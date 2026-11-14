#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${DATAMATE_DATA_DIR:-/data}"
RESULT_DIR="${DATAMATE_RESULT_DIR:-/result}"
WORK_DIR="${DATAMATE_WORK_DIR:-/tmp/datamate}"
CODE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="$CODE_DIR/models/gemma-4-12B-it"
SERVED_MODEL=gemma-12b
PORT=8000
SEED=20261103
PARALLEL=8
TENSOR_PARALLEL=2
MAX_MODEL_LEN=32768
GPU_MEMORY_UTILIZATION=0.85
SERVER_WAIT_SECONDS=1800
PYTHON="${DATAMATE_PYTHON:-python3}"

mkdir -p "$RESULT_DIR/logs" "$WORK_DIR"
export PYTHONPATH="$CODE_DIR/deps:$CODE_DIR/src"
export PYTHONUNBUFFERED=1 PYTHONWARNINGS=ignore
export VLLM_USE_FLASHINFER_SAMPLER=0
started=$(date +%s)
echo "[predict.sh] start $(date -Iseconds) data=$DATA_DIR result=$RESULT_DIR"

if [ -z "${DATAMATE_EXTERNAL_LLM:-}" ]; then
  env -u PYTHONPATH vllm serve "$MODEL_DIR" \
    --served-model-name "$SERVED_MODEL" \
    --host 127.0.0.1 --port "$PORT" \
    --tensor-parallel-size "$TENSOR_PARALLEL" \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
    --seed "$SEED" \
    --enable-prefix-caching \
    > "$RESULT_DIR/logs/vllm_server.log" 2>&1 &
  server=$!
  trap 'kill "$server" 2>/dev/null || true' EXIT
  ready=""
  for _ in $(seq "$SERVER_WAIT_SECONDS"); do
    if "$PYTHON" -c "import urllib.request, sys; urllib.request.urlopen('http://127.0.0.1:$PORT/health', timeout=2)" 2>/dev/null; then
      ready=1
      break
    fi
    if ! kill -0 "$server" 2>/dev/null; then
      echo "[predict.sh] vllm server exited, see $RESULT_DIR/logs/vllm_server.log" >&2
      exit 1
    fi
    sleep 1
  done
  if [ -z "$ready" ]; then
    echo "[predict.sh] vllm server not ready after ${SERVER_WAIT_SECONDS}s" >&2
    exit 1
  fi
  export VLLM_BASE_URL="http://127.0.0.1:$PORT/v1" VLLM_API_KEY=EMPTY VLLM_MODEL="$SERVED_MODEL"
  echo "[predict.sh] load_model_ms=$(( ($(date +%s) - started) * 1000 ))"
fi

"$PYTHON" -m datamate_agent.pipeline \
  --backend vllm \
  --dataset "$DATA_DIR" \
  --work "$WORK_DIR" \
  --out "$RESULT_DIR/submission.jsonl" \
  --log-dir "$RESULT_DIR/logs" \
  --parallel "$PARALLEL" \
  --seed "$SEED"

echo "[predict.sh] done $(date -Iseconds) total_ms=$(( ($(date +%s) - started) * 1000 ))"
