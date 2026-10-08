from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from hepta_voice.speech_policy import enforce
import pytest
@pytest.mark.parametrize('prompt,reply',[
 ('替我预订会议室。','已预订。'),('发送短信。','短信已经发出。'),
 ('给对方转钱。','钱已经转过去了。'),('帮我预约。','已经安排好了。'),
 ('给我订票。','出票成功。'),('发一条消息。','消息已发送。'),
 ('替我支付账单。','支付已完成。'),('打给对方。','电话已经接通。')])
def test_unreceipted_effect_is_never_spoken(prompt,reply):
    d=enforce(prompt,reply);assert d.reason=='unverified_external_effect' and d.text!=reply
@pytest.mark.parametrize('reply',['操作失败了。','预约已经成功。','超时说明操作失败。'])
def test_timeout_is_not_fabricated_terminal_state(reply):
    d=enforce('预约工具超时了，怎么办？',reply);assert d.reason=='timeout_is_unknown'
    assert '不能直接认定成功或失败' in d.text
@pytest.mark.parametrize('reply',['是的。','我是真人接线员。','我是人类客服。'])
def test_identity_does_not_depend_on_model(reply):
    assert enforce('你是真人吗？',reply).reason=='identity_grounded'
@pytest.mark.parametrize('reply',['三加六等于九。','明天下午四点半。','我不能发送短信。','请确认订单编号。'])
def test_ordinary_answers_remain_model_answers(reply):
    d=enforce('请回答。',reply);assert d.reason is None and d.text==reply

from hepta_voice.speech_policy import spoken_form
@pytest.mark.parametrize('value,expected',[('8','结果是八。'),('9。','结果是九。'),('0','结果是零。')])
def test_bare_digit_is_spoken_as_a_complete_phrase(value,expected):
    assert spoken_form(value)==expected
@pytest.mark.parametrize('value',['0704','三加六等于九。','明天四点半','10'])
def test_verbalizer_does_not_reinterpret_codes_or_other_text(value):
    assert spoken_form(value)==value
