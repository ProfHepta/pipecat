#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
DATA=${HEPTA_VOICE_DATA:-$HOME/.local/share/hepta-pipecat}
# CPU-only is intentional: do not re-enable the GPU suspended for H3.
exec docker run --rm --name hepta-pipecat-lab --network none --user "$(id -u):$(id -g)" \
 --read-only --cap-drop ALL --security-opt no-new-privileges --cpus 4 --memory 6g --memory-swap 6g --pids-limit 192 \
 --tmpfs /tmp:rw,nosuid,size=256m \
 --mount type=bind,src="$ROOT",dst="$ROOT",readonly \
 --mount type=bind,src="$DATA",dst="$DATA",readonly \
 --mount type=bind,src="$DATA/state",dst="$DATA/state" \
 --workdir "$ROOT" --env HOME=/tmp --env HEPTA_VOICE_DATA="$DATA" \
 --env PYTHONDONTWRITEBYTECODE=1 --env PYTHONUNBUFFERED=1 --env NUMBA_CACHE_DIR=/tmp/numba \
 --env PIPECAT_SMART_TURN_LOG_DATA=0 --env OPENBLAS_NUM_THREADS=1 --env OMP_NUM_THREADS=2 \
 --env CUDA_VISIBLE_DEVICES=-1 --env OLLAMA_VULKAN=0 --env OLLAMA_HOST=127.0.0.1:11445 \
 --env OLLAMA_MODELS="$DATA/models/ollama" --env OLLAMA_NO_CLOUD=1 --env OLLAMA_MAX_LOADED_MODELS=1 --env OLLAMA_NUM_PARALLEL=1 \
 sha256:62d572b92f9f32d3427b6d220ad1f9dca9c7b6ffad37d295425037dbff78abaf \
 /bin/bash -c '"$HEPTA_VOICE_DATA/runtime/bin/ollama" serve >"$HEPTA_VOICE_DATA/state/ollama.log" 2>&1 & child=$!; trap "kill $child 2>/dev/null || true" EXIT; exec "$HEPTA_VOICE_DATA/venv/bin/python" -m hepta_voice.server'
