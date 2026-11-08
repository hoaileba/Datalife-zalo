set -e
cd "$(dirname "$0")/../../.."
set -a; . ./.env; set +a; export OPENROUTER_API_KEY="$OPENROUTER_KEY"
X=experiments/EXP-20261107-05-train1000
G=google/gemma-3-12b-it
PYTHONPATH=src nice -n 10 python3 -W ignore -m datamate_agent.question_rewrite --dataset train --questions $X/out/train1000.jsonl --backend openrouter --model $G --parallel 3 --out $X/out/analysis_train_gemma.jsonl > $X/logs/01-analysis.log 2>&1
PYTHONPATH=src nice -n 10 python3 -W ignore -m datamate_agent.agent --dataset train --questions $X/out/train1000.jsonl --prompt v10 --backend openrouter --model $G --holdout --rewrites $X/out/analysis_train_gemma.jsonl --parallel 4 --out $X/run/train1000 > $X/logs/02-agent.log 2>&1
