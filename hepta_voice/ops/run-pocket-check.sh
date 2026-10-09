#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/alex/hepta-pipecat-voice
DATA=/home/alex/.local/share/hepta-pipecat
IMAGE=sha256:b725f5836d23e1388052104754effb598f05229da6df51181b5cdce06b5a4a2f
case "${1:-}" in
  pcm) MODULE=hepta_voice.ops.pocket_local_pcm ;;
  controls) MODULE=hepta_voice.ops.acceptance ;;
  pytest) MODULE=pytest; shift ;;
  *) echo "usage: run-pocket-check.sh pcm|controls|pytest" >&2; exit 64 ;;
esac
exec /usr/bin/podman run --rm --network none --userns keep-id --user 1000:1000 \
 --read-only --cap-drop ALL --security-opt no-new-privileges \
 --cpus 2 --memory 3g --memory-swap 3g --pids-limit 128 \
 --tmpfs /tmp:rw,nosuid,size=128m \
 --mount "type=bind,src=$ROOT,dst=$ROOT,readonly" \
 --mount "type=bind,src=$DATA,dst=$DATA,readonly" \
 --mount "type=bind,src=$DATA/state,dst=$DATA/state" \
 --mount "type=bind,src=$DATA/evidence,dst=$DATA/evidence" \
 --workdir "$ROOT" --env HOME=/tmp --env HEPTA_VOICE_DATA="$DATA" \
 --env PYTHONDONTWRITEBYTECODE=1 --env OPENBLAS_NUM_THREADS=1 \
 --env OMP_NUM_THREADS=1 \
 "$IMAGE" "$DATA/venv/bin/python" -m "$MODULE" "$@"
