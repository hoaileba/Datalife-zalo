#!/bin/zsh
set -a; . ./.env; set +a; export OPENROUTER_API_KEY="$OPENROUTER_KEY"
E=experiments/EXP-20261107-02-question-rewrite
Q=$E/out/public100.jsonl
run() { PYTHONPATH=src nice -n 10 python3 -W ignore -m datamate_agent.agent --dataset public_test --questions $Q --parallel 2 "$@" ; }
run --prompt v9 --model google/gemma-3-12b-it --out $E/run/A_gemma_v9 > $E/logs/02-A.log 2>&1 &
run --prompt v10 --model google/gemma-3-12b-it --out $E/run/B_gemma_v10 > $E/logs/02-B.log 2>&1 &
wait
run --prompt v10 --model google/gemma-3-12b-it --rewrites $E/out/rewrites_gemma.jsonl --out $E/run/C_gemma_v10_rewrite > $E/logs/02-C.log 2>&1 &
run --prompt v10 --model qwen/qwen3.5-9b --rewrites $E/out/rewrites_qwen.jsonl --out $E/run/D_qwen_v10_rewrite > $E/logs/02-D.log 2>&1 &
wait
touch $E/logs/02-done
