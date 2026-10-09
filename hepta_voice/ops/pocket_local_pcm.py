"""Real Pocket4-local GPU/Pipecat PCM roundtrip. No call control or microphone.

The client, ASR, LLM and synthesized PCM all run on Pocket4. Its timings are
direct same-host monotonic durations, but do not claim human phone audibility.
"""
import asyncio
import base64
import hashlib
import io
import json
import math
import os
import struct
import time
import wave
from pathlib import Path

import aiohttp

from hepta_voice.config import DATA
from hepta_voice.timing import STAGES

OUT = DATA / "evidence/pocket-local-real-gpu-pcm.json"


def samples():
    raw = (DATA / "fixtures/input-8k.wav").read_bytes()
    with wave.open(io.BytesIO(raw), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (8000, 1, 2)
        data = w.readframes(w.getnframes())
    chunks = [data[i:i + 320] for i in range(0, len(data), 320)]
    voiced = [index for index, part in enumerate(chunks)
              if part and (sum(v * v for v in struct.unpack("<" + "h" * (len(part) // 2), part))
                           / len(part) * 2) ** .5 > 500]
    # The exact speech endpoint definition is shared with the synthetic fixture.
    assert voiced, "no_speech_detected"
    return raw, chunks, max(voiced)


async def main():
    os.umask(0o077)
    OUT.parent.mkdir(exist_ok=True, parents=True)
    result = {"scope": "real_local_Pocket4_llama_CPP_GPU_with_synthetic_audio",
              "production_ready": False, "telephone_used": False,
              "human_listened": False, "completed": False}
    try:
        original, chunks, speech_index = samples()
        token = (DATA / "state/access.token").read_text().strip()
        async with aiohttp.ClientSession(
                connector=aiohttp.UnixConnector(path=str(DATA / "state/agent.sock")),
                headers={"Authorization": "Bearer " + token},
                timeout=aiohttp.ClientTimeout(total=120), trust_env=False) as client:
            async with client.get("http://localhost/health") as response:
                info = await response.json()
                assert info["ready"] and info["llm_engine"] == "llama.cpp"
                assert info["llm_gpu_host"] == "pocket4"
                assert not info["production_ready"] and not info["phone_authority"]
            async with client.ws_connect("http://localhost/session") as ws:
                ready = await ws.receive_json(timeout=15)
                assert ready["type"] == "ready"
                await ws.send_json({"type": "format", "sample_rate": 8000})
                last_voiced_sent = None
                first_pcm = None
                frames = []
                transcript = None
                last_epoch = None

                async def send_audio():
                    nonlocal last_voiced_sent
                    for index, chunk in enumerate(chunks):
                        await ws.send_bytes(chunk)
                        if index == speech_index:
                            last_voiced_sent = time.monotonic_ns()
                            await ws.send_json({"type": "input_end_marker"})
                        await asyncio.sleep(.02)
                    for _ in range(130):
                        await ws.send_bytes(bytes(320))
                        await asyncio.sleep(.02)

                sender = asyncio.create_task(send_audio())
                try:
                    while True:
                        item = await ws.receive_json(timeout=100)
                        kind = item.get("type")
                        if kind == "transcript_final":
                            transcript = item["text"]
                        elif kind == "flush":
                            last_epoch = item["epoch"]
                            frames = []
                        elif kind == "audio":
                            if first_pcm is None:
                                first_pcm = time.monotonic_ns()
                            if last_epoch is not None and item["epoch"] != last_epoch:
                                raise RuntimeError("stale_audio_after_flush")
                            audio = base64.b64decode(item["pcm"], validate=True)
                            if not 0 < len(audio) <= 640 or len(audio) % 2:
                                raise RuntimeError("invalid_pcm_frame")
                            frames.append(audio)
                        elif kind == "turn_done":
                            await sender
                            assert frames and last_voiced_sent and first_pcm and transcript
                            stages = (item.get("timeline") or {}).get("stages_monotonic_ns", {})
                            assert STAGES.issubset(stages), "missing_timing_stages"
                            assert not (item.get("timeline") or {}).get("invalid_order")
                            assert all(stages[b] >= stages[a] for a, b in zip(
                                ["input_end_ingress", "asr_start", "asr_final",
                                 "llm_start", "llm_first_token", "reply_validated", "tts_first_ready"],
                                ["asr_start", "asr_final", "llm_start", "llm_first_token",
                                 "reply_validated", "tts_first_ready", "audio_first_sent"]))
                            result.update({
                                "completed": True,
                                "model": "hepta-qwen3-4b",
                                "transcript": transcript,
                                "reply": item.get("text"),
                                "fixture_sha256": hashlib.sha256(original).hexdigest(),
                                "output_sha256": hashlib.sha256(b"".join(frames)).hexdigest(),
                                "audio_frames": len(frames),
                                "synthetic_end_to_received_first_pcm_ms":
                                    round((first_pcm - last_voiced_sent) / 1e6, 3),
                                "voice_host_timeline": item["timeline"],
                                "engine": info["llm_engine"],
                                "model_host": info["llm_gpu_host"],
                            })
                            await ws.send_json({"type": "end"})
                            break
                        elif kind == "error":
                            raise RuntimeError("pipeline_error:" + str(item))
                finally:
                    if not sender.done():
                        sender.cancel()
        print(json.dumps({"completed": result["completed"], "ms": result.get("synthetic_end_to_received_first_pcm_ms"),
                          "frames": result.get("audio_frames"), "transcript": result.get("transcript"),
                          "reply": result.get("reply")}, ensure_ascii=False), flush=True)
    except Exception as e:
        result["error"] = {"type": type(e).__name__, "message": str(e)[:300]}
        raise
    finally:
        result["recorded_at"] = time.time()
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
