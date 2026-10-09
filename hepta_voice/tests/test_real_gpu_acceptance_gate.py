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
