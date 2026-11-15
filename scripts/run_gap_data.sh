#!/usr/bin/env bash
# Gap-filling real train questions on the reskins (scripts/select_train_gap.py): pass 1 then pass 2 on misses.
# Cap: 4 x $0.22 pass 1 + 4 x $0.03 pass 2 = $1.00 at most.
set -u
cd "$(dirname "$0")/.."
PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python
export TMPDIR=$PWD/outputs/tmp PYTHONPATH=src:. PYTHONIOENCODING=utf-8
T=outputs/teacher/final; L=$T/logs_cli; mkdir -p $L
NOTE="--teacher-note gen/assets/teacher_note.md --price 0.28,0.028,0.42 --workers 4 --concurrency 4 --yes"
resume() { [ -d "$1/logs" ] && ls "$1"/logs/*.json >/dev/null 2>&1 && echo --resume; }
for r in 1 2; do for k in 0 1; do
  out=$T/p1_G${r}_$k
  $PY -m gen.teacher --split data_gen/reskin_$r --ids-file data_gen/final_ids/G_r$r.txt --shard $k/2 --out $out \
      --max-usd 0.22 --config config.final_nothink.yaml $NOTE $(resume $out) > $L/p1_G${r}_$k.log 2>&1 &
done; done; wait
for r in 1 2; do for k in 0 1; do
  out=$T/p2_G${r}_$k
  $PY -m gen.teacher --split data_gen/reskin_$r --redo-from $T/p1_G${r}_$k --out $out --max-usd 0.03 \
      --config config.deepseek_direct.yaml $NOTE $(resume $out) > $L/p2_G${r}_$k.log 2>&1 &
done; done; wait
echo "GAP DONE $(date +%T)"
