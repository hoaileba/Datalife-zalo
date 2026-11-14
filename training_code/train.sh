#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${1:-/tmp/datamate_library_build}"

echo "No model is trained or fine-tuned. This script rebuilds the only generated data, the few-shot example library."
PYTHONPATH="$ROOT/deps:$ROOT/src" python3 "$ROOT/training_code/data_generation/build_library.py" \
  --train "$ROOT/training_code/data/train" \
  --agent-examples "$ROOT/training_code/data/library_agent.jsonl" \
  --work "$WORK" \
  --out "$WORK/library.jsonl" \
  --expected "$ROOT/src/datamate_agent/prompts/library.jsonl"
