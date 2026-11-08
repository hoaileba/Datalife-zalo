set -e
cd "$(dirname "$0")/../../.."
X=experiments/EXP-20261108-02-gemma4-public1000
start=$(date +%s)
PYTHONPATH=src nice -n 10 python3 -W ignore -m datamate_agent.question_rewrite --backend vllm --dataset public_test --questions public_test/questions.jsonl --parallel 5 --out $X/out/analysis_public.jsonl > $X/logs/01-analysis.log 2>&1
mid=$(date +%s)
PYTHONPATH=src nice -n 10 python3 -W ignore -m datamate_agent.agent --backend vllm --dataset public_test --questions $X/out/remaining900.jsonl --prompt v10 --rewrites $X/out/analysis_public.jsonl --parallel 5 --out $X/run/remaining900 > $X/logs/02-agent.log 2>&1
end=$(date +%s)
echo "analysis_seconds=$((mid-start)) agent_seconds=$((end-mid))" > $X/logs/timing.txt
