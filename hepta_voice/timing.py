"""Passive timing records. Never subtract monotonic clocks from different hosts.
Only observed stages are emitted; missing stages do not become zero-duration passes.
"""
from dataclasses import dataclass,field
from pathlib import Path
import time
try:
    CLOCK_ID='voice-monotonic:'+Path('/proc/sys/kernel/random/boot_id').read_text().strip()
except OSError:
    CLOCK_ID='voice-process-monotonic'
STAGES=frozenset({'input_end_ingress','asr_start','asr_final','llm_start','llm_first_token','reply_validated','tts_first_ready','audio_first_sent'})
PAIRS={
    'ingress_end_to_final_transcript':('input_end_ingress','asr_final'),
    'recognition_compute':('asr_start','asr_final'),
    'transcript_to_llm_request':('asr_final','llm_start'),
    'llm_time_to_first_token':('llm_start','llm_first_token'),
    'llm_first_token_to_validated_reply':('llm_first_token','reply_validated'),
    'validation_to_first_synthesis_ready':('reply_validated','tts_first_ready'),
    'synthesis_ready_to_first_frame_sent':('tts_first_ready','audio_first_sent'),
    'ingress_end_to_first_frame_sent':('input_end_ingress','audio_first_sent'),
}
@dataclass
class StageTimeline:
    request_id:str
    clock_id:str=CLOCK_ID
    stages_ns:dict[str,int]=field(default_factory=dict)
    def mark(self,stage:str,timestamp_ns:int|None=None):
        if stage not in STAGES:raise ValueError('unknown_timing_stage')
        value=time.monotonic_ns() if timestamp_ns is None else timestamp_ns
        if type(value) is not int or value<0:raise ValueError('invalid_timing_value')
        self.stages_ns.setdefault(stage,value)
    def snapshot(self):
        durations={};invalid=[]
        for name,(a,b) in PAIRS.items():
            if a in self.stages_ns and b in self.stages_ns:
                delta=self.stages_ns[b]-self.stages_ns[a]
                if delta<0:invalid.append(name)
                else:durations[name]=delta/1e6
        return {'request_id':self.request_id,'clock_id':self.clock_id,'stages_monotonic_ns':dict(self.stages_ns),'durations_ms':durations,'invalid_order':invalid,'scope':'voice_host_only_not_remote_audibility'}

def endpoint_latency_ms(speech_end_ns:int,first_audio_ns:int,*,source_clock:str,sink_clock:str):
    if source_clock!=sink_clock:raise ValueError('cross_host_clock_subtraction_forbidden')
    if first_audio_ns<speech_end_ns:raise ValueError('reply_preceded_input_end')
    return (first_audio_ns-speech_end_ns)/1e6
