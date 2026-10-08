"""Deterministic verbal authority checks, separate from model quality.
This is defense in depth, NOT a claim of perfect semantic detection.
External write actions remain unavailable regardless of generated words.
"""
from dataclasses import dataclass
import re
@dataclass(frozen=True)
class Decision:
    text:str
    reason:str|None=None
OPERATIONS=r'发(?:送|出)|预[约订]|订票|订位|付款|支付|转账|汇款|出票|拨号|拨打|接听|接通|改签'
COMPLETED=re.compile(r'(?:已经|现已|已)(?:.{0,12})(?:'+OPERATIONS+r')|(?:'+OPERATIONS+r')(?:.{0,10})(?:成功|完毕|完成|办妥|好了|过去了|出去了)|(?:短信|消息|邮件|款项|订单|预约|机票)(?:.{0,8})(?:已经|已)(?:.{0,8})(?:发|付|转|取消|确认|完成)|(?:钱|款项|资金).{0,12}(?:转|汇).{0,6}(?:过去了|出去了|完成|成功)')
INDIRECT=re.compile(r'办妥了|办好了|安排好了|安排妥了|处理好了|已经完成|已经搞定|发好了|已完成')
REQUEST_ACTION=re.compile(OPERATIONS+r'|发短信|转钱|订房|订餐|订一张|订一间|取消订单|取消预约')

def enforce(request:str,reply:str)->Decision:
    if re.search(r'你.{0,12}(?:真人|人类|人吗|机器人|人工智能)',request) or re.search(r'(?<!不)是(?:一名|一个)?真人|我是人类',reply):
        return Decision('我是人工智能语音助手，不是真人接线员。','identity_grounded')
    if '超时' in request+reply and re.search(r'工具|请求|订单|预[约订]|转账|支付|短信|任务',request+reply):
        return Decision('超时只表示结果尚未确认，不能直接认定成功或失败。应该先核对原请求状态，不要盲目重试。','timeout_is_unknown')
    if COMPLETED.search(reply) or (REQUEST_ACTION.search(request) and INDIRECT.search(reply)):
        return Decision('我没有执行任何外部操作，也没有对应的真实工具收据，不能确认已经完成。','unverified_external_effect')
    return Decision(reply)

def spoken_form(reply:str)->str:
    """Give a bare single-digit answer a complete Chinese spoken phrase.
    Preserve original model text separately; never reinterpret identifiers or dates.
    """
    match=re.fullmatch(r'\s*([0-9])[。.!！]?\s*',reply)
    if match:return '结果是'+'零一二三四五六七八九'[int(match.group(1))]+'。'
    return reply
