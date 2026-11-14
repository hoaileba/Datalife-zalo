set -e
cd "$(dirname "$0")/../../.."
X=experiments/EXP-20261109-01-controlled-query-norm-public1000
: "${VLLM_BASE_URL:?set VLLM_BASE_URL in process environment}"
: "${VLLM_API_KEY:?set VLLM_API_KEY in process environment}"
: "${VLLM_MODEL:?set VLLM_MODEL in process environment}"
PYTHONPATH="$X/code/src" python3 "$X/code/test_normalization.py"
python3 "$X/code/runner.py" check
python3 "$X/code/runner.py" smoke
python3 "$X/code/runner.py" full
