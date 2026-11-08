#!/bin/zsh
set -a; . ./.env; set +a; export OPENROUTER_API_KEY="$OPENROUTER_KEY"
E=experiments/EXP-20261107-03-gates-public1000
G=google/gemma-3-12b-it
PYTHONPATH=src nice -n 10 python3 -W ignore -m datamate_agent.question_rewrite --dataset public_test --questions public_test/questions.jsonl --model $G --parallel 6 --out $E/out/analysis_public_gemma.jsonl >> $E/logs/03-analysis-public.log 2>&1
PYTHONPATH=src nice -n 10 python3 -W ignore -m datamate_agent.agent --dataset public_test --prompt v10 --model $G --rewrites $E/out/analysis_public_gemma.jsonl --parallel 4 --out $E/run/public1000 > $E/logs/05-agent-public1000.log 2>&1
touch $E/logs/stage2.done
