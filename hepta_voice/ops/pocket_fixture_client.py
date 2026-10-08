"""Synthetic audio endpoint over an already-authorized SSH stdio channel.
No microphone, telephone, credentials, listening sockets, or shell execution.
"""
import base64,hashlib,json,math,os,signal,struct,sys,threading,time,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parent
WAV=ROOT/'fixtures/question-8k.wav';OUT=ROOT/'run';OUT.mkdir(exist_ok=True)
lock=threading.Lock();state={'last_speech':None,'first_audio':None,'input_finished':False,'last_speech_ns':None,'first_audio_ns':None}
CLOCK_ID='pocket-monotonic:'+Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def emit(obj):
    with lock:sys.stdout.write(json.dumps(obj,ensure_ascii=False)+'\n');sys.stdout.flush()
def send_audio():
    with wave.open(str(WAV),'rb') as w:
        if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,8000):raise ValueError('fixture_format')
        if w.getnframes()>8000*15:raise ValueError('fixture_too_long')
        pcm=w.readframes(w.getnframes())
    blocks=[pcm[i:i+320] for i in range(0,len(pcm),320)]
    voiced=[]
    for index,b in enumerate(blocks):
        samples=struct.unpack('<'+'h'*(len(b)//2),b)
        if samples and math.sqrt(sum(v*v for v in samples)/len(samples))>500:voiced.append(index)
    last_voiced=max(voiced,default=-1)
    for index,i in enumerate(range(0,len(pcm),320)):
        b=pcm[i:i+320];samples=struct.unpack('<'+'h'*(len(b)//2),b)
        if samples and math.sqrt(sum(v*v for v in samples)/len(samples))>500:state['last_speech']=time.monotonic()
        emit({'type':'input_audio','pcm':base64.b64encode(b).decode()})
        if index==last_voiced:
            state['last_speech_ns']=time.monotonic_ns()
            emit({'type':'input_end_marker'})
        time.sleep(.02)
    state['input_finished']=True
    for _ in range(80):emit({'type':'input_audio','pcm':base64.b64encode(bytes(320)).decode()});time.sleep(.02)
    emit({'type':'input_finished'})
signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(TimeoutError('fixture_deadline')));signal.alarm(90)
emit({'type':'endpoint_ready','input_sha256':hashlib.sha256(WAV.read_bytes()).hexdigest(),'hostname':os.uname().nodename})
epoch=-1;frames=[];stale=0;started=False;first_before_input_end=False
for line in sys.stdin:
    if len(line)>65536:raise ValueError('message_too_large')
    e=json.loads(line);typ=e.get('type')
    if typ=='start':
        if started:raise ValueError('duplicate_start')
        started=True;threading.Thread(target=send_audio,daemon=True).start()
    elif typ=='flush':epoch=e['epoch'];frames=[]
    elif typ=='audio':
        if e['epoch']<epoch:stale+=1;continue
        if e['epoch']!=epoch:raise ValueError('unexpected_audio_generation')
        b=base64.b64decode(e['pcm'],validate=True)
        if len(b)>640 or len(b)%2:raise ValueError('bad_output_pcm')
        if len(frames)>3000:raise ValueError('output_audio_limit')
        if state['first_audio'] is None:
            state['first_audio']=time.monotonic();state['first_audio_ns']=time.monotonic_ns();first_before_input_end=not state['input_finished']
        frames.append(b)
    elif typ=='turn_done':
        payload=b''.join(frames);path=OUT/'received-answer.wav'
        with wave.open(str(path),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(payload)
        receipt={'type':'endpoint_receipt','input_sha256':hashlib.sha256(WAV.read_bytes()).hexdigest(),
         'output_pcm_sha256':hashlib.sha256(payload).hexdigest(),'output_bytes':len(payload),
         'audio_frames':len(frames),'stale_frames':stale,'response_text':e.get('text'),
         'speech_end_to_first_received_audio_seconds':None if state['first_audio'] is None or state['last_speech'] is None else state['first_audio']-state['last_speech'],
         'endpoint_clock_id':CLOCK_ID,'source_last_active_frame_sent_ns':state['last_speech_ns'],'sink_first_frame_received_ns':state['first_audio_ns'],
         'voice_host_timeline':e.get('timeline'),'speech_end_definition':'synthetic last frame RMS>500; frame resolution20ms; not human acoustic endpoint',
         'first_audio_before_input_finished':first_before_input_end,'human_listened':False,'telephone_used':False}
        (OUT/'fixture-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));emit(receipt);break
    elif typ=='error':emit({'type':'endpoint_error','code':e.get('code')});break
signal.alarm(0)
