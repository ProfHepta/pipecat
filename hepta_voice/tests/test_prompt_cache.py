import pytest
from hepta_voice.prompt_cache import FixedPromptCache

def test_cache_is_exact_identity_and_bytes():
 c=FixedPromptCache('identity');pcm=bytes(32000)
 assert c.add('你好。',pcm,'你好','identity')
 assert c.get('你好。','identity')==pcm
 assert c.get('你好。','changed-model') is None
 assert c.get('你好。已完成预约。','identity') is None

def test_negation_loss_is_not_cached():
 c=FixedPromptCache('identity')
 assert not c.add('我是人工智能语音助手，不是真人接线员。',bytes(32000),'我是人工智能语音助手，我是真人接线员。','identity')
 assert c.get('我是人工智能语音助手，不是真人接线员。','identity') is None

@pytest.mark.parametrize('text',['订单已支付。','三加五等于八。','预约时间是三点。','电话音频端点检查通过，当前有零个活动通话。'])
def test_facts_and_tool_results_cannot_be_cached(text):
 with pytest.raises(ValueError):FixedPromptCache('x').add(text,bytes(32000),text,'x')

def test_cache_model_and_memory_bounds():
 c=FixedPromptCache('x',640)
 with pytest.raises(ValueError):c.add('你好。',bytes(642),'你好','x')
 with pytest.raises(ValueError):c.add('你好。',bytes(640),'你好','y')

def test_cache_identity_includes_lexicon_and_synthesis_configuration(tmp_path):
 from hepta_voice.prompt_cache import cache_identity
 weights=tmp_path/'weights';words=tmp_path/'lexicon';weights.write_bytes(b'model');words.write_bytes(b'words')
 files={'model':weights,'lexicon':words};config={'rate':16000,'speaker':0,'speed':1}
 one=cache_identity(files,'sherpa-test',config)
 assert one==cache_identity(dict(reversed(list(files.items()))),'sherpa-test',config)
 words.write_bytes(b'changed words');assert one!=cache_identity(files,'sherpa-test',config)
 assert one!=cache_identity(files,'sherpa-next',config)
 assert one!=cache_identity(files,'sherpa-test',{**config,'speed':2})
