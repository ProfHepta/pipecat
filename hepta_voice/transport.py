"""Authenticated PCM is wrapped by native Pipecat input/output transports.
Native schedulers own output queues; the write hook models physical PCM pacing.
No microphone or phone device is opened.
"""
import asyncio,base64,time
from pipecat.transports.base_transport import BaseTransport,TransportParams
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.frames.frames import InputAudioRawFrame,InterruptionFrame
from .control import checked_id

class PCMInput(BaseInputTransport):
    def __init__(self,params):super().__init__(params);self.ready=asyncio.Event()
    async def start(self,frame):
        await super().start(frame);await self.set_transport_ready(frame);self.ready.set()

class PCMOutput(BaseOutputTransport):
    def __init__(self,params,state):super().__init__(params);self.state=state;self.ready=asyncio.Event()
    async def start(self,frame):
        await super().start(frame);await self.set_transport_ready(frame);self.ready.set()
    async def process_frame(self,frame,direction):
        if isinstance(frame,InterruptionFrame):
            # Native scheduler cancels/drains its own queues before acknowledging a flush.
            await super().process_frame(frame,direction)
            self.state.epoch+=1
            await self.state.emit({'type':'flush','epoch':self.state.epoch,'reason':'pipecat_interruption'})
        else:await super().process_frame(frame,direction)
    async def write_audio_frame(self,frame):
        if self.state.closed:return False
        self.state.audio_frames+=1
        if self.state.first_audio is None:self.state.first_audio=time.monotonic()
        await self.state.emit({'type':'audio','epoch':self.state.epoch,'pcm':base64.b64encode(frame.audio).decode(),'sample_rate':frame.sample_rate})
        await asyncio.sleep(len(frame.audio)/(frame.sample_rate*frame.num_channels*2))
        return True

class PocketPCMTransport(BaseTransport):
    def __init__(self,state):
        super().__init__()
        params=TransportParams(audio_in_enabled=True,audio_in_sample_rate=16000,audio_out_enabled=True,
          audio_out_sample_rate=16000,audio_out_10ms_chunks=2,audio_out_auto_silence=False,audio_out_end_silence_secs=0)
        self._input=PCMInput(params);self._output=PCMOutput(params,state)
    def input(self):return self._input
    def output(self):return self._output
