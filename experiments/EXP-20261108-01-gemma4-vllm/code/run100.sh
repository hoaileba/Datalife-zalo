set -e
cd "$(dirname "$0")/../../.."
X=experiments/EXP-20261108-01-gemma4-vllm
start=$(date +%s)
PYTHONPATH=src nice -n 10 python3 -W ignore -m datamate_agent.question_rewrite --backend vllm --dataset public_test --questions $X/out/public100.jsonl --parallel 5 --out $X/out/analysis_public100.jsonl > $X/logs/01-analysis.log 2>&1
mid=$(date +%s)
PYTHONPATH=src nice -n 10 python3 -W ignore -m datamate_agent.agent --backend vllm --dataset public_test --questions $X/out/public100.jsonl --prompt v10 --rewrites $X/out/analysis_public100.jsonl --parallel 5 --out $X/run/public100 > $X/logs/02-agent.log 2>&1
end=$(date +%s)
echo "analysis_seconds=$((mid-start)) agent_seconds=$((end-mid))" > $X/logs/timing.txt
