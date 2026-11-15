#!/usr/bin/env bash
# More unique worlds after the final run (user 2026-11-15: >3000 kept train questions). Batches B5..B8 of 300 worlds,
# intents re-weighted toward the ones earlier batches kept few of (gen/assets/intent_boost_B5.json); each batch's
# teacher pass 1 overlaps the next build; pass 2 (thinking) on misses at the end. Resumable like run_final_data.sh.
set -u
cd "$(dirname "$0")/.."
PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python
export TMPDIR=$PWD/outputs/tmp PYTHONPATH=src:. PYTHONIOENCODING=utf-8
T=outputs/teacher/final; L=$T/logs_cli; mkdir -p $L
NOTE="--teacher-note gen/assets/teacher_note.md --price 0.28,0.028,0.42 --workers 6 --concurrency 6 --yes"
P1="--config config.final_nothink.yaml $NOTE"
P2="--config config.deepseek_direct.yaml $NOTE --max-usd 0.35"
resume() { [ -d "$1/logs" ] && ls "$1"/logs/*.json >/dev/null 2>&1 && echo --resume; }
build() {   # name seed
  [ -f data_gen/final/$1/BUILT ] && return
  $PY -m gen.world --out data_gen/final/$1 --n 300 --seed $2 --jobs 10 --llm-readme --yes \
      --intent-boost gen/assets/intent_boost_B5.json --seen data_gen/final/*/manifest.jsonl > $L/build_$1.log 2>&1 \
      && date +%T > data_gen/final/$1/BUILT
}
p1() {      # name
  for k in 0 1 2 3 4; do
    out=$T/p1_$1_$k
    $PY -m gen.teacher --split data_gen/final/$1 --all --shard $k/5 --out $out --max-usd 0.5 $P1 $(resume $out) > $L/p1_$1_$k.log 2>&1 &
  done
}
build B5 16
for pair in "B6 17 B5" "B7 18 B6" "B8 19 B7"; do
  set -- $pair
  build $1 $2 & p1 $3; wait
done
p1 B8; wait
for b in B5 B6 B7 B8; do for k in 0 1 2 3 4; do
  $PY -m gen.teacher --split data_gen/final/$b --redo-from $T/p1_${b}_$k --out $T/p2_${b}_$k $P2 $(resume $T/p2_${b}_$k) > $L/p2_${b}_$k.log 2>&1 &
done; wait; done
echo "ALL DONE $(date +%T)"
