#!/usr/bin/env bash
# bash /code/predict.sh : /data -> /result/submission.jsonl, /result/logs/
set -uo pipefail
export DATAMATE_START=$(date +%s)
DATA=${DATA:-/data}
RESULT=${RESULT:-/result}
MODEL_DIR=${MODEL_DIR:-/code/models/model}
GPU_UTIL=${GPU_UTIL:-0.90}
MAX_MODEL_LEN=${MAX_MODEL_LEN:-32768}
mkdir -p "$RESULT/logs"

vllm serve "$MODEL_DIR" --served-model-name gemma-12b --host 127.0.0.1 --port 8000 --seed 0 \
  --max-model-len "$MAX_MODEL_LEN" --gpu-memory-utilization "$GPU_UTIL" > "$RESULT/vllm.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null; wait $SERVER 2>/dev/null' EXIT

for i in $(seq 1 600); do
  curl -sf http://127.0.0.1:8000/v1/models > /dev/null && break
  kill -0 $SERVER 2>/dev/null || { echo "vllm exited, see $RESULT/vllm.log"; tail -20 "$RESULT/vllm.log"; exit 1; }
  sleep 2
done
echo "model ready after $(( $(date +%s) - DATAMATE_START ))s"

cd /code
PYTHONPATH=/code/src /opt/agent/bin/python -m datamate.runner \
  --split "$DATA" --all --out "$RESULT" --config /code/config.yaml
echo "done after $(( $(date +%s) - DATAMATE_START ))s"
