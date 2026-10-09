"""Whole-turn local ASR with a separate, bounded post-VAD commit window.
VAD remains 0.5 seconds. No partial transcript, LLM request or tool execution
is published while continuation audio is still eligible to extend this turn.
"""
import asyncio,time
from dataclasses import dataclass
from pipecat.frames.frames import InputAudioRawFrame,UserAudioRawFrame,TranscriptionFrame
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601
from .services import SenseVoiceSTTService

@dataclass(frozen=True)
class CommittedAudio:
    pcm: bytes
    generation: int
    end_marker_ns: int | None
    segments: int
    sample_rate: int = 16000

class CoalescingSenseVoiceSTTService(SenseVoiceSTTService):
    def __init__(self,models,state=None,*,settle_seconds=1.3,max_seconds=30.0):
        if not 0.75<=settle_seconds<=1.5:raise ValueError('invalid_coalescing_settle_window')
        if not 1<=max_seconds<=30:raise ValueError('invalid_coalescing_audio_limit')
        super().__init__(models,state)
        self._settle_seconds=settle_seconds
        self._max_seconds=max_seconds;self._source_rate=None
        self._max_bytes=int((max_seconds-.3)*16000*2)
        self._preroll_limit=16000*2  # Preserve native SegmentedSTTService's 1-second pre-roll.
        self._preroll=bytearray();self._whole_turn=bytearray()
        self._collecting=False;self._speaking=False;self._discard_until_stop=False
        self._pending_release=None;self._generation=0;self._turn_segments=0;self._vad_end_bytes=0
        self.cancelled_transcripts_dropped=0
    async def process_audio_frame(self,frame:InputAudioRawFrame,direction):
        if frame.sample_rate!=16000 or frame.num_channels!=1 or len(frame.audio)%2:
            raise ValueError('coalescer_requires_mono_s16_16k')
        self._user_id=frame.user_id if isinstance(frame,UserAudioRawFrame) else ''
        pcm=frame.metadata.get('hepta_source_pcm',frame.audio)
        rate=frame.metadata.get('hepta_source_rate',frame.sample_rate)
        if rate not in (8000,16000) or type(pcm) is not bytes or len(pcm)%2:raise ValueError('invalid_original_pcm')
        if self._source_rate is not None and rate!=self._source_rate:raise ValueError('original_rate_changed')
        self._source_rate=rate;self._max_bytes=int((self._max_seconds-.3)*rate*2);self._preroll_limit=rate*2
        if self._discard_until_stop:return
        if self._collecting:
            if len(self._whole_turn)+len(pcm)>self._max_bytes:
                await self.abandon_input();raise ValueError('coalescer_max_speech_duration')
            self._whole_turn+=pcm
        else:
            self._preroll+=pcm
            if len(self._preroll)>self._preroll_limit:del self._preroll[:-self._preroll_limit]
    async def _discard_pending(self):
        self._generation+=1;t=self._pending_release;self._pending_release=None
        if t and not t.done():await self.cancel_task(t)
    async def abandon_input(self):
        """Explicit client cancel/text supersession: never reactivate old waveform or ASR."""
        discard_current_speech=self._speaking or self._discard_until_stop
        await self._discard_pending()
        self._whole_turn.clear();self._preroll.clear();self._collecting=False
        self._speaking=False;self._user_speaking=False;self._vad_end_bytes=0;self._turn_segments=0
        self._discard_until_stop=discard_current_speech
        if self.state is not None:self.state.input_end_ingress_ns=None
        while not self._segment_queue.empty():
            item=self._segment_queue.get_nowait()
            if item is None:
                await self._segment_queue.put(None);break
    async def _handle_user_started_speaking(self,frame):
        if self._discard_until_stop:return
        self._user_speaking=True;self._speaking=True
        await self._discard_pending()
        if not self._collecting:
            self._whole_turn=bytearray(self._preroll);self._preroll.clear();self._collecting=True;self._turn_segments=0
    async def _handle_user_stopped_speaking(self,frame):
        self._user_speaking=False;self._speaking=False
        if self._discard_until_stop:
            self._discard_until_stop=False;self._preroll.clear();return
        if not self._collecting:return
        self._turn_segments+=1;self._vad_end_bytes=len(self._whole_turn)
        await self._discard_pending();g=self._generation
        self._pending_release=self.create_task(self._publish_when_settled(g),f'{self}::coalescing_settle')
    async def _publish_when_settled(self,g):
        try:
            await asyncio.sleep(self._settle_seconds)
            if self._speaking or not self._collecting or g!=self._generation:return
            # Do not change acoustic padding merely because a decision waited.
            rate=self._source_rate or 16000
            pcm=bytes(self._whole_turn[:self._vad_end_bytes])+bytes(int(self._trailing_silence_secs*rate)*2)
            n=self._turn_segments;marker=self.state.input_end_ingress_ns if self.state is not None else None
            self._whole_turn.clear();self._preroll.clear();self._collecting=False;self._turn_segments=0
            if len(pcm)<640:return
            self._stt_usage_pending_seconds+=len(pcm)/(rate*2);await self.emit_stt_usage_metrics()
            await self._segment_queue.put(CommittedAudio(pcm,g,marker,n,rate))
        finally:
            if g==self._generation:self._pending_release=None
    async def _segment_task_handler(self):
        while True:
            item=await self._segment_queue.get()
            if item is None:return
            if not isinstance(item,CommittedAudio):raise TypeError('unbound_asr_segment')
            if item.generation!=self._generation:continue
            stages={'asr_start':time.monotonic_ns()}
            if item.end_marker_ns is not None:stages['input_end_ingress']=item.end_marker_ns
            try:text=await self.models.decode(item.pcm,item.sample_rate)
            except asyncio.CancelledError:raise
            except Exception as exc:
                if item.generation==self._generation:await self.push_error(f'whole-turn ASR failed: {type(exc).__name__}')
                continue
            if item.generation!=self._generation or (self.state is not None and self.state.closed):
                self.cancelled_transcripts_dropped+=1;continue
            stages['asr_final']=time.monotonic_ns()
            if self.state is not None and self.state.input_end_ingress_ns==item.end_marker_ns:self.state.input_end_ingress_ns=None
            if text:
                frame=TranscriptionFrame(text,self._user_id,time_now_iso8601(),language=Language.ZH,finalized=True)
                frame.metadata['hepta_stages_ns']=stages
                frame.metadata['coalesced_segments']=item.segments
                frame.metadata['asr_input_rate']=item.sample_rate
                await self.push_frame(frame)
    async def stop(self,frame):
        await self.abandon_input();await super().stop(frame)
    async def cancel(self,frame):
        await self.abandon_input();await super().cancel(frame)
    async def cleanup(self):
        await self.abandon_input();await super().cleanup()

