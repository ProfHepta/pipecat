"""Finite isolated Whisper/NPU probe. No microphone, phone, GPU, or production replacement."""
import hashlib,json,os,signal,socket,subprocess,time,urllib.request,urllib.error,uuid,wave
from pathlib import Path
ROOT=Path.home()/'.local/share/hepta-npu-lab';E=Path.home()/'.local/state/hepta-npu-probe-20261009'
APP=ROOT/'fastflowlm-1.0.7/opt/fastflowlm';BIN=APP/'bin/flm';BASE='http://127.0.0.1:18466'
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}));RESULT={'scope':'standalone_npu_asr_synthetic_8khz','llm_gpu_started':False,'production_asr_replaced':False,'stages':{}};process=None

def save():
    p=E/'asr-result.tmp';p.write_text(json.dumps(RESULT,ensure_ascii=False,indent=2));p.replace(E/'asr-result.json')

def post_audio(path,deadline=60):
    boundary='hepta_'+uuid.uuid4().hex;data=path.read_bytes()
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nwhisper-v3\r\n--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nzh\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="sample.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()+data+f'\r\n--{boundary}--\r\n'.encode())
    request=urllib.request.Request(BASE+'/v1/audio/transcriptions',data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    t=time.monotonic()
    with OPENER.open(request,timeout=deadline) as response:j=json.load(response)
    return j,time.monotonic()-t

def flm_processes():
    found=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            if (p/'exe').resolve()!=BIN:continue
            fds=[]
            for fd in (p/'fd').iterdir():
                try:
                    target=os.readlink(fd)
                    if '/dev/accel/' in target:fds.append(target)
                except OSError:pass
            found.append({'pid':int(p.name),'npu_fds':fds,'maps_whisper_npu':'libwhisper_npu.so' in (p/'maps').read_text()})
        except (OSError,PermissionError):pass
    return found

try:
    assert hashlib.sha256(BIN.read_bytes()).hexdigest()=='ae6ac97c1520fd1ab5f2194c57b9bdf3dd32f527a0794315cb99ae2d62a1c48c'
    manifest=json.loads((E/'whisper-manifest.json').read_text());model=ROOT/'data/models/Whisper-V3-Turbo-NPU2'
    for item in manifest['files']:
        h=hashlib.sha256()
        with (model/item['file']).open('rb') as f:
            for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
        assert h.hexdigest()==item['observed_sha256']
    RESULT['model_revision']=manifest['revision'];RESULT['model_sha256']=next(x['observed_sha256'] for x in manifest['files'] if x['file']=='model.q4nx')
    fixtures=json.loads((ROOT/'asr-fixtures/manifest.json').read_text())['samples']
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',18466))!=0
    assert not flm_processes(),'another_flm_owner'
    library_path=f'{APP}/lib:{ROOT}/deps/usr/lib/x86_64-linux-gnu:/opt/xilinx/xrt/lib'
    args=['/usr/bin/timeout','--signal=TERM','--kill-after=5s','240s','sudo','-n','prlimit','--memlock=6442450944:6442450944','--','setpriv','--reuid=1000','--regid=1000','--init-groups','--no-new-privs','env',f'HOME={ROOT}/home',f'LD_LIBRARY_PATH={library_path}',f'FLM_MODEL_PATH={ROOT}/data',f'FLM_CONFIG_PATH={APP}/share/flm/model_list.json',f'FLM_XCLBIN_PATH={APP}/share/flm','XILINX_XRT=/opt/xilinx/xrt','FLM_DISABLE_UPDATE_CHECK=1','OMP_NUM_THREADS=2',str(BIN),'serve','--asr','1','--host','127.0.0.1','--port','18466','--cors','0','--socket','1','--q-len','1','--pmode','balanced']
    logfile=(E/'flm-asr.log').open('w');t=time.monotonic();process=subprocess.Popen(args,stdout=logfile,stderr=subprocess.STDOUT,start_new_session=True,cwd=ROOT)
    for _ in range(150):
        if process.poll() is not None:raise RuntimeError('flm_exited_before_ready:'+str(process.returncode))
        try:
            with OPENER.open(BASE+'/v1/models',timeout=1) as response:models=json.load(response)
            break
        except (urllib.error.URLError,TimeoutError,ConnectionError):time.sleep(.2)
    else:raise RuntimeError('flm_startup_timeout')
    RESULT['startup_seconds']=time.monotonic()-t;RESULT['models_response']=models;RESULT['process_hardware_evidence']=flm_processes();save()
    rows=[]
    for repeat in range(3):
        for sample in fixtures:
            path=ROOT/'asr-fixtures'/sample['file'];assert hashlib.sha256(path.read_bytes()).hexdigest()==sample['sha256']
            response,elapsed=post_audio(path)
            row={'sample_id':sample['id'],'repeat':repeat,'reference':sample['reference'],'duration_seconds':sample['duration_seconds'],'response':response,'asr_seconds':elapsed,'real_time_factor':elapsed/sample['duration_seconds'],'sensevoice_baseline_text':sample['sensevoice_text'],'sensevoice_baseline_seconds':sample['sensevoice_seconds']}
            rows.append(row);RESULT['trials']=rows;save();print(json.dumps(row,ensure_ascii=False),flush=True)
    RESULT['completed']=True;RESULT['hardware_after_trials']=flm_processes();save()
except Exception as exc:
    RESULT['completed']=False;RESULT['error']={'type':type(exc).__name__,'message':str(exc)};save();print('FAILED',json.dumps(RESULT['error']),flush=True)
finally:
    if process and process.poll() is None:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(8)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.wait()
    RESULT['remaining_flm_processes']=flm_processes();RESULT['finished_unix']=time.time();save();print('FINAL',json.dumps({k:v for k,v in RESULT.items() if k not in ('trials','models_response')},ensure_ascii=False),flush=True)
