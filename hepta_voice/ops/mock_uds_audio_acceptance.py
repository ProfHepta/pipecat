"""Run an isolated full Pipecat audio pass against a simulated local LLM.

This is deliberately NOT a GPU benchmark or telephone acceptance:
the model endpoint is an in-process, authenticated AF_UNIX fixture. ASR, VAD,
TTS, Pipecat and PCM transport are real, in a network-none sandbox.
"""
import asyncio
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
DATA = Path.home() / ".local/share/hepta-pipecat"
IMAGE = "sha256:62d572b92f9f32d3427b6d220ad1f9dca9c7b6ffad37d295425037dbff78abaf"
CONTAINER = "hepta-pipecat-mock-audio"
REPORT = DATA / "evidence/mock-uds-audio-20261009.json"


async def main():
    # Namespaced credentials. Never touch state/llama.key, llama.sock or any live
    # GPU/phone engine. The fake model speaks on a private Unix socket only.
    tmp = Path(tempfile.mkdtemp(prefix="synthetic-audio-", dir=DATA / "state"))
    state = tmp / "state"
    state.mkdir(mode=0o700)
    (tmp / "models").symlink_to(DATA / "models", target_is_directory=True)
    (tmp / "fixtures").symlink_to(DATA / "fixtures", target_is_directory=True)
    (tmp / "evidence").mkdir(mode=0o700)
    fake_key = "synthetic-test-only-" + secrets.token_hex(32)
    api_key = secrets.token_hex(32)
    (state / "llama.key").write_text(fake_key)
    (state / "access.token").write_text(api_key)
    for name in ("llama.key", "access.token"):
        (state / name).chmod(0o600)
    script_log = tmp / "sandbox-output.log"
    collected = {"scope": "real ASR/VAD/TTS + FAKE LLM, no GPU or telephone",
                 "fake_secret_only": True, "zero_external_llm_calls": True,
                 "calls": 0, "completed": False}
    fake_runner = None
    proc = None

    async def health(request):
        if request.headers.get("Authorization") != "Bearer " + fake_key:
            raise web.HTTPUnauthorized()
        return web.json_response({"status": "ok"})

    async def props(request):
        if request.headers.get("Authorization") != "Bearer " + fake_key:
            raise web.HTTPUnauthorized()
        return web.json_response({
            "model_alias": "hepta-qwen3-4b", "model_ftype": "Q4_K - Medium",
            "total_slots": 1, "default_generation_settings": {"n_ctx": 4096},
        })

    async def chat(request):
        if request.headers.get("Authorization") != "Bearer " + fake_key:
            raise web.HTTPUnauthorized()
        payload = await request.json()
        assert payload["model"] == "hepta-qwen3-4b", payload.get("model")
        collected["calls"] += 1
        response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for part, finish in [("三加五等于八。", None), ("", "stop")]:
            packet = {
                "id": "synthetic-chat-id", "object": "chat.completion.chunk",
                "created": 0, "model": "hepta-qwen3-4b",
                "choices": [{"index": 0, "delta": {"content": part}, "finish_reason": finish}],
            }
            await response.write(("data: " + json.dumps(packet, ensure_ascii=False) + "\n\n").encode())
            await asyncio.sleep(0.01)
        await response.write(b"data: [DONE]\n\n")
        return response

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/props", props)
    app.router.add_post("/v1/chat/completions", chat)
    fake_runner = web.AppRunner(app, access_log=None)
    await fake_runner.setup()
    await web.UnixSite(fake_runner, str(state / "llama.sock")).start()
    (state / "llama.sock").chmod(0o600)

    cmd = [
        "docker", "run", "--rm", "--name", CONTAINER, "--network", "none",
        "--user", f"{os.getuid()}:{os.getgid()}", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--cpus", "4",
        "--memory", "6g", "--memory-swap", "6g", "--pids-limit", "192",
        "--tmpfs", "/tmp:rw,nosuid,size=256m",
        "--mount", f"type=bind,src={ROOT},dst={ROOT},readonly",
        "--mount", f"type=bind,src={DATA},dst={DATA},readonly",
        "--mount", f"type=bind,src={state},dst={state}",
        "--workdir", str(ROOT),
        "--env", "HOME=/tmp",
        "--env", f"HEPTA_VOICE_DATA={tmp}",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "OPENBLAS_NUM_THREADS=1",
        "--env", "OMP_NUM_THREADS=2",
        "--env", "NUMBA_CACHE_DIR=/tmp/numba",
        "--env", "CUDA_VISIBLE_DEVICES=-1",
        IMAGE, f"{DATA}/venv/bin/python", "-m", "hepta_voice.server",
    ]
    try:
        with script_log.open("w") as output:
            proc = subprocess.Popen(cmd, stdout=output, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        headers = {"Authorization": "Bearer " + api_key}
        async with aiohttp.ClientSession(
            connector=aiohttp.UnixConnector(path=str(state / "agent.sock")),
            headers=headers, timeout=aiohttp.ClientTimeout(total=120),
            trust_env=False,
        ) as client:
            for _ in range(120):
                if proc.poll() is not None:
                    raise RuntimeError("synthetic_sandbox_exited_before_ready")
                try:
                    async with client.get("http://localhost/health") as r:
                        j = await r.json()
                    if j.get("ready"):
                        assert j["framework"] == "pipecat"
                        break
                except (aiohttp.ClientError, OSError):
                    pass
                await asyncio.sleep(0.25)
            else:
                raise RuntimeError("synthetic_sandbox_not_ready")
            collected["engine"] = "authenticated_fake_uds"
            async with client.ws_connect("http://localhost/session") as ws:
                intro = await ws.receive_json(timeout=15)
                assert intro["type"] == "ready"
                await ws.send_json({"type": "format", "sample_rate": 8000})
                with wave.open(str(DATA / "fixtures/input-8k.wav"), "rb") as wav:
                    assert wav.getframerate() == 8000 and wav.getsampwidth() == 2
                    pcm = wav.readframes(wav.getnframes())
                recorded_end_ns = None

                async def send_input():
                    nonlocal recorded_end_ns
                    for i in range(0, len(pcm), 320):
                        await ws.send_bytes(pcm[i:i + 320])
                        await asyncio.sleep(0.02)
                    recorded_end_ns = time.monotonic_ns()
                    await ws.send_json({"type": "input_end_marker"})
                    for _ in range(155):
                        await ws.send_bytes(bytes(320))
                        await asyncio.sleep(0.02)
                uploader = asyncio.create_task(send_input())
                first_received_ns = None
                audio_frames = 0
                all_audio_bytes = 0
                final_event = None
                try:
                    for _ in range(2000):
                        message = await ws.receive_json(timeout=40)
                        kind = message.get("type")
                        if kind == "audio":
                            if first_received_ns is None:
                                first_received_ns = time.monotonic_ns()
                            audio_frames += 1
                            all_audio_bytes += len(message.get("pcm", ""))
                        elif kind == "turn_done":
                            final_event = message
                            break
                        elif kind == "error":
                            raise RuntimeError("synthetic_pipeline_error:" + str(message))
                    else:
                        raise RuntimeError("synthetic_turn_not_completed")
                    await uploader
                finally:
                    if not uploader.done():
                        uploader.cancel()
                if not final_event or not audio_frames or recorded_end_ns is None:
                    raise RuntimeError("missing_real_audio_or_endpoint_timestamp")
                timeline = final_event.get("timeline") or {}
                marks = timeline.get("stages_monotonic_ns", {})
                required = {"input_end_ingress", "asr_start", "asr_final",
                            "llm_start", "llm_first_token", "reply_validated",
                            "tts_first_ready", "audio_first_sent"}
                absent = sorted(required - set(marks))
                assert not absent, "missing_timestamps:" + ",".join(absent)
                assert not timeline.get("invalid_order"), "out_of_order_timing"
                assert final_event["text"] == "三加五等于八。"
                collected.update({
                    "completed": True, "text": final_event["text"],
                    "audio_frames": audio_frames, "synthetic_pcm_characters": all_audio_bytes,
                    "same_host_input_end_to_first_audio_ms":
                        round((first_received_ns - recorded_end_ns) / 1e6, 2),
                    "pipeline_timing": timeline,
                    "engine_request_count": collected["calls"],
                    "gpu_evaluated": False, "real_telephone": False,
                    "human_listened": False,
                })
                await ws.send_json({"type": "end"})
        # Independently test actual Pocket4 synthetic PCM over pinned-host-key
        # SSH stdio. The LLM is still the isolated FAKE Unix socket fixture;
        # this cannot qualify the live GPU or a real telephone call.
        await asyncio.sleep(0.8)
        env = {**os.environ, "HEPTA_VOICE_DATA": str(tmp)}
        cross_proc = await asyncio.create_subprocess_exec(
            str(DATA / "venv/bin/python"), "-m", "hepta_voice.ops.cross_host",
            cwd=str(ROOT), env=env, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            cross_out, cross_err = await asyncio.wait_for(cross_proc.communicate(), 150)
        except asyncio.TimeoutError:
            cross_proc.kill()
            await cross_proc.wait()
            raise RuntimeError("mock_cross_host_test_deadline")
        if cross_proc.returncode != 0:
            raise RuntimeError("mock_cross_host_failure:" + cross_err.decode(errors="replace")[-250:])
        cross = json.loads((tmp / "evidence/pipecat-cross-host.json").read_text())
        proof = cross["cross_host_first_audio"]
        assert cross["sha256_both_directions_match"] and proof["clock_domains_kept_separate"]
        assert not proof["end_to_end_gpu_verified"] and not proof["telephone_remote_audibility_verified"]
        collected["cross_host_completed"] = True
        collected["mock_cross_host"] = {
            "remote": cross["remote"],
            "synthetic_endpoint_first_audio_ms": proof["synthetic_endpoint_first_audio_ms"],
            "voice_host_internal_first_audio_ms": proof["voice_host_internal_first_audio_ms"],
            "audio_frames": cross["endpoint_receipt"]["audio_frames"],
            "input_output_hashes_verified": cross["sha256_both_directions_match"],
            "stale_frames": cross["endpoint_receipt"]["stale_frames"],
            "actual_gpu": False, "actual_telephone": False,
        }
        print(json.dumps({
            "completed": True, "audio_frames": audio_frames,
            "first_audio_ms": collected["same_host_input_end_to_first_audio_ms"],
            "durations_ms": timeline["durations_ms"],
            "mock_engine": True,
        }, ensure_ascii=False), flush=True)
    except Exception as e:
        collected["completed"] = False
        collected["cross_host_completed"] = False
        collected["failure"] = {"type": type(e).__name__, "message": str(e)[:240]}
        try:
            collected["sandbox_log_tail"] = script_log.read_text()[-2400:]
        except OSError:
            pass
        raise
    finally:
        REPORT.write_text(json.dumps(collected, ensure_ascii=False, indent=2))
        if proc and proc.poll() is None:
            subprocess.run(["docker", "stop", "-t", "3", CONTAINER],
                           capture_output=True, timeout=10)
        if proc:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if fake_runner:
            await fake_runner.cleanup()
        shutil.rmtree(tmp)


if __name__ == "__main__":
    asyncio.run(main())
