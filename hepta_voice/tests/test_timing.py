import pytest
from hepta_voice.timing import StageTimeline,endpoint_latency_ms

def test_measured_stages_only_not_missing_zeroes():
    t=StageTimeline('trace_0001');t.mark('asr_start',1000000);t.mark('asr_final',4000000)
    s=t.snapshot();assert s['durations_ms']=={'recognition_compute':3.0}
    assert 'ingress_end_to_first_frame_sent' not in s['durations_ms']

def test_first_event_is_preserved_across_multiple_tts_sentences():
    t=StageTimeline('trace_0002');t.mark('tts_first_ready',100);t.mark('tts_first_ready',200)
    assert t.stages_ns['tts_first_ready']==100

def test_clocks_cannot_be_silently_mixed():
    with pytest.raises(ValueError):endpoint_latency_ms(100,200,source_clock='pocket4',sink_clock='qian-qi')
    assert endpoint_latency_ms(1000000,5000000,source_clock='pocket4',sink_clock='pocket4')==4

def test_invalid_order_is_a_failure_not_clamped():
    t=StageTimeline('trace_0003');t.mark('asr_start',300);t.mark('asr_final',200)
    s=t.snapshot();assert s['invalid_order']==['recognition_compute'];assert not s['durations_ms']

def test_trace_metadata_contains_no_audio_or_transcript():
    t=StageTimeline('trace_0004');t.mark('llm_start',10)
    assert set(t.snapshot())=={'request_id','clock_id','stages_monotonic_ns','durations_ms','invalid_order','scope'}
