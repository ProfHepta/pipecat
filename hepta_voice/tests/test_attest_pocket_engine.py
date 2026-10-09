"""Read-only engine attestation rejects stale PID, changed weight or backend."""
import copy
import pytest
from hepta_voice.deploy.attest_pocket_engine import (
    ENGINE_SHA, MODEL_SHA, BINARY_SHA, verify_engine_attestation,
)

GOOD = {
    "identity": True, "flags": True, "commit": ENGINE_SHA,
    "model_sha256": MODEL_SHA, "binary_sha256": BINARY_SHA,
    "backend": "Vulkan", "flash_attention": True,
    "engine_ready": True, "model_alias": "hepta-qwen3-4b",
    "model_ftype": "Q4_K - Medium", "total_slots": 1,
    "n_ctx": 4096, "only_loopback": True,
    "read_only_no_phone": True, "gpu_render_fds": 2, "pid": 12345,
}

def test_actual_contract_accepts_valid_synthetic_attestation():
    assert verify_engine_attestation(GOOD) is True

@pytest.mark.parametrize("override", [
    {"identity": False}, {"flags": False}, {"commit": "other"},
    {"model_sha256": "bad"}, {"binary_sha256": "bad"},
    {"backend": "HIP"}, {"flash_attention": False},
    {"engine_ready": False}, {"model_alias": "wrong"},
    {"model_ftype": "Q8_0"}, {"total_slots": 2},
    {"n_ctx": 8192}, {"only_loopback": False},
    {"read_only_no_phone": False}, {"gpu_render_fds": 0},
    {"gpu_render_fds": False}, {"pid": 0},
])
def test_invalid_identity_never_passes(override):
    value = {**GOOD, **override}
    with pytest.raises(ValueError):
        verify_engine_attestation(value)
