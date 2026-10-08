"""Exact local-UDS adapter; only a real checked receipt can produce a tool result."""
import aiohttp
from pathlib import Path
TOOLS=[{'type':'function','function':{'name':'telephone_status','description':'只读检查Pocket4当前活动通话数量与物理音频端点。不能证明远端听感，不会接听、拨号或发送短信。','parameters':{'type':'object','properties':{},'required':[],'additionalProperties':False}}}]
async def execute(name,arguments,rid):
    if name!='telephone_status' or type(arguments) is not dict or arguments:raise ValueError('unapproved_tool_call')
    from .config import STATE
    async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=str(STATE/'tools.sock')),
                                    timeout=aiohttp.ClientTimeout(total=12),trust_env=False) as client:
        async with client.post('http://localhost/call',json={'id':rid,'name':name,'arguments':arguments}) as response:
            response.raise_for_status();receipt=await response.json()
    if receipt.get('id')!=rid or receipt.get('name')!=name or receipt.get('status')!='ok' or receipt.get('read_only') is not True:
        raise RuntimeError('invalid_tool_receipt')
    result=receipt.get('result',{});n=result.get('active_call_count')
    if type(n) is not int or not 0<=n<=1 or result.get('physical_audio_ready') is not True or result.get('phone_control_performed') is not False:
        raise RuntimeError('invalid_tool_result')
    count='零' if n==0 else '一'
    spoken=f'口袋电脑的音频端点检查通过，当前有{count}个活动通话。真实来电与远端听感还没有验收。'
    return receipt,spoken
