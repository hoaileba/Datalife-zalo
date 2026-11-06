#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

python3 -m pytest tests/ -q

for script in shops/dev_*.py; do
  [ -e "$script" ] || continue
  echo "== $script"
  python3 "$script"
done

python3 merge.py
