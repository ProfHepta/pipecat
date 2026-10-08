"""Finite crash test of only hepta-pipecat-lab, followed by explicit CPU-only restart."""
import asyncio,json,os,sqlite3,subprocess,time,uuid
from pathlib import Path
import aiohttp
DATA=Path(os.environ.get('HEPTA_VOICE_DATA',str(Path.home()/'.local/share/hepta-pipecat')))
ENV={**os.environ,'XDG_RUNTIME_DIR':f'/run/user/{os.getuid()}'}
def status(rid):
    c=sqlite3.connect('file:'+str(DATA/'state/ledger.sqlite3')+'?mode=ro',uri=True)
    try:
        row=c.execute('SELECT status FROM requests WHERE id=?',(rid,)).fetchone();return row[0] if row else None
    finally:c.close()
async def main():
    out={}
    def save():
        (DATA/'evidence/pipecat-recovery.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False),flush=True)
    def client():return aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=str(DATA/'state/agent.sock')),headers={'Authorization':'Bearer '+(DATA/'state/access.token').read_text().strip()},timeout=aiohttp.ClientTimeout(total=10))
    rid='pipecat_crash_'+uuid.uuid4().hex;prompt='请用两句话介绍太阳系。'
    h=client()
    async with h.get('http://localhost/health') as r:health=await r.json()
    assert health['ready'] and not health['active_session'] and not health['gpu_enabled']
    ws=await h.ws_connect('http://localhost/session');assert (await ws.receive_json(timeout=20))['type']=='ready'
    await ws.send_json({'type':'text','id':rid,'text':prompt})
    while True:
        e=await ws.receive_json(timeout=20)
        if e['type']=='turn_started':break
        if e['type']=='error':raise RuntimeError(e)
    assert status(rid)=='pending';out['before_crash']={'id':rid,'status':'pending'};save()
    subprocess.run(['docker','kill','--signal=KILL','hepta-pipecat-lab'],check=True,capture_output=True,timeout=10)
    await ws.close();await h.close();t=time.monotonic()
    subprocess.run(['systemctl','--user','restart','hepta-pipecat.service'],env=ENV,check=True,timeout=25)
    for _ in range(120):
        try:
            async with client() as h:
                async with h.get('http://localhost/health') as r:health=await r.json()
            if health.get('ready'):break
        except (aiohttp.ClientError,asyncio.TimeoutError):pass
        await asyncio.sleep(1)
    else:raise RuntimeError('cpu_restart_failed')
    assert status(rid)=='unknown' and not health['gpu_enabled']
    out['after_restart']={'elapsed_seconds':time.monotonic()-t,'status':status(rid),'gpu_enabled':health['gpu_enabled']};save()
    async with client() as h:
        async with h.ws_connect('http://localhost/session') as ws:
            assert (await ws.receive_json(timeout=20))['type']=='ready'
            await ws.send_json({'type':'text','id':rid,'text':prompt})
            while True:
                e=await ws.receive_json(timeout=10)
                if e['type']!='flush':break
            assert e['type']=='duplicate' and e['status']=='unknown';out['retry']=e
            await ws.send_json({'type':'end'})
        async with h.post('http://localhost/tools/local-note',json={'id':'acceptance_note_20261008','text':'语音验收专用本地测试记录，不是实际业务操作。'}) as r:j=await r.json()
        assert j.get('duplicate');out['original_note']=j
    out['completed']=True;save()
asyncio.run(main())
