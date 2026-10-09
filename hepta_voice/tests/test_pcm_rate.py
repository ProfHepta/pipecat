import numpy as np
import pytest
from pipecat.frames.frames import InputAudioRawFrame
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.base_input import BaseInputTransport
from hepta_voice.transport import PCMInput

@pytest.mark.asyncio
async def test_eight_kilohertz_stream_is_actually_resampled_not_relabelled(monkeypatch):
 frames=[]
 async def capture(self,frame):frames.append(frame)
 monkeypatch.setattr(BaseInputTransport,'push_audio_frame',capture)
 inp=PCMInput(TransportParams(audio_in_enabled=True))
 x=(np.sin(2*np.pi*1000*np.arange(8000)/8000)*10000).astype('<i2')
 for i in range(0,len(x),160):await inp.push_audio_frame(InputAudioRawFrame(x[i:i+160].tobytes(),8000,1))
 assert frames and all(f.sample_rate==16000 and f.num_channels==1 for f in frames)
 # A streaming FIR retains a tail; finish it before asserting total samples.
 # This tests exact duration preservation instead of guessing a latency bound.
 tail=await inp._resampler.flush()
 y=np.frombuffer(b''.join(f.audio for f in frames)+tail,dtype='<i2').astype(float)
 assert len(y)==16000
 frequencies=np.fft.rfftfreq(len(y),1/16000);peak=frequencies[np.argmax(np.abs(np.fft.rfft(y)))]
 assert abs(peak-1000)<3,'8k payload must not be interpreted as 16k (which doubles pitch)'

@pytest.mark.asyncio
async def test_sixteen_kilohertz_bytes_are_unchanged(monkeypatch):
 frames=[]
 async def capture(self,frame):frames.append(frame)
 monkeypatch.setattr(BaseInputTransport,'push_audio_frame',capture)
 x=np.arange(320,dtype='<i2').tobytes();inp=PCMInput(TransportParams(audio_in_enabled=True))
 await inp.push_audio_frame(InputAudioRawFrame(x,16000,1));assert frames[0].audio==x

@pytest.mark.asyncio
async def test_rate_switch_and_non_mono_are_rejected(monkeypatch):
 async def discard(*args):pass
 monkeypatch.setattr(BaseInputTransport,'push_audio_frame',discard)
 inp=PCMInput(TransportParams(audio_in_enabled=True))
 await inp.push_audio_frame(InputAudioRawFrame(bytes(320),8000,1))
 with pytest.raises(ValueError):await inp.push_audio_frame(InputAudioRawFrame(bytes(640),16000,1))
 with pytest.raises(ValueError):await PCMInput(TransportParams(audio_in_enabled=True)).push_audio_frame(InputAudioRawFrame(bytes(640),8000,2))
