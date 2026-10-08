"""Actual Pipecat Pipeline, VAD/turn aggregation, local Ollama and native function calling."""
import asyncio,json,time,uuid
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (TranscriptionFrame,LLMFullResponseStartFrame,LLMFullResponseEndFrame,LLMTextFrame,InterruptionFrame,ErrorFrame,FunctionCallsStartedFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker,PipelineParams
from pipecat.workers.runner import WorkerRunner
from pipecat.processors.frame_processor import FrameProcessor,FrameDirection
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair,LLMUserAggregatorParams
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from .config import MODEL,OLLAMA,SYSTEM
from .services import SenseVoiceSTTService,MeloTTSService
from .transport import PocketPCMTransport
from .speech_policy import enforce,spoken_form
from .tool_client import execute

class ClosedFunctionSchema(FunctionSchema):
    def to_default_dict(self):
        value=super().to_default_dict()
        value['parameters']['additionalProperties']=False
        value['strict']=True
        return value

class State:
    def __init__(self,ws,ledger):
        self.ws=ws;self.ledger=ledger;self.closed=False;self.send_lock=asyncio.Lock()
        self.pending=None;self.active=None;self.text='';self.safe_text='';self.started=0
        self.epoch=0;self.audio_frames=0;self.first_audio=None;self.receipt=None;self.tool_failed=False;self.tool_calls=0;self.tool_waiting=False
    async def emit(self,event):
        if not self.closed and not self.ws.closed:
            async with self.send_lock:await self.ws.send_json(event)
    def reserve(self,rid,text):
        result=self.ledger.reserve(rid,'speech',{'scope':'voice-r2','text':text})
        if not result['duplicate']:
            if self.pending:self.ledger.finish(self.pending[0],'interrupted')
            self.pending=(rid,text)
        return result
    def cancel_active(self):
        if self.active:self.ledger.finish(self.active,'interrupted')
        self.active=None;self.safe_text='';self.receipt=None;self.tool_failed=False;self.tool_waiting=False
    def begin(self):
        if self.pending:
            self.cancel_active();self.active,self.text=self.pending;self.pending=None
            self.started=time.monotonic();self.first_audio=None;self.audio_frames=0;self.tool_calls=0
        self.safe_text=''

class Admission(FrameProcessor):
    def __init__(self,state):super().__init__();self.state=state
    async def process_frame(self,frame,direction):
        await super().process_frame(frame,direction)
        if isinstance(frame,TranscriptionFrame) and direction==FrameDirection.DOWNSTREAM:
            if not frame.text.strip():return
            rid=frame.metadata.get('request_id')
            if rid is None:
                rid=uuid.uuid4().hex;self.state.reserve(rid,frame.text)
            await self.state.emit({'type':'transcript_final','text':frame.text,'id':rid,'recognizer':'sensevoice'})
        await self.push_frame(frame,direction)

class AuthorityGuard(FrameProcessor):
    def __init__(self,state):super().__init__();self.state=state;self.buffer=''
    async def process_frame(self,frame,direction):
        await super().process_frame(frame,direction)
        if direction!=FrameDirection.DOWNSTREAM:await self.push_frame(frame,direction);return
        if isinstance(frame,InterruptionFrame):
            self.buffer='';self.state.cancel_active();await self.push_frame(frame,direction)
        elif isinstance(frame,LLMFullResponseStartFrame):
            self.state.begin();self.buffer='';self.state.tool_waiting=False
            if self.state.active:await self.state.emit({'type':'turn_started','id':self.state.active,'epoch':self.state.epoch})
            await self.push_frame(frame,direction)
        elif isinstance(frame,FunctionCallsStartedFrame):
            self.state.tool_waiting=True
            await self.push_frame(frame,direction)
        elif isinstance(frame,LLMTextFrame):
            self.buffer+=frame.text
            if len(self.buffer)>1600:raise ValueError('llm_response_limit')
        elif isinstance(frame,LLMFullResponseEndFrame):
            reply=self.buffer.strip();self.buffer=''
            if self.state.tool_waiting:
                self.state.safe_text=''
                await self.push_frame(frame,direction)
                return
            if self.state.tool_failed:reply='工具暂时不可用，结果尚未确认。'
            elif self.state.receipt:
                count=self.state.receipt['result']['active_call_count'];digit='零' if count==0 else '一'
                reply=f'电话音频端点检查通过，当前有{digit}个活动通话。实际远端听感尚未验收。'
            elif reply:
                d=enforce(self.state.text,reply);reply=d.text
                if d.reason:await self.state.emit({'type':'policy_guard','reason':d.reason})
            if any(x in reply for x in ('<think>','<tool_call>','<|im_')):reply='模型输出不符合语音要求，这次回复未执行任何操作。'
            if reply:
                self.state.safe_text=reply
                await self.push_frame(LLMTextFrame(spoken_form(reply)))
            await self.push_frame(frame,direction)
        else:await self.push_frame(frame,direction)

class ReceiptObserver(FrameProcessor):
    def __init__(self,state):super().__init__();self.state=state
    async def process_frame(self,frame,direction):
        await super().process_frame(frame,direction)
        if direction==FrameDirection.DOWNSTREAM and isinstance(frame,LLMFullResponseEndFrame):
            s=self.state
            if s.active and s.safe_text and s.audio_frames:
                s.ledger.finish(s.active,'done',{'audio_generated':True,'delivery':'frames_sent_not_human_confirmed','framework':'pipecat-1.12.0'})
                await s.emit({'type':'turn_done','id':s.active,'epoch':s.epoch,'text':s.safe_text,
                  'first_audio_seconds':s.first_audio-s.started if s.first_audio else None,'audio_frames':s.audio_frames})
                s.active=None
        if isinstance(frame,ErrorFrame):await self.state.emit({'type':'error','code':'pipecat_error','detail':str(frame.error)[:160]})
        await self.push_frame(frame,direction)

def build(state,models):
    transport=PocketPCMTransport(state)
    llm=OLLamaLLMService(base_url=OLLAMA,settings=OLLamaLLMService.Settings(model=MODEL,system_instruction=SYSTEM,temperature=0,max_tokens=96),max_retries=0)
    tool=ClosedFunctionSchema(name='telephone_status',description='固定只读检查Pocket4的音频端点与活动通话数量。没有参数，arguments必须为{}，不得添加endpoint、target等字段。不接听、不拨号、不发送短信。',properties={},required=[])
    context=LLMContext(tools=ToolsSchema(standard_tools=[tool]))
    user,assistant=LLMContextAggregatorPair(context,user_params=LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(params=VADParams(start_secs=.12,stop_secs=.5)),empty_user_turn=None))
    async def telephone_status(params):
        state.tool_calls+=1
        if state.tool_calls>1:
            state.tool_failed=True;await params.result_callback({'status':'failed','reason':'one_tool_per_turn'});return
        rid=uuid.uuid4().hex
        try:
            receipt,_=await execute(params.function_name,params.arguments,rid)
            state.receipt=receipt;await state.emit({'type':'tool_receipt','receipt':receipt})
            await params.result_callback(receipt)
        except asyncio.CancelledError:raise
        except Exception:
            state.tool_failed=True;await params.result_callback({'status':'failed','result':None})
    llm.register_function('telephone_status',telephone_status,cancel_on_interruption=True)
    pipeline=Pipeline([transport.input(),SenseVoiceSTTService(models),Admission(state),user,llm,
       AuthorityGuard(state),MeloTTSService(models),transport.output(),ReceiptObserver(state),assistant])
    worker=PipelineWorker(pipeline,params=PipelineParams(audio_in_sample_rate=16000,audio_out_sample_rate=16000),idle_timeout_secs=180)
    return transport,worker,WorkerRunner(handle_sigint=False),context
