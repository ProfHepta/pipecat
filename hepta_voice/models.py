"""Reuse pinned local SenseVoice/Melo assets; all heavy work is CPU-only and serialized."""
import asyncio,concurrent.futures,io,math,wave
import numpy as np
import sherpa_onnx
from scipy.signal import resample_poly
from .config import MODELS

class Models:
    def __init__(self):
        p=MODELS/'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09'
        self.asr=sherpa_onnx.OfflineRecognizer.from_sense_voice(model=str(p/'model.int8.onnx'),tokens=str(p/'tokens.txt'),num_threads=2,provider='cpu',language='zh',use_itn=False)
        p=MODELS/'vits-melo-tts-zh_en'
        cfg=sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(p/'model.onnx'),tokens=str(p/'tokens.txt'),lexicon=str(p/'lexicon.txt')),num_threads=2,provider='cpu'),rule_fsts=','.join(str(p/x) for x in ('phone.fst','date.fst','number.fst')),max_num_sentences=1)
        if not cfg.validate():raise RuntimeError('invalid_local_tts_config')
        self.tts=sherpa_onnx.OfflineTts(cfg)
        self.asr_pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.tts_pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
    @staticmethod
    def resample(x,rate,out=16000):
        if rate==out:return x
        g=math.gcd(rate,out);return resample_poly(x,out//g,rate//g).astype(np.float32)
    def decode_sync(self,pcm,rate):
        if rate not in (8000,16000) or len(pcm)%2 or len(pcm)>rate*2*30:raise ValueError('invalid_audio_segment')
        x=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
        stream=self.asr.create_stream();stream.accept_waveform(16000,self.resample(x,rate));self.asr.decode_stream(stream)
        return stream.result.text.strip()
    async def decode(self,pcm,rate):
        return await asyncio.get_running_loop().run_in_executor(self.asr_pool,self.decode_sync,pcm,rate)
    def synth_sync(self,text):
        if not isinstance(text,str) or not 1<=len(text.strip())<=1000:raise ValueError('invalid_tts_text')
        a=self.tts.generate(text,sid=0,speed=1.0)
        pcm=self.resample(a.samples,a.sample_rate)
        return (np.clip(pcm,-1,1)*32767).astype('<i2').tobytes()
    async def synth(self,text):
        return await asyncio.get_running_loop().run_in_executor(self.tts_pool,self.synth_sync,text)
    def close(self):
        self.asr_pool.shutdown(wait=True,cancel_futures=True);self.tts_pool.shutdown(wait=True,cancel_futures=True)
