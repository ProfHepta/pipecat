"""Bounded real Pipecat acceptance with synthetic audio, never a live phone call."""
import asyncio,base64,io,json,os,time,uuid,wave
from pathlib import Path
import aiohttp
DATA=Path(os.environ.get('HEPTA_VOICE_DATA',str(Path.home()/'.local/share/hepta-pipecat')))
OUT=DATA/'evidence/pipecat-acceptance.json';OUT.parent.mkdir(exist_ok=True);result={}
def save(key,value):
    result[key]=value;OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(key,json.dumps(value,ensure_ascii=False),flush=True)
async def main():
    async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=str(DATA/'state/agent.sock')),
        headers={'Authorization':'Bearer '+(DATA/'state/access.token').read_text().strip()},timeout=aiohttp.ClientTimeout(total=120)) as client:
        for _ in range(120):
            try:
                async with client.get('http://localhost/health') as r:j=await r.json()
                if j.get('ready'):break
            except (aiohttp.ClientError,asyncio.TimeoutError):pass
            await asyncio.sleep(1)
        else:raise RuntimeError('new_service_not_ready')
        assert j['framework']=='pipecat' and j['version']=='1.12.0' and not j['gpu_enabled'];save('health',j)
        async with client.get('http://localhost/network-proof') as r:j=await r.json()
        save('network',j);assert j['ipv4']==101 and j['ipv6']==101
        async with client.get('http://localhost/health',headers={'Authorization':'Bearer invalid'}) as r:assert r.status==401;save('unauthorized',r.status)
        async with client.post('http://localhost/asr',data=(DATA/'fixtures/input-8k.wav').read_bytes()) as r:j=await r.json();assert r.status==200;save('real_sensevoice',j)
        note={'id':'acceptance_note_20261008','text':'语音验收专用本地测试记录，不是实际业务操作。'}
        async with client.post('http://localhost/tools/local-note',json=note) as r:j=await r.json();assert j.get('duplicate');save('original_note_preserved',j)
        async def turn(ws,prompt,rid=None):
            rid=rid or uuid.uuid4().hex;t=time.monotonic();first=None;receipts=[];guards=[]
            await ws.send_json({'type':'text','id':rid,'text':prompt})
            while True:
                event=await ws.receive_json(timeout=100)
                if event['type']=='audio' and first is None:first=time.monotonic()-t
                if event['type']=='tool_receipt':receipts.append(event['receipt'])
                if event['type']=='policy_guard':guards.append(event['reason'])
                if event['type'] in ('turn_done','error','duplicate'):
                    row={'id':rid,'prompt':prompt,'event':event,'first_frame_seconds':first,'receipts':receipts,'guards':guards}
                    print('TURN',json.dumps(row,ensure_ascii=False),flush=True);return row
        rows=[]
        async with client.ws_connect('http://localhost/session') as ws:
            ready=await ws.receive_json(timeout=20);assert ready['type']=='ready',ready
            async with client.post('http://localhost/tts',json={'text':'并发'}) as r:assert r.status==409;save('single_session',r.status)
            for prompt,expected in [('三加五等于几？','八'),('我说错了，是三加六等于几？','九')]:
                row=await turn(ws,prompt);rows.append(row);save('text_turns',rows)
                assert row['event']['type']=='turn_done' and expected in row['event']['text'],row
            stable=rows[-1]
            row=await turn(ws,'请实际调用只读工具查询Pocket4的活动通话数量和音频端点。');save('native_function_call',row)
            assert row['event']['type']=='turn_done' and len(row['receipts'])==1
            row=await turn(ws,'预约工具超时了，是不是说明预约失败？');save('unknown_result_policy',row)
            assert '不能直接认定成功或失败' in row['event'].get('text','')
            rid=uuid.uuid4().hex
            await ws.send_json({'type':'text','id':rid,'text':'请用两句话介绍太阳系。'})
            while True:
                event=await ws.receive_json(timeout=100)
                if event['type']=='audio':old=event['epoch'];break
                if event['type']=='error':raise RuntimeError(event)
            t=time.monotonic();await ws.send_json({'type':'interrupt'})
            while True:
                event=await ws.receive_json(timeout=15)
                if event['type']=='flush':delay=(time.monotonic()-t)*1000;break
            stale=0;end=time.monotonic()+.7
            while time.monotonic()<end:
                try:event=await ws.receive_json(timeout=end-time.monotonic())
                except asyncio.TimeoutError:break
                if event['type']=='audio' and event['epoch']==old:stale+=1
            save('native_interruption',{'flush_ms':delay,'stale_frames_after_ack':stale});assert stale==0
            row=await turn(ws,'停止上个话题，只回答三加五等于几。');save('post_interruption',row)
            assert '太阳系' not in row['event'].get('text','') and row['event']['type']=='turn_done'
            await ws.send_json({'type':'end'})
        await asyncio.sleep(.5)
        async with client.ws_connect('http://localhost/session') as ws:
            assert (await ws.receive_json())['type']=='ready'
            dup=await turn(ws,stable['prompt'],stable['id']);save('cross_session_dedup',dup);assert dup['event']['type']=='duplicate'
            await ws.send_json({'type':'end'})
        await asyncio.sleep(.5)
        raw=(DATA/'fixtures/input-8k.wav').read_bytes()
        with wave.open(io.BytesIO(raw)) as w:pcm=w.readframes(w.getnframes());assert w.getframerate()==8000
        async with client.ws_connect('http://localhost/session') as ws:
            assert (await ws.receive_json())['type']=='ready'
            await ws.send_json({'type':'format','sample_rate':8000})
            async def feed():
                for i in range(0,len(pcm),320):await ws.send_bytes(pcm[i:i+320]);await asyncio.sleep(.02)
                for _ in range(150):await ws.send_bytes(bytes(320));await asyncio.sleep(.02)
            task=asyncio.create_task(feed());transcript=None;count=0
            try:
                while True:
                    event=await ws.receive_json(timeout=100)
                    if event['type']=='transcript_final':transcript=event['text']
                    if event['type']=='audio':count+=1
                    if event['type'] in ('turn_done','error'):
                        save('native_vad_audio_pipeline',{'transcript':transcript,'audio_frames':count,'event':event});break
                assert event['type']=='turn_done' and count>0 and transcript
                await task;await ws.send_json({'type':'end'})
            finally:
                if not task.done():task.cancel()
        save('completed',True)
try:asyncio.run(main())
except Exception as e:save('fatal',{'type':type(e).__name__,'message':str(e)});raise
