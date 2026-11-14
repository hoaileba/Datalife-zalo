#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRAIN_SOURCE="${1:-$ROOT/train}"

if [ ! -f "$TRAIN_SOURCE/questions.jsonl" ] || [ ! -d "$TRAIN_SOURCE/split" ]; then
  echo "train data not found at $TRAIN_SOURCE" >&2
  exit 1
fi
mkdir -p "$ROOT/training_code/data/train"
cp -R "$TRAIN_SOURCE/." "$ROOT/training_code/data/train/"
find "$ROOT/training_code/data/train" -name .DS_Store -delete
PYTHONPATH="$ROOT/src" python3 "$ROOT/training_code/data_generation/make_manifest.py" --code "$ROOT"
