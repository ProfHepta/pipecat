from pathlib import Path
import pytest
from hepta_voice.lease import Lease
from hepta_voice.control import Ledger,Rejected
from hepta_voice.server import read_wav
from hepta_voice.services import SenseVoiceSTTService,MeloTTSService
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.services.ollama.llm import OLLamaLLMService
from hepta_voice.config import OLLAMA
import io,wave

def test_real_upstream_service_contracts():
    assert issubclass(SenseVoiceSTTService,SegmentedSTTService)
    assert issubclass(MeloTTSService,TTSService)
    assert OLLAMA=='http://127.0.0.1:11445/v1'

def test_exclusive_service_owner(tmp_path):
    a=Lease(tmp_path/'owner').acquire()
    try:
        with pytest.raises(RuntimeError):Lease(tmp_path/'owner').acquire()
    finally:a.close()
    with Lease(tmp_path/'owner'):pass

def test_original_r2_request_identity_survives(tmp_path):
    p=tmp_path/'requests.sqlite3';old=Ledger(p)
    payload={'scope':'voice-r2','text':'检查状态'}
    old.reserve('migration_test_001','speech',payload);old.close()
    new=Ledger(p)
    result=new.reserve('migration_test_001','speech',payload)
    assert result['duplicate'] and result['status']=='unknown'
    with pytest.raises(Rejected):new.reserve('migration_test_001','speech',{'scope':'voice-r2','text':'改了内容'})
    new.close()

def sample():
    b=io.BytesIO()
    with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(bytes(3200))
    return b.getvalue()

def test_wav_validation():
    pcm,rate=read_wav(sample());assert rate==8000 and len(pcm)==3200
    with pytest.raises(Rejected):read_wav(sample()[:100])

from hepta_voice.pipeline import ClosedFunctionSchema

def test_native_function_schema_is_closed():
    definition=ClosedFunctionSchema(name='telephone_status',description='fixed',properties={},required=[]).to_default_dict()
    assert definition['strict'] is True
    assert definition['parameters']['additionalProperties'] is False
    assert definition['parameters']['properties']=={}
