"""Deterministic continuous PCM resampling for ASR, without int16 output dither.
Use SoXR float32 filtering and explicit round-to-even PCM quantization. Keep
filter history across chunks and pauses; flush/reset only at stream boundaries.
"""
import numpy as np
import soxr
class PCMResampler:
    def __init__(self,quality='HQ'):
        if quality!='HQ':raise ValueError('unqualified_resampler_quality')
        self._quality=quality;self._stream=None;self._rates=None
    @staticmethod
    def _pcm(samples):
        return np.clip(np.rint(samples*32768.0),-32768,32767).astype('<i2').tobytes()
    async def resample(self,audio,in_rate,out_rate):
        if in_rate not in (8000,16000) or out_rate!=16000 or len(audio)%2:raise ValueError('invalid_resampling_format')
        rates=(in_rate,out_rate)
        if self._rates is not None and rates!=self._rates:raise ValueError('resampler_rate_change')
        self._rates=rates
        if in_rate==out_rate:return audio
        if self._stream is None:self._stream=soxr.ResampleStream(in_rate,out_rate,1,dtype='float32',quality=self._quality)
        samples=np.frombuffer(audio,dtype='<i2').astype(np.float32)/32768.0
        return self._pcm(self._stream.resample_chunk(samples,last=False))
    async def flush(self):
        if self._stream is None:return b''
        tail=self._pcm(self._stream.resample_chunk(np.empty(0,dtype=np.float32),last=True))
        self._stream=None;self._rates=None;return tail
    async def reset(self):self._stream=None;self._rates=None

