"""Authorized REAL Pocket4 GPU/Pipecat synthetic-audio acceptance gate.

This script NEVER transfers credentials, provisions forwarding, changes Pocket4,
dials a phone, opens a microphone, modifies a system service, or substitutes a
synthetic LLM. It can only run once the local authenticated SSH Unix socket and
key have been provisioned through an authorized channel.
"""
import asyncio
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

from hepta_voice.config import DATA, STATE
from hepta_voice.endpoint_attestation import validate_local_endpoint_files
from hepta_voice.llama_client import verify_engine_properties
from hepta_voice.deploy.attest_pocket_engine import probe_pocket4_engine

REPORT = DATA / "evidence" / "pocket4-real-gpu-voice-acceptance-20261009.json"
CROSS_RECEIPT = DATA / "evidence" / "pipecat-cross-host.json"
CONTROL_RECEIPT = DATA / "evidence" / "pipecat-acceptance.json"
BASE = Path(__file__).resolve().parents[2]
EXE = DATA / "venv" / "bin" / "python"


class GateClosed(RuntimeError):
    pass


def private_ssh_unix_listener(path: Path) -> dict:
    # SO_PEERCRED certifies who actually accepted the Unix connection, rather
    # than trusting a socket filename or an old systemd success message.
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(3)
        sock.connect(str(path))
        pid, uid, gid = struct.unpack("3i", sock.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
    if uid != os.getuid():
        raise GateClosed("ssh_relay_process_owner_mismatch")
    proc = Path("/proc") / str(pid)
    binary = os.readlink(proc / "exe")
    if Path(binary).name != "ssh":
        raise GateClosed("unix_listener_not_ssh")
    args = [x.decode(errors="replace") for x in (proc / "cmdline").read_bytes().split(b"\\0") if x]
    expected = str(path) + ":127.0.0.1:18455"
    # Require forwarding to the pre-existing Pocket4 loopback endpoint; do not
    # accept dynamically provided URL or a listener bound to public IP.
    if "pocket4" not in args or not any(
        arg == expected or arg.endswith("=" + expected) for arg in args
    ):
        raise GateClosed("ssh_forwarding_target_not_pinned")
    return {"pid": pid, "owner_uid": uid, "authenticated_forward": True}


def active(unit: str) -> bool:
    env = {**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
    result = subprocess.run(["systemctl", "--user", "is-active", unit],
                            env=env, capture_output=True, text=True, timeout=10)
    return result.returncode == 0 and result.stdout.strip() == "active"


def start_stop(unit: str, verb: str):
    if unit not in ("hepta-pipecat.service", "hepta-pipecat-tools.service"):
        raise ValueError("unrelated_service_not_owned_by_voice_acceptance")
    env = {**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
    subprocess.run(["systemctl", "--user", verb, unit],
                   env=env, capture_output=True, timeout=25, check=True)


async def model_probe() -> dict:
    secret = (STATE / "llama.key").read_text().strip()
    async with aiohttp.ClientSession(
        connector=aiohttp.UnixConnector(path=str(STATE / "llama.sock")),
        headers={"Authorization": "Bearer " + secret},
        timeout=aiohttp.ClientTimeout(total=10),
        trust_env=False,
    ) as client:
        async with client.get("http://localhost/health") as response:
            response.raise_for_status()
            assert (await response.json()).get("status") == "ok", "engine_unhealthy"
        async with client.get("http://localhost/props") as response:
            response.raise_for_status()
            props = await response.json()
            verify_engine_properties(props)
    return {
        "authenticated": True,
        "model_alias": props["model_alias"],
        "quantization": props["model_ftype"],
        "slots": props["total_slots"],
        "context": props["default_generation_settings"]["n_ctx"],
    }


async def wait_voice_ready(timeout=50) -> dict:
    token = (STATE / "access.token").read_text().strip()
    async with aiohttp.ClientSession(
        connector=aiohttp.UnixConnector(path=str(STATE / "agent.sock")),
        headers={"Authorization": "Bearer " + token},
        timeout=aiohttp.ClientTimeout(total=5), trust_env=False,
    ) as client:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                async with client.get("http://localhost/health") as response:
                    health = await response.json()
                if health.get("ready"):
                    if health.get("llm_engine") != "llama.cpp" or health.get("llm_gpu_host") != "pocket4":
                        raise GateClosed("wrong_voice_model_adapter")
                    if health.get("production_ready") is not False or health.get("phone_authority") is not False:
                        raise GateClosed("voice_production_flags_not_isolated")
                    if health.get("active_session") is not False:
                        raise GateClosed("another_voice_session_active")
                    async with client.get("http://localhost/network-proof") as response:
                        net = await response.json()
                    if net.get("ipv4") != 101 or net.get("ipv6") != 101:
                        raise GateClosed("voice_container_network_not_isolated")
                    return {"ready": True, "engine": "llama.cpp", "remote_host": "pocket4",
                            "production_ready": False, "network_none": True}
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(.5)
    raise GateClosed("voice_did_not_become_ready")


def controlled_test(script, outfile, timeout) -> dict:
    before = outfile.stat().st_mtime_ns if outfile.exists() else None
    result = subprocess.run([str(EXE), '-m', 'hepta_voice.ops.' + script.stem], cwd=str(BASE),
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise GateClosed("real_gpu_test_failed:" + script.name)
    if not outfile.exists() or outfile.stat().st_mtime_ns == before:
        raise GateClosed("missing_new_real_gpu_evidence:" + script.name)
    return json.loads(outfile.read_text())


async def main():
    os.umask(0o077)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    result = {"scope": "real_pocket4_gpu_inference_with_synthetic_pcm_only",
              "real_pocket4_gpu_verified": False,
              "synthetic_audio_first_frame_measured": False,
              "human_remote_audibility_verified": False,
              "telephone_dialed": False, "auto_answer_enabled": False}
    started = []
    try:
        # No local service is started until all read-only prerequisites succeed.
        remote_before = probe_pocket4_engine()
        result["pocket4_before"] = remote_before
        validate_local_endpoint_files(STATE)
        result["ssh_relay"] = private_ssh_unix_listener(STATE / "llama.sock")
        result["model_api"] = await model_probe()
        if active("hepta-pipecat.service"):
            raise GateClosed("existing_voice_owner_must_be_drained_first")
        # The tool broker is read-only, but must be stopped only if this run
        # started it. No other user service is changed.
        for unit in ("hepta-pipecat-tools.service", "hepta-pipecat.service"):
            if not active(unit):
                start_stop(unit, "start")
                started.append(unit)
        result["voice_health"] = await wait_voice_ready()
        cross = controlled_test(BASE / "hepta_voice/ops/cross_host.py", CROSS_RECEIPT, 180)
        assert cross["sha256_both_directions_match"] is True
        assert cross["cross_host_first_audio"]["clock_domains_kept_separate"]
        assert cross["endpoint_receipt"]["telephone_used"] is False
        result["cross_host_synthetic"] = cross
        result["synthetic_audio_first_frame_measured"] = True
        # Control regression includes interrupt, duplicate, read-only tool,
        # timeout-unknown policy. It may fail on a new real-model behavior:
        # preserve that failure rather than weakening its assertions.
        controls = controlled_test(BASE / "hepta_voice/ops/acceptance.py",
                                   CONTROL_RECEIPT, 420)
        if controls.get("completed") is not True:
            raise GateClosed("real_gpu_control_acceptance_not_complete")
        result["control_suite"] = controls
        remote_after = probe_pocket4_engine()
        if any(remote_before[k] != remote_after[k] for k in ("pid", "boot_id", "start_ticks")):
            raise GateClosed("gpu_engine_restarted_during_voice_acceptance")
        result["pocket4_after"] = remote_after
        result["real_pocket4_gpu_verified"] = True
        result["completed"] = True
    except Exception as exc:
        result["completed"] = False
        result["blocker"] = type(exc).__name__ + ":" + str(exc)[:160]
        raise
    finally:
        for unit in reversed(started):
            try:
                start_stop(unit, "stop")
            except Exception:
                result.setdefault("failed_to_restore", []).append(unit)
        result["services_started_and_stopped_by_this_run"] = started
        result["persisted_at_unix"] = time.time()
        REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({
            "completed": result.get("completed", False),
            "blocker": result.get("blocker"),
            "gpu_verified": result.get("real_pocket4_gpu_verified"),
            "synthetic_first_audio_measured": result.get("synthetic_audio_first_frame_measured"),
            "telephone_dialed": False,
        }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
