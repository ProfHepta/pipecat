"""Local authenticated Unix socket endpoint; Pipecat owns the conversation pipeline."""
import asyncio,contextlib,io,json,os,secrets,signal,socket,time,uuid,wave
from importlib.metadata import version
import aiohttp
from loguru import logger
import sys
logger.remove();logger.add(sys.stderr,level="WARNING")
from aiohttp import web,WSMsgType
from pipecat.frames.frames import TranscriptionFrame,InputAudioRawFrame,InterruptionFrame
from pipecat.utils.time import time_now_iso8601
from .config import DATA,STATE,MODEL
from .control import Ledger,Rejected,checked_id
from .lease import Lease
from .models import Models
from .pipeline import State,build
from .llama_client import verify_engine_properties
from .endpoint_attestation import validate_local_endpoint_files
from .timing import CLOCK_ID

def read_wav(raw):
    with wave.open(io.BytesIO(raw)) as w:
        if (w.getnchannels(),w.getsampwidth())!=(1,2) or w.getframerate() not in (8000,16000):raise Rejected('mono_s16_8k_or_16k_required')
        rate=w.getframerate();n=w.getnframes()
        if not rate*.1<=n<=rate*30:raise Rejected('audio_duration_out_of_range')
        pcm=w.readframes(n)
        if len(pcm)!=n*2:raise Rejected('truncated_wav')
        return pcm,rate

def wav(pcm):
    b=io.BytesIO()
    with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(pcm)
    return b.getvalue()

async def main():
    os.umask(0o077);STATE.mkdir(parents=True,exist_ok=True)
    # No automatic fallback to the removed local Ollama backend.
    validate_local_endpoint_files(STATE)
    lease=Lease(STATE/'pipeline-owner.lock').acquire()
    token=(STATE/'access.token').read_text().strip()
    if len(token)<32:raise RuntimeError('invalid_auth_token')
    ledger=Ledger(STATE/'ledger.sqlite3');models=Models();busy=False
    engine_key=(STATE/'llama.key').read_text().strip()
    http=aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=str(STATE/'llama.sock')),
        headers={'Authorization':'Bearer '+engine_key},timeout=aiohttp.ClientTimeout(total=30),trust_env=False)
    async with http.get('http://localhost/health') as r:
        r.raise_for_status();assert (await r.json()).get('status')=='ok'
    async with http.get('http://localhost/props') as r:
        r.raise_for_status();verify_engine_properties(await r.json())
    await models.synth('你好。')
    @web.middleware
    async def auth(req,handler):
        if not secrets.compare_digest(req.headers.get('Authorization',''),'Bearer '+token):raise web.HTTPUnauthorized()
        try:return await handler(req)
        except (Rejected,ValueError,TypeError,KeyError,AttributeError,wave.Error,json.JSONDecodeError) as e:return web.json_response({'error':str(e)[:150]},status=400)
    app=web.Application(middlewares=[auth],client_max_size=2*1024*1024)
    async def health(req):
        try:
            async with http.get('http://localhost/health') as r:
                r.raise_for_status();loaded=(await r.json()).get('status')=='ok'
            async with http.get('http://localhost/props') as r:
                r.raise_for_status();verify_engine_properties(await r.json())
        except (aiohttp.ClientError,asyncio.TimeoutError,RuntimeError):loaded=False
        return web.json_response({'ready':loaded,'framework':'pipecat','version':version('pipecat-ai'),'model':MODEL,
          'active_session':busy,'gpu_enabled':False,'llm_engine':'llama.cpp','llm_gpu_host':'pocket4','llm_gpu_requested':True,'production_ready':False,'phone_authority':False,'microphone_open':False,
          'write_tools':[],'read_only_tools':['telephone_status'],'network_interfaces':socket.if_nameindex()})
    async def network(req):
        out={}
        for name,fam,addr in [('ipv4',socket.AF_INET,('1.1.1.1',443)),('ipv6',socket.AF_INET6,('2606:4700:4700::1111',443))]:
            with socket.socket(fam) as s:s.settimeout(.5);out[name]=s.connect_ex(addr)
        out['interfaces']=socket.if_nameindex();return web.json_response(out)
    async def asr(req):
        nonlocal busy
        pcm,rate=read_wav(await req.read())
        if busy:raise web.HTTPConflict(text='one_session_limit')
        busy=True
        try:
            t=time.monotonic();text=await models.decode(pcm,rate)
            return web.json_response({'text':text,'seconds':time.monotonic()-t})
        finally:busy=False
    async def tts(req):
        nonlocal busy
        text=(await req.json()).get('text')
        if not isinstance(text,str) or not 1<=len(text.strip())<=200:raise Rejected('invalid_text')
        if busy:raise web.HTTPConflict(text='one_session_limit')
        busy=True
        try:return web.Response(body=wav(await models.synth(text)),content_type='audio/wav')
        finally:busy=False
    async def note(req):
        j=await req.json();return web.json_response(ledger.local_note(j.get('id'),j.get('text')))
    async def session(req):
        nonlocal busy
        if busy:raise web.HTTPConflict(text='one_session_limit')
        busy=True;ws=web.WebSocketResponse(max_msg_size=8192,heartbeat=15);state=None;runner=None;job=None
        try:
            await ws.prepare(req);state=State(ws,ledger)
            transport,worker,runner,context=build(state,models)
            await runner.add_workers(worker);job=asyncio.create_task(runner.run())
            await asyncio.wait_for(transport.input().ready.wait(),15)
            await asyncio.wait_for(transport.output().ready.wait(),15)
            await state.emit({'type':'ready','sample_rate':16000,'out_sample_rate':16000,'framework':'pipecat'})
            await state.emit({'type':'flush','epoch':state.epoch,'reason':'session_started'})
            rate=16000;received=0;first_input=None
            async for message in ws:
                try:
                    if message.type==WSMsgType.BINARY:
                        raw=message.data
                        if len(raw)%2 or not 0<len(raw)<=rate*2//5:raise Rejected('invalid_pcm_frame')
                        if first_input is None:first_input=time.monotonic()
                        received+=len(raw)
                        if received>rate*2*(time.monotonic()-first_input+2):raise Rejected('audio_arrived_too_fast')
                        if time.monotonic()-first_input>300:raise Rejected('session_time_limit')
                        await transport.input().push_audio_frame(InputAudioRawFrame(raw,rate,1))
                    elif message.type==WSMsgType.TEXT:
                        j=json.loads(message.data);typ=j.get('type')
                        if typ=='format':
                            if received or state.active or state.pending:raise Rejected('mid_session_format_change')
                            if j.get('sample_rate') not in (8000,16000):raise Rejected('invalid_sample_rate')
                            rate=j['sample_rate']
                        elif typ=='text':
                            text=j.get('text');rid=checked_id(j.get('id'))
                            if not isinstance(text,str) or not 1<=len(text.strip())<=1000:raise Rejected('invalid_text')
                            r=state.reserve(rid,text)
                            if r['duplicate']:await state.emit({'type':'duplicate','id':rid,'status':r['status']});continue
                            f=TranscriptionFrame(text,'local',time_now_iso8601(),finalized=True);f.metadata['request_id']=rid
                            await worker.queue_frame(f)
                        elif typ=='input_end_marker':
                            state.input_end_ingress_ns=time.monotonic_ns()
                        elif typ=='clock_probe':
                            await state.emit({'type':'clock_probe','clock_id':CLOCK_ID,'server_monotonic_ns':time.monotonic_ns()})
                        elif typ=='interrupt':await worker.queue_frame(InterruptionFrame())
                        elif typ=='end':break
                        else:raise Rejected('unsupported_message')
                except (Rejected,ValueError,TypeError,AttributeError) as e:await state.emit({'type':'error','code':str(e)[:150]})
        except Exception as e:
            import traceback;traceback.print_exc()
            if state:await state.emit({'type':'error','code':'pipeline_failed','detail':type(e).__name__})
            else:raise
        finally:
            if state:
                state.closed=True;state.cancel_active()
                if state.pending:ledger.finish(state.pending[0],'interrupted')
            if runner:
                with contextlib.suppress(Exception):await runner.cancel()
            if job:
                with contextlib.suppress(asyncio.CancelledError,Exception):await asyncio.wait_for(job,10)
            busy=False
        return ws
    app.router.add_get('/health',health);app.router.add_get('/network-proof',network)
    app.router.add_post('/asr',asr);app.router.add_post('/tts',tts);app.router.add_post('/tools/local-note',note)
    app.router.add_get('/session',session)
    runner=web.AppRunner(app,access_log=None);await runner.setup();sock=STATE/'agent.sock'
    if sock.exists():sock.unlink()
    await web.UnixSite(runner,str(sock)).start();os.chmod(sock,0o600)
    print(json.dumps({'ready':True,'framework':'pipecat','version':version('pipecat-ai'),'gpu_enabled':False}),flush=True)
    stop=asyncio.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):asyncio.get_running_loop().add_signal_handler(sig,stop.set)
    try:await stop.wait()
    finally:
        await runner.cleanup();await http.close();models.close();ledger.close();lease.close()
if __name__=='__main__':asyncio.run(main())
