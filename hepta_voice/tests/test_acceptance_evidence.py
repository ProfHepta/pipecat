"""Synthetic receipt validation: stages, bytes, clock domains, no phone claim."""
import copy
import pytest
from hepta_voice.acceptance_evidence import verify_synthetic_endpoint_receipt

STAGES = ['input_end_ingress','asr_start','asr_final','llm_start',
          'llm_first_token','reply_validated','tts_first_ready','audio_first_sent']


def baseline():
    timeline = {'clock_id':'voice-monotonic:synthetic-host',
                'invalid_order':[],
                'stages_monotonic_ns':{name:1000+i*1000 for i,name in enumerate(STAGES)}}
    host={'text':'三加五等于八。','timeline':timeline}
    remote={'type':'endpoint_receipt','telephone_used':False,'human_listened':False,
            'input_sha256':'fixture-sha','output_pcm_sha256':'pcm-sha',
            'audio_frames':63,'stale_frames':0,'voice_host_timeline':timeline,
            'endpoint_clock_id':'pocket-monotonic:synthetic-pocket',
            'source_last_active_frame_sent_ns':1_000_000_000,
            'sink_first_frame_received_ns':1_500_000_000,
            'speech_end_to_first_received_audio_seconds':0.5,
            'response_text':'三加五等于八。'}
    return host,remote


def verify(host,remote):
    return verify_synthetic_endpoint_receipt(voice_host=host,remote=remote,
        pcm_digest='pcm-sha',pcm_frames=63,source_wav_digest='fixture-sha')


def test_both_local_clock_domains_are_reported_separately():
    h,r=baseline();result=verify(h,r)
    assert result['synthetic_endpoint_first_audio_ms']==500
    assert result['voice_host_internal_first_audio_ms']==0.007
    assert result['clock_domains_kept_separate']
    assert not result['end_to_end_gpu_verified']
    assert not result['telephone_remote_audibility_verified']


def test_voice_stage_not_invented_when_missing():
    h,r=baseline();del r['voice_host_timeline']['stages_monotonic_ns']['llm_first_token']
    with pytest.raises(ValueError,match='missing_voice_stages'):verify(h,r)


def test_invalid_stage_order_fails():
    h,r=baseline();r['voice_host_timeline']['stages_monotonic_ns']['tts_first_ready']=1
    with pytest.raises(ValueError,match='invalid_voice_host_stage_order'):verify(h,r)


def test_different_device_timestamp_domain_fails():
    h,r=baseline();r['endpoint_clock_id']='voice-monotonic:synthetic-host'
    with pytest.raises(ValueError,match='missing_endpoint_clock_identity'):verify(h,r)


def test_wrong_output_digest_fails():
    h,r=baseline();r['output_pcm_sha256']='other-digest'
    with pytest.raises(ValueError,match='actual_audio_bytes_or_frame_count_mismatch'):verify(h,r)


def test_stale_frames_do_not_pass():
    h,r=baseline();r['stale_frames']=1
    with pytest.raises(ValueError,match='no_audio_or_stale_audio'):verify(h,r)


def test_remote_audio_duration_must_agree_with_its_own_clock():
    h,r=baseline();r['speech_end_to_first_received_audio_seconds']=0.03
    with pytest.raises(ValueError,match='reported_endpoint_duration_conflict'):verify(h,r)


def test_no_telephone_or_human_qualification_in_synthetic_receipt():
    h,r=baseline();r['telephone_used']=True
    with pytest.raises(ValueError,match='unexpected_telephone_or_listening_claim'):verify(h,r)
