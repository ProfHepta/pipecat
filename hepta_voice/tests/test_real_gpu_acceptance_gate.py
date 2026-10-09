"""Real GPU acceptance is gated; tests may never touch actual GPU/phone."""
import asyncio
import json
import socket

import pytest
from hepta_voice.ops import real_gpu_acceptance as gate


def test_forged_nonssh_unix_listener_rejected(tmp_path):
    path = tmp_path / "synthetic.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        listener.listen(1)
        with pytest.raises(gate.GateClosed, match="unix_listener_not_ssh"):
            gate.private_ssh_unix_listener(path)


def test_unrelated_business_unit_cannot_be_modified():
    with pytest.raises(ValueError, match="unrelated_service_not_owned"):
        gate.start_stop("heptatrader-execution.service", "stop")


@pytest.mark.asyncio
async def test_missing_connector_key_never_starts_voice_or_changes_gpu(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "REPORT", tmp_path / "receipt.json")
    monkeypatch.setattr(gate, "STATE", tmp_path)
    monkeypatch.setattr(gate, "probe_pocket4_engine", lambda: {"engine_ready": True})
    observed_starts = []

    def forbidden_start(*args, **kwargs):
        observed_starts.append((args, kwargs))
        raise AssertionError("should not start service with missing credential")

    monkeypatch.setattr(gate, "start_stop", forbidden_start)
    with pytest.raises(FileNotFoundError):
        await gate.main()
    assert not observed_starts
    receipt = json.loads(gate.REPORT.read_text())
    assert receipt["completed"] is False
    assert receipt["real_pocket4_gpu_verified"] is False
    assert receipt["synthetic_audio_first_frame_measured"] is False
    assert receipt["services_started_and_stopped_by_this_run"] == []
    assert receipt["telephone_dialed"] is False


@pytest.mark.parametrize('argv,allowed', [
    (['/usr/bin/ssh', '-N', '-L', '/tmp/synthetic.sock:127.0.0.1:18455', 'pocket4'], True),
    (['/usr/bin/ssh', '-N', '-L/tmp/synthetic.sock:127.0.0.1:18455', 'pocket4'], True),
    (['/usr/bin/ssh', '-N', '-o', 'LocalForward=/tmp/synthetic.sock:127.0.0.1:18455', 'pocket4'], True),
    (['/usr/bin/ssh', 'pocket4', 'echo', '/tmp/synthetic.sock:127.0.0.1:18455'], False),
    (['/usr/bin/ssh', '-L', '/tmp/synthetic.sock:127.0.0.1:18455', 'pocket4'], False),
    (['/usr/bin/ssh', '-N', '-L', '/tmp/synthetic.sock:0.0.0.0:18455', 'pocket4'], False),
    (['/usr/bin/ssh', '-N', '-L', '/tmp/synthetic.sock:127.0.0.1:18456', 'pocket4'], False),
    (['/usr/bin/ssh', '-N', '-L', '/tmp/synthetic.sock:127.0.0.1:18455', 'other-host'], False),
])
def test_forward_must_be_explicit_ssh_local_forward(argv, allowed):
    assert gate.pinned_ssh_forward(argv, __import__('pathlib').Path('/tmp/synthetic.sock')) is allowed


def test_other_systemctl_verbs_forbidden():
    with pytest.raises(ValueError, match='unsupported_service_action'):
        gate.start_stop('hepta-pipecat.service', 'enable')


@pytest.mark.asyncio
async def test_cleanup_failure_never_records_completed_gpu_qualification(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, 'REPORT', tmp_path / 'failure.json')
    monkeypatch.setattr(gate, 'STATE', tmp_path)
    monkeypatch.setattr(gate, 'probe_pocket4_engine', lambda: {'pid':123,'start_ticks':'a','boot_id':'b'})
    monkeypatch.setattr(gate, 'validate_local_endpoint_files', lambda *_: None)
    monkeypatch.setattr(gate, 'private_ssh_unix_listener', lambda *_: {'authenticated_forward':True})

    async def good_model(): return {'authenticated':True}
    async def good_health(): return {'ready':True}
    monkeypatch.setattr(gate, 'model_probe', good_model)
    monkeypatch.setattr(gate, 'wait_voice_ready', good_health)
    monkeypatch.setattr(gate, 'active', lambda _: False)
    def owned_stop(unit, action):
        if action == 'stop': raise OSError('synthetic_cleanup_failure')
    monkeypatch.setattr(gate, 'start_stop', owned_stop)
    fake_cross = {
        'sha256_both_directions_match':True,
        'cross_host_first_audio':{'clock_domains_kept_separate':True},
        'endpoint_receipt':{'telephone_used':False},
    }
    monkeypatch.setattr(gate, 'controlled_test', lambda script, *_: fake_cross if script.name == 'cross_host.py' else {'completed':True})
    with pytest.raises(gate.GateClosed, match='failed_to_restore_owned_services'):
        await gate.main()
    data=json.loads(gate.REPORT.read_text())
    assert data['completed'] is False
    assert data['real_pocket4_gpu_verified'] is False
    assert data['blocker']=='failed_to_restore_owned_services'
    assert set(data['failed_to_restore'])=={'hepta-pipecat.service','hepta-pipecat-tools.service'}
