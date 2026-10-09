#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/alex/hepta-pipecat-voice
DATA=/home/alex/.local/share/hepta-pipecat
ENGINEKEY=/home/alex/.local/state/hepta-inference/ab-20261009/api.key
IMAGE=sha256:b725f5836d23e1388052104754effb598f05229da6df51181b5cdce06b5a4a2f

test "$(id -u)" = 1000
test -r "$ENGINEKEY"
test -S "$DATA/state/llama.sock"
test -S "$DATA/state/tools.sock"
test -f "$DATA/state/ledger.sqlite3"
test -x "$DATA/venv/bin/python"
test -d "$DATA/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
test -d "$DATA/models/vits-melo-tts-zh_en"

exec /usr/bin/podman run --rm --name hepta-pocket-voice-lab \
  --network none --userns keep-id --user 1000:1000 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --cpus 4 --memory 5g --memory-swap 5g --pids-limit 192 \
  --tmpfs /tmp:rw,nosuid,size=256m \
  --mount "type=bind,src=$ROOT,dst=$ROOT,readonly" \
  --mount "type=bind,src=$DATA,dst=$DATA,readonly" \
  --mount "type=bind,src=$DATA/state,dst=$DATA/state" \
  --mount "type=bind,src=$ENGINEKEY,dst=$ENGINEKEY,readonly" \
  --workdir "$ROOT" \
  --env HOME=/tmp --env HEPTA_VOICE_DATA="$DATA" \
  --env HEPTA_VOICE_ENGINE_KEY_FILE="$ENGINEKEY" \
  --env PYTHONDONTWRITEBYTECODE=1 --env PYTHONUNBUFFERED=1 \
  --env NUMBA_CACHE_DIR=/tmp/numba --env OPENBLAS_NUM_THREADS=1 \
  --env OMP_NUM_THREADS=2 --env CUDA_VISIBLE_DEVICES=-1 \
  "$IMAGE" "$DATA/venv/bin/python" -m hepta_voice.server
