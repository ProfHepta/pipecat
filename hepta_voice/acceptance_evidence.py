"""Strict synthetic audio receipts with separate clock domains.

This does not authenticate the real GPU process or certify telephone audibility.
Those independent gates must be checked against live host-bound evidence.
"""
from .timing import STAGES, endpoint_latency_ms


def verify_synthetic_endpoint_receipt(*, remote: dict, voice_host: dict,
                                      pcm_digest: str, pcm_frames: int,
                                      source_wav_digest: str) -> dict:
    if not remote or remote.get('type') != 'endpoint_receipt':
        raise ValueError('missing_real_remote_endpoint_receipt')
    if remote.get('telephone_used') is not False or remote.get('human_listened') is not False:
        raise ValueError('unexpected_telephone_or_listening_claim')
    if remote.get('input_sha256') != source_wav_digest:
        raise ValueError('source_fixture_identity_mismatch')
    if remote.get('output_pcm_sha256') != pcm_digest or remote.get('audio_frames') != pcm_frames:
        raise ValueError('actual_audio_bytes_or_frame_count_mismatch')
    if type(pcm_frames) is not int or pcm_frames <= 0 or remote.get('stale_frames') != 0:
        raise ValueError('no_audio_or_stale_audio')
    timeline = remote.get('voice_host_timeline')
    if not timeline or not isinstance(timeline, dict):
        raise ValueError('missing_voice_host_timeline')
    if timeline != voice_host.get('timeline'):
        raise ValueError('timeline_receipt_identity_mismatch')
    if not isinstance(timeline.get('clock_id'), str) or not timeline['clock_id'].startswith('voice-monotonic:'):
        raise ValueError('missing_voice_host_clock_identity')
    stages = timeline.get('stages_monotonic_ns', {})
    missing = STAGES.difference(stages)
    if missing:
        raise ValueError('missing_voice_stages:' + ','.join(sorted(missing)))
    if timeline.get('invalid_order'):
        raise ValueError('invalid_voice_host_stage_order')
    if len({type(stages[name]) for name in STAGES}) != 1 or any(type(stages[name]) is not int for name in STAGES):
        raise ValueError('invalid_voice_host_stage_type')
    expected_order = ['input_end_ingress', 'asr_start', 'asr_final', 'llm_start',
                      'llm_first_token', 'reply_validated', 'tts_first_ready', 'audio_first_sent']
    if any(stages[b] < stages[a] for a, b in zip(expected_order, expected_order[1:])):
        raise ValueError('invalid_voice_host_stage_order')
    clock = remote.get('endpoint_clock_id')
    if not isinstance(clock, str) or not clock.startswith('pocket-monotonic:'):
        raise ValueError('missing_endpoint_clock_identity')
    elapsed = endpoint_latency_ms(remote['source_last_active_frame_sent_ns'],
                                  remote['sink_first_frame_received_ns'],
                                  source_clock=clock, sink_clock=clock)
    measured = remote.get('speech_end_to_first_received_audio_seconds')
    if type(measured) not in (int, float) or abs(elapsed / 1000 - measured) > 0.1:
        raise ValueError('reported_endpoint_duration_conflict')
    if voice_host.get('text') != remote.get('response_text'):
        raise ValueError('voice_response_identity_mismatch')
    return {
        'synthetic_endpoint_first_audio_ms': round(elapsed, 3),
        'voice_host_internal_first_audio_ms': round(
            (stages['audio_first_sent'] - stages['input_end_ingress']) / 1e6, 3),
        'clock_domains_kept_separate': True,
        'end_to_end_gpu_verified': False,
        'telephone_remote_audibility_verified': False,
    }
