"""Bounded Pocket4 synthetic audio roundtrip. Service secret stays on qian-qi.
SSH uses existing trust, no SSH configuration or host-key changes.
"""
import asyncio,base64,hashlib,json,sys,time,os
from pathlib import Path
import aiohttp
R=Path(os.environ.get('HEPTA_VOICE_DATA',str(Path.home()/'.local/share/hepta-pipecat')))
async def main():
    proc=await asyncio.create_subprocess_exec('ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
        '-o','ConnectTimeout=8','pocket4','/usr/bin/python3','/home/alex/hepta-voice-client/pocket_fixture_client.py',
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    async def read():
        line=await asyncio.wait_for(proc.stdout.readline(),90)
        if not line:raise RuntimeError('remote_endpoint_closed')
        return json.loads(line)
    async def write(obj):proc.stdin.write((json.dumps(obj,ensure_ascii=False)+'\n').encode());await proc.stdin.drain()
    try:
        ready=await read();expected=hashlib.sha256((R/'fixtures/input-8k.wav').read_bytes()).hexdigest()
        assert ready['type']=='endpoint_ready' and ready['input_sha256']==expected
        async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=str(R/'state/agent.sock')),
             headers={'Authorization':'Bearer '+(R/'state/access.token').read_text().strip()},timeout=aiohttp.ClientTimeout(total=90)) as h:
            async with h.ws_connect('http://localhost/session') as ws:
                assert (await ws.receive_json())['type']=='ready'
                await ws.send_json({'type':'format','sample_rate':8000});await write({'type':'start'})
                output=hashlib.sha256();frames=0;transcript=None;receipt=None
                async def uplink():
                    nonlocal receipt
                    while True:
                        e=await read()
                        if e['type']=='input_audio':
                            b=base64.b64decode(e['pcm'],validate=True)
                            if len(b)>320 or len(b)%2:raise ValueError('bad_remote_frame')
                            await ws.send_bytes(b)
                        elif e['type']=='endpoint_receipt':receipt=e;return
                        elif e['type']=='endpoint_error':raise RuntimeError(e.get('code'))
                sender=asyncio.create_task(uplink())
                try:
                    while True:
                        e=await ws.receive_json(timeout=60)
                        if e['type']=='transcript_final':transcript=e['text']
                        if e['type']=='audio':output.update(base64.b64decode(e['pcm'],validate=True));frames+=1
                        if e['type'] in ('flush','audio','turn_done','error'):await write(e)
                        if e['type'] in ('turn_done','error'):break
                    await asyncio.wait_for(sender,10);await ws.send_json({'type':'end'})
                finally:
                    if not sender.done():sender.cancel()
                if receipt is None:raise RuntimeError('missing_remote_receipt')
                assert receipt['output_pcm_sha256']==output.hexdigest() and receipt['audio_frames']==frames
                result={'scope':'Pipecat actual cross-host synthetic PCM; no hardware playback or telephone',
                    'remote':ready['hostname'],'transcript':transcript,'sha256_both_directions_match':True,
                    'service_secret_copied':False,'endpoint_receipt':receipt,'checked_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
                (R/'evidence/pipecat-cross-host.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:
        if proc.stdin:proc.stdin.close()
        try:await asyncio.wait_for(proc.wait(),5)
        except asyncio.TimeoutError:proc.terminate();await proc.wait()
asyncio.run(main())
