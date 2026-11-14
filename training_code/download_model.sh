#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REVISION=707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7

hf download google/gemma-4-12B-it --revision "$REVISION" --local-dir "$ROOT/models/gemma-4-12B-it"
echo "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d  $ROOT/models/gemma-4-12B-it/model.safetensors" | sha256sum -c -
