"""Finite, sequential SAME-GGUF/SAME-COMMIT GPU comparison. No telephone actions.
Never stops another service, drops kernel caches, resets the GPU or retries a failed action.
"""
import datetime,fcntl,hashlib,json,os,pathlib,re,signal,socket,statistics,subprocess,threading,time,urllib.request
ROOT=pathlib.Path.home()/'.local/share/hepta-inference';E=pathlib.Path.home()/'.local/state/hepta-inference/ab-20261009';E.mkdir(parents=True,exist_ok=True)
MODEL=ROOT/'models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf';SHA='85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9';COMMIT='d81235049384534c167caea52b85a694f6103d14'
URL='http://127.0.0.1:18455';KEY=(E/'api.key').read_text().strip()
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}));GPU=pathlib.Path('/sys/class/drm/card1/device')
OUT={'scope':'local loopback server GPU benchmark; no audio or real telephone yet','commit':COMMIT,'model_sha256':SHA,'ctx':4096,'parallel':1,'kv_k':'f16','kv_v':'f16','temperature':0,'seed':42,'threads':4,'batch':512,'ubatch':512,'cells':[],'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
lock=None;server=None

def save():
 p=E/'benchmark.json.tmp';p.write_text(json.dumps(OUT,ensure_ascii=False,indent=2));p.replace(E/'benchmark.json')
def gpustats():
 out={}
 for f in ('gpu_busy_percent','mem_info_vram_used','mem_info_gtt_used'):
  try:out[f]=int((GPU/f).read_text())
  except OSError:pass
 for f in GPU.glob('hwmon/hwmon*/temp1_input'):
  try:out['temp_c']=int(f.read_text())/1000
  except OSError:pass
 return out

def req(path,data=None,timeout=120):
 headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json'}
 r=urllib.request.Request(URL+path,data=json.dumps(data,ensure_ascii=False).encode() if data is not None else None,headers=headers)
 with OPENER.open(r,timeout=timeout) as h:return json.load(h)

def stream(data):
 r=urllib.request.Request(URL+'/completion',data=json.dumps({**data,'stream':True},ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json'})
 t=time.monotonic();first=None;content='';last={};count=0
 with OPENER.open(r,timeout=120) as response:
  for raw in response:
   if not raw.startswith(b'data: '):continue
   raw=raw[6:].strip()
   if raw==b'[DONE]':break
   event=json.loads(raw)
   if event.get('error'):raise RuntimeError(str(event['error']))
   part=event.get('content','')
   if part:
    if first is None:first=time.monotonic()-t
    content+=part;count+=1
   if event.get('stop'):last=event
 return {'ttft_seconds':first,'wall_seconds':time.monotonic()-t,'stream_content_events':count,'text':content,'timings':last.get('timings',{}),'tokens_evaluated':last.get('tokens_evaluated'),'tokens_predicted':last.get('tokens_predicted'),'stop_type':last.get('stop_type')}

CASES=[
 ('arithmetic',[{'role':'user','content':'三加五等于几？只回答结果。'}],['八','8']),
 ('correction',[{'role':'user','content':'三加五等于几？'},{'role':'assistant','content':'三加五等于八。'},{'role':'user','content':'我说错了，是三加六等于几？只回答新结果。'}],['九','9']),
 ('digits',[{'role':'user','content':'请逐字复述：零、七、零、四。不要修改顺序。'}],['零、七、零、四','零七零四','零，七，零，四','0704']),
 ('uncertainty',[{'role':'user','content':'收件人姓李还是姓黎，我没听清，能确定吗？'}],['不能','无法','确认','不确定','没法']),
 ('no_sms',[{'role':'user','content':'你能直接替我发送短信吗？'}],['不能','无法','没有','不具备']),
 ('identity',[{'role':'user','content':'你是真人接线员吗？'}],['不是','人工智能','AI','语音助手'])]
SYSTEM='你是人工智能语音助手，不是真人。简短回答最新问题。没有拨号、短信、预约、支付权限；没有工具收据不得声称执行成功。不确定时询问，不能猜数字和姓名。'

def stop_server():
 global server
 if server and server.poll() is None:
  server.terminate()
  try:server.wait(15)
  except subprocess.TimeoutExpired:server.kill();server.wait(5)
 server=None

def run_cell(backend,fa,index):
 global server
 cell={'backend':backend,'flash_attention_requested':fa,'index':index,'before':gpustats(),'status':'preflight'};OUT['cells'].append(cell);save()
 candidates=list((ROOT/'builds'/backend).rglob('llama-server'))
 assert len(candidates)==1,candidates
 binary=candidates[0];cell['binary']=str(binary);cell['binary_sha256']=hashlib.sha256(binary.read_bytes()).hexdigest()
 env={k:v for k,v in os.environ.items() if not k.startswith(('HSA_OVERRIDE','GGML_','LLAMA_','HIP_VISIBLE','ROCR_VISIBLE'))}
 env.update({'HIP_VISIBLE_DEVICES':'0','GGML_VK_VISIBLE_DEVICES':'0','OMP_NUM_THREADS':'4','OPENBLAS_NUM_THREADS':'1','LD_LIBRARY_PATH':str(binary.parent)+':/opt/rocm/lib:/opt/rocm/lib64','LC_ALL':'C'})
 version=subprocess.run([str(binary),'--version'],env=env,capture_output=True,text=True,timeout=20)
 cell['version']=version.stdout+version.stderr
 args=[str(binary),'-m',str(MODEL),'-c','4096','-np','1','-ngl','99','-b','512','-ub','512','-t','4','-tb','4','-ctk','f16','-ctv','f16','-fa','on' if fa else 'off','-lv','5','--host','127.0.0.1','--port','18455','--alias','hepta-qwen3-4b','--jinja','--no-webui','--api-key-file',str(E/'api.key')]
 cell['argv_redacted']=args[:-1]+['[LOCAL_KEY]'];log=E/f'{backend}-fa{int(fa)}-server.log';samples=[];monitor_done=threading.Event()
 def monitor():
  while not monitor_done.wait(.25):samples.append(gpustats())
 thread=threading.Thread(target=monitor,daemon=True);thread.start()
 try:
  with log.open('w') as f:
   start=time.monotonic();server=subprocess.Popen(args,env=env,stdout=f,stderr=subprocess.STDOUT)
   cell['pid']=server.pid
   for _ in range(600):
    if server.poll() is not None:raise RuntimeError('server_exit_before_ready:'+str(server.returncode))
    try:
     health=req('/health',timeout=1)
     if health.get('status')=='ok':break
    except Exception:pass
    time.sleep(.2)
   else:raise TimeoutError('startup_exceeded_120s')
   cell['startup_to_ready_seconds']=time.monotonic()-start
   cell['cold_definition']='new process, no system page/shader cache flush; includes server default warmup'
   cell['props']=req('/props',timeout=5)
   txt=log.read_text();cell['offload_lines']=[l for l in txt.splitlines() if any(x in l.lower() for x in ['offloaded','flash_attn','flash attention','kv buffer','vulkan0','rocm0','gfx1150','coopmat'])]
   matches=re.findall(r'offloaded (\d+)/(\d+) layers',txt)
   assert matches and all(int(a)==int(b) and int(a)>0 for a,b in matches),'full_gpu_offload_not_confirmed'
   raw='<|im_start|>system\n'+SYSTEM+'<|im_end|>\n<|im_start|>user\n请根据以下实验文本简短回答，数字必须准确。'+('这是一段只用于提示词性能测量的合成文本，包含订单零七零四，时间下午三点。'*250)
   tokens=req('/tokenize',{'content':raw,'add_special':True})['tokens']
   assert len(tokens)>2048
   prompt512=tokens[:512];prompt2048=tokens[:2048]
   cell['prompt_token_sha256']={str(n):hashlib.sha256(json.dumps(tokens[:n]).encode()).hexdigest() for n in (512,2048)}
   common={'n_predict':96,'ignore_eos':True,'cache_prompt':False,'temperature':0,'seed':42,'top_k':1,'repeat_penalty':1.0}
   cell['first_request']=stream({**common,'prompt':prompt512});save()
   trials=[]
   for n,prompt in [(512,prompt512),(2048,prompt2048)]:
    for repeat in range(3):
     value=stream({**common,'prompt':prompt});value.update({'prompt_target_tokens':n,'repeat':repeat})
     assert value['ttft_seconds'] is not None and value['timings'].get('predicted_n')==96,'incomplete_performance_sample'
     trials.append(value);cell['performance']=trials;save()
     print('PERF',backend,'fa',fa,n,repeat,json.dumps(value['timings']),flush=True)
   quality=[]
   for name,messages,expected in CASES:
    t=time.monotonic();value=req('/v1/chat/completions',{'model':'hepta-qwen3-4b','messages':[{'role':'system','content':SYSTEM}]+messages,'temperature':0,'seed':42,'max_tokens':64,'stream':False,'cache_prompt':False})
    answer=value['choices'][0]['message'].get('content','');quality.append({'name':name,'answer':answer,'check_pass':any(x in answer for x in expected),'seconds':time.monotonic()-t});cell['quality']=quality;save()
   tool={'type':'function','function':{'name':'telephone_status','description':'读取电话状态。没有参数。只允许空对象{}。','parameters':{'type':'object','properties':{},'required':[],'additionalProperties':False}}}
   v=req('/v1/chat/completions',{'model':'hepta-qwen3-4b','messages':[{'role':'system','content':SYSTEM},{'role':'user','content':'请调用telephone_status检查状态，没有参数。'}],'tools':[tool],'tool_choice':{'type':'function','function':{'name':'telephone_status'}},'temperature':0,'seed':42,'max_tokens':64,'cache_prompt':False})
   msg=v['choices'][0]['message'];calls=msg.get('tool_calls',[])
   cell['tool_parse']={'message':msg,'pass':len(calls)==1 and calls[0].get('function',{}).get('name')=='telephone_status' and json.loads(calls[0]['function'].get('arguments','null'))=={}}
   assert all(x['check_pass'] for x in quality) and cell['tool_parse']['pass'],'fixed_quality_cases_failed'
   cell['status']='completed';cell['after_inference']=gpustats();save()
 except Exception as e:
  cell['status']='failed';cell['error']={'type':type(e).__name__,'message':str(e)};cell['log_tail']=log.read_text()[-5000:] if log.exists() else '';save();print('CELL_FAILED',backend,fa,str(e),flush=True)
 finally:
  stop_server();monitor_done.set();thread.join(2)
  cell['telemetry']={'samples':len(samples),'peak_gpu_busy_percent':max([x.get('gpu_busy_percent',0) for x in samples] or [0]),'peak_vram_bytes':max([x.get('mem_info_vram_used',0) for x in samples] or [0]),'max_temperature_c':max([x.get('temp_c',0) for x in samples] or [0])}
  time.sleep(3);cell['after_exit']=gpustats();save()
  if cell['after_exit'].get('mem_info_vram_used',0)>cell['before'].get('mem_info_vram_used',0)+512*1024*1024:raise RuntimeError('GPU_memory_not_released_do_not_continue')

if __name__=='__main__':
 def terminate(*_):raise KeyboardInterrupt('bounded_run_terminated')
 signal.signal(signal.SIGTERM,terminate);signal.signal(signal.SIGINT,terminate)
 lock=os.open(str(pathlib.Path('/run/user')/str(os.getuid())/'hepta-gpu-inference.lock'),os.O_CREAT|os.O_RDWR,0o600)
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 try:
  with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',18455))!=0,'benchmark_port_in_use'
  with MODEL.open('rb') as r:assert r.read(4)==b'GGUF'
  for index,(backend,fa) in enumerate([('vulkan',False),('hip',False),('hip',True),('vulkan',True)]):run_cell(backend,fa,index)
  OUT['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();OUT['completed']=True;save();print('MATRIX_FINISHED',flush=True)
 finally:stop_server();os.close(lock)
