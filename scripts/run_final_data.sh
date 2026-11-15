#!/usr/bin/env bash
# The final SFT data run (outputs/tmp/PLAN_FINAL_DATA.md, commit tag final-data-v3). Stages overlap world builds with
# teacher pass 1; pass 2 (thinking) on every pass-1 folder at the end. Each stage writes outputs/teacher/final/STAGE_<n>.
# Resumable: a stage whose marker exists is skipped; teacher folders resume with --resume.
set -u
cd "$(dirname "$0")/.."
PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python
export TMPDIR=$PWD/outputs/tmp PYTHONPATH=src:. PYTHONIOENCODING=utf-8
T=outputs/teacher/final; L=$T/logs_cli; mkdir -p $L
NOTE="--teacher-note gen/assets/teacher_note.md --price 0.28,0.028,0.42 --workers 6 --concurrency 6 --yes"
P1="--config config.final_nothink.yaml $NOTE"
P2="--config config.deepseek_direct.yaml $NOTE --max-usd 0.35"

resume() { [ -d "$1/logs" ] && ls "$1"/logs/*.json >/dev/null 2>&1 && echo --resume; }
p1_shards() {   # name split select n cap
  local name=$1 split=$2 sel=$3 n=$4 cap=$5
  for k in $(seq 0 $((n - 1))); do
    out=$T/p1_${name}_$k
    $PY -m gen.teacher --split $split $sel --shard $k/$n --out $out --max-usd $cap $P1 $(resume $out) > $L/p1_${name}_$k.log 2>&1 &
  done
}
build() {       # out n seed jobs [--val]
  $PY -m gen.world --out $1 --n $2 --seed $3 --jobs $4 --llm-readme --yes ${5:-} > $L/build_$(basename $1).log 2>&1
}
stage() { [ -f $T/STAGE_$1 ] && { echo "stage $1 done before"; return 1; }; echo "== stage $1 $(date +%T)"; return 0; }
mark() { date +%T > $T/STAGE_$1; echo "== stage $1 finished $(date +%T)"; }

if stage 1; then build data_gen/final/B2 700 12 10 & p1_shards A data/train "--ids-file data_gen/final_ids/A_rest.txt" 5 0.5; wait; mark 1; fi
if stage 2; then build data_gen/final/B3 700 13 10 & p1_shards B2 data_gen/final/B2 --all 5 0.8; wait; mark 2; fi
if stage 3; then (build data_gen/final/B4 270 14 10; build data_gen/final/CW 120 15 10 --val) & p1_shards B3 data_gen/final/B3 --all 5 0.8; wait; mark 3; fi
if stage 4; then
  p1_shards B4 data_gen/final/B4 --all 3 0.5
  p1_shards CW data_gen/final/CW --all 2 0.4
  p1_shards CS data/train "--ids-file data_gen/final_ids/C_shops.txt" 1 0.3
  wait; mark 4
fi
if stage 5; then
  declare -A SPLIT=([A]=data/train [CS]=data/train [B2]=data_gen/final/B2 [B3]=data_gen/final/B3 [B4]=data_gen/final/B4 [CW]=data_gen/final/CW)
  running=0
  for p in $T/p1_A_* $T/p1_B2_* $T/p1_B3_* $T/p1_B4_* $T/p1_CW_* $T/p1_CS_*; do
    base=$(basename $p); part=${base#p1_}; part=${part%_*}; out=$T/p2_${base#p1_}
    $PY -m gen.teacher --split ${SPLIT[$part]} --redo-from $p --out $out $P2 $(resume $out) > $L/p2_${base#p1_}.log 2>&1 &
    running=$((running + 1))
    if [ $running -ge 6 ]; then wait -n; running=$((running - 1)); fi
  done
  wait; mark 5
fi
echo "ALL DONE $(date +%T)"
