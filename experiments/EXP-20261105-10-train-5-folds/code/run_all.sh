#!/bin/zsh
E=experiments/EXP-20261105-10-train-5-folds
set -a; . ./.env; set +a; export OPENROUTER_API_KEY="$OPENROUTER_KEY"
for number in 1 2 3 4 5; do
  python3 $E/code/remaining.py $E $number
  [ -s $E/inputs/todo_$number.jsonl ] && PYTHONPATH=$E/code/src nice -n 10 python3 -W ignore -m datamate_agent.agent --dataset train --questions $E/inputs/todo_$number.jsonl --parallel 5 --out $E/run/fold_$number > $E/logs/fold_$number.txt 2>&1
  echo "fold $number xong $(date)"
done
