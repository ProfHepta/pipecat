"""Run only the already-qualified Vulkan/FA-on engine on the authorized Pocket4.
No model download, GPU eviction, phone actions, or permission changes.
"""
import fcntl,hashlib,json,os,signal,socket,subprocess,time
from pathlib import Path
ROOT=Path.home()/'.local/share/hepta-inference'
STATE=Path.home()/'.local/state/hepta-inference'
BENCH=STATE/'ab-20261009'
COMMIT='d81235049384534c167caea52b85a694f6103d14'
MODEL_SHA='85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9'
BIN_SHA='5faf410bbbc00a1b94b09ee01623699f255365628dfa73b1ee552d9e52a2231d'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

def main():
    os.umask(0o077)
    lock=os.open(f'/run/user/{os.getuid()}/hepta-gpu-inference.lock',os.O_CREAT|os.O_RDWR,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    binary=ROOT/'builds/vulkan/llama-b11429/llama-server'
    model=ROOT/'models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
    bench=json.loads((BENCH/'benchmark.json').read_text())
    cell=next(c for c in bench['cells'] if c['backend']=='vulkan' and c['flash_attention_requested'])
    if cell['status']!='completed' or bench['commit']!=COMMIT:raise RuntimeError('unqualified_engine')
    if digest(binary)!=BIN_SHA or digest(model)!=MODEL_SHA:raise RuntimeError('artifact_identity_mismatch')
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',18455))==0:raise RuntimeError('engine_port_occupied')
    gpu=Path('/sys/class/drm/card1/device')
    if int((gpu/'mem_info_vram_used').read_text())>2*1024**3:raise RuntimeError('gpu_memory_busy_no_eviction')
    if int((gpu/'gpu_busy_percent').read_text())>30:raise RuntimeError('gpu_busy_no_eviction')
    env={k:v for k,v in os.environ.items() if not k.startswith(('LLAMA_','GGML_','HIP_VISIBLE','HSA_OVERRIDE'))}
    env.update(GGML_VK_VISIBLE_DEVICES='0',OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='1',LC_ALL='C',LD_LIBRARY_PATH=str(binary.parent))
    args=[str(binary),'-m',str(model),'-c','4096','-np','1','-ngl','99','-b','512','-ub','512','-t','4','-tb','4','-ctk','f16','-ctv','f16','-fa','on','-lv','4','--host','127.0.0.1','--port','18455','--alias','hepta-qwen3-4b','--jinja','--no-webui','--api-key-file',str(BENCH/'api.key')]
    child=None
    try:
        child=subprocess.Popen(args,env=env)
        def stop(*_):
            if child.poll() is None:child.terminate()
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        record={'pid':child.pid,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'start_ticks':Path(f'/proc/{child.pid}/stat').read_text().split()[21], 'commit':COMMIT,'binary_sha256':BIN_SHA,'model_sha256':MODEL_SHA,'backend':'Vulkan','flash_attention':True,'context':4096,'slots':1,'kv':'f16','port':18455,'created_unix':time.time()}
        temp=STATE/'engine-instance.tmp';temp.write_text(json.dumps(record,indent=2));temp.replace(STATE/'engine-instance.json')
        return child.wait()
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:child.wait(10)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        os.close(lock)
if __name__=='__main__':raise SystemExit(main())
