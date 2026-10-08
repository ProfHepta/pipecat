"""Minimal local-model adapters using Pipecat's native STT/TTS lifecycle."""
import asyncio
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.services.settings import STTSettings,TTSSettings
from pipecat.transcriptions.language import Language
from pipecat.frames.frames import TranscriptionFrame,TTSStartedFrame,TTSStoppedFrame,TTSAudioRawFrame
from pipecat.utils.time import time_now_iso8601

class SenseVoiceSTTService(SegmentedSTTService):
    def __init__(self,models):
        super().__init__(sample_rate=16000,trailing_silence_secs=.3,settings=STTSettings(model='sensevoice-int8',language=Language.ZH))
        self.models=models
    @property
    def wants_wav_segments(self):return False
    async def run_stt(self,audio):
        text=await self.models.decode(audio,self.sample_rate)
        if text:yield TranscriptionFrame(text,self._user_id,time_now_iso8601(),language=Language.ZH,finalized=True)

class MeloTTSService(TTSService):
    def __init__(self,models):
        super().__init__(sample_rate=16000,settings=TTSSettings(model='melo-fp32',voice='0',language=Language.ZH))
        self.models=models
    async def run_tts(self,text,context_id):
        yield TTSStartedFrame(context_id=context_id)
        pcm=await self.models.synth(text)
        for start in range(0,len(pcm),6400):
            yield TTSAudioRawFrame(pcm[start:start+6400],16000,1,context_id=context_id)
        yield TTSStoppedFrame(context_id=context_id)
