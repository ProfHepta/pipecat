"""Host-side broker for ONE existing read-only Pocket4 diagnostic.
No free-form shell, file API, phone control, contacts, SMS or trading operations.
"""
import asyncio,datetime,json,os,re
from pathlib import Path
from aiohttp import web
from .config import DATA, STATE
ROOT=DATA
COMMAND=('/usr/bin/ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=5',
         'pocket4','/usr/bin/python3','/opt/pocket4-telephony/call-audio-watch.py','--inspect')

def validate(payload):
    if type(payload) is not dict or set(payload)!={'id','name','arguments'}:raise ValueError('invalid_envelope')
    if not isinstance(payload['id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,96}',payload['id']):raise ValueError('invalid_id')
    if payload['name']!='telephone_status':raise ValueError('tool_not_allowed')
    if type(payload['arguments']) is not dict or payload['arguments']:raise ValueError('arguments_not_allowed')
    return payload['id']

async def inspect():
    p=await asyncio.create_subprocess_exec(*COMMAND,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        stdout,stderr=await asyncio.wait_for(p.communicate(),8)
        if p.returncode!=0 or len(stdout)>65536:raise RuntimeError('diagnostic_failed')
        raw=json.loads(stdout)
        if raw.get('code')!='READ_ONLY_AUDIO_READY':raise RuntimeError('audio_not_ready')
        count=raw.get('active_call_count')
        if type(count) is not int or not 0<=count<=1 or raw.get('loopbacks_started') is not False:raise RuntimeError('unexpected_diagnostic')
        return {'target':'pocket4','physical_audio_ready':True,'active_call_count':count,
                'real_incoming_call_verified':False,'remote_audibility_verified':False,
                'phone_control_performed':False,'source':'existing call-audio-watch.py --inspect'}
    finally:
        if p.returncode is None:
            p.terminate()
            try:await asyncio.wait_for(p.wait(),1)
            except asyncio.TimeoutError:p.kill();await p.wait()

async def main():
    os.umask(0o077);gate=asyncio.Semaphore(1)
    async def call(req):
        try:payload=await req.json();rid=validate(payload)
        except (ValueError,TypeError):return web.json_response({'error':'tool_not_allowed_or_invalid'},status=400)
        try:
            async with gate:result=await inspect()
        except (RuntimeError,asyncio.TimeoutError,json.JSONDecodeError):
            return web.json_response({'id':rid,'status':'failed','result':None},status=503)
        return web.json_response({'id':rid,'name':'telephone_status','status':'ok','read_only':True,
              'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'result':result})
    async def health(req):return web.json_response({'ready':True,'allowed_tools':['telephone_status'],'write_tools':[]})
    app=web.Application(client_max_size=2048);app.router.add_post('/call',call);app.router.add_get('/health',health)
    runner=web.AppRunner(app,access_log=None);await runner.setup();p=STATE/'tools.sock'
    if p.exists():p.unlink()
    await web.UnixSite(runner,str(p)).start();os.chmod(p,0o600)
    print('read_only_tool_broker_ready',flush=True)
    try:await asyncio.Event().wait()
    finally:await runner.cleanup()
if __name__=='__main__':asyncio.run(main())
