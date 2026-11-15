#!/usr/bin/env bash
# Batch B9 (user 2026-11-15): one-question worlds whose question the world's own rulebook answers differently from the
# defaults (--moved-only), so a model that recites default rules gets them wrong. Build, pass 1, pass 2 on misses.
set -u
cd "$(dirname "$0")/.."
PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python
export TMPDIR=$PWD/outputs/tmp PYTHONPATH=src:. PYTHONIOENCODING=utf-8
T=outputs/teacher/final; L=$T/logs_cli; mkdir -p $L
NOTE="--teacher-note gen/assets/teacher_note.md --price 0.28,0.028,0.42 --workers 6 --concurrency 6 --yes"
resume() { [ -d "$1/logs" ] && ls "$1"/logs/*.json >/dev/null 2>&1 && echo --resume; }
[ -f data_gen/final/B9/BUILT ] || { $PY -m gen.world --out data_gen/final/B9 --n 380 --seed 20 --jobs 12 --llm-readme --yes --moved-only \
    --intent-boost gen/assets/intent_boost_B5.json --seen data_gen/final/*/manifest.jsonl > $L/build_B9.log 2>&1 && date +%T > data_gen/final/B9/BUILT; }
for k in 0 1 2 3 4; do out=$T/p1_B9_$k
  $PY -m gen.teacher --split data_gen/final/B9 --all --shard $k/5 --out $out --max-usd 0.45 --config config.final_nothink.yaml $NOTE $(resume $out) > $L/p1_B9_$k.log 2>&1 &
done; wait
for k in 0 1 2 3 4; do out=$T/p2_B9_$k
  $PY -m gen.teacher --split data_gen/final/B9 --redo-from $T/p1_B9_$k --out $out --max-usd 0.06 --config config.deepseek_direct.yaml $NOTE $(resume $out) > $L/p2_B9_$k.log 2>&1 &
done; wait
echo "B9 DONE $(date +%T)"
