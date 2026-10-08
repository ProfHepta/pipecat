"""Finite outage of only the newly installed read-only Pipecat broker, with restore."""
import asyncio,json,os,subprocess,time,uuid
from pathlib import Path
import aiohttp
DATA=Path(os.environ.get('HEPTA_VOICE_DATA',str(Path.home()/'.local/share/hepta-pipecat')))
ENV={**os.environ,'XDG_RUNTIME_DIR':f'/run/user/{os.getuid()}'}
async def main():
    result={};unit='hepta-pipecat-tools.service'
    def record():
        (DATA/'evidence/pipecat-tool-failure.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False),flush=True)
    async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=str(DATA/'state/agent.sock')),headers={'Authorization':'Bearer '+(DATA/'state/access.token').read_text().strip()},timeout=aiohttp.ClientTimeout(total=120)) as client:
        async with client.get('http://localhost/health') as r:health=await r.json()
        assert health['ready'] and not health['active_session']
        try:
            subprocess.run(['systemctl','--user','stop',unit],env=ENV,check=True,timeout=10)
            async with client.ws_connect('http://localhost/session') as ws:
                assert (await ws.receive_json(timeout=20))['type']=='ready'
                await ws.send_json({'type':'text','id':uuid.uuid4().hex,'text':'请调用telephone_status，只读查看当前电话状态。该工具没有参数。'})
                receipts=[];text=None
                while True:
                    e=await ws.receive_json(timeout=100)
                    if e['type']=='tool_receipt':receipts.append(e['receipt'])
                    if e['type'] in ('turn_done','error'):text=e;break
                result['outage']={'event':text,'success_receipts':len(receipts)};record()
                assert not receipts and text['type']=='turn_done' and '尚未确认' in text.get('text','')
                await ws.send_json({'type':'end'})
        finally:subprocess.run(['systemctl','--user','start',unit],env=ENV,check=True,timeout=10)
        for _ in range(30):
            try:
                async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=str(DATA/'state/tools.sock')),timeout=aiohttp.ClientTimeout(total=1)) as h:
                    async with h.post('http://localhost/call',json={'id':uuid.uuid4().hex,'name':'telephone_status','arguments':{}}) as r:j=await r.json()
                if j.get('status')=='ok':result['restored_receipt']=j;break
            except (aiohttp.ClientError,asyncio.TimeoutError):pass
            await asyncio.sleep(.2)
        else:raise RuntimeError('broker_restore_failed')
        result['completed']=True;record()
asyncio.run(main())
