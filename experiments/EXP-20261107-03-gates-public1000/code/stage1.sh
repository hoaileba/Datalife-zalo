#!/bin/zsh
set -a; . ./.env; set +a; export OPENROUTER_API_KEY="$OPENROUTER_KEY"
E=experiments/EXP-20261107-03-gates-public1000
G=google/gemma-3-12b-it
PYTHONPATH=src nice -n 10 python3 -W ignore -m datamate_agent.agent --dataset public_test --questions $E/out/public100.jsonl --prompt v10 --model $G --rewrites $E/out/analysis100_gemma.jsonl --parallel 3 --out $E/run/try100 > $E/logs/02-try100.log 2>&1 &
PYTHONPATH=src nice -n 10 python3 -W ignore -m datamate_agent.question_rewrite --dataset public_test --questions public_test/questions.jsonl --model $G --parallel 3 --out $E/out/analysis_public_gemma.jsonl > $E/logs/03-analysis-public.log 2>&1 &
PYTHONPATH=src nice -n 10 python3 -W ignore -m datamate_agent.question_rewrite --dataset train --questions $E/out/train1000.jsonl --model $G --parallel 3 --out $E/out/analysis_train_gemma.jsonl > $E/logs/04-analysis-train.log 2>&1 &
wait
touch $E/logs/stage1.done
