from __future__ import annotations

import glob
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.argv = ["final_score", str(ROOT / "experiments/EXP-20261105-07-domain-helpers")]
exec((ROOT / "experiments/EXP-20261105-07-domain-helpers/code/final_score.py").read_text(encoding="utf-8").split("Q, G = load(")[0])

EXP_DIR = ROOT / "experiments/EXP-20261107-02-question-rewrite"
RUNS = {"gemma cũ (answers_public_current)": ROOT / "error/answers_public_current.jsonl", "qwen v9 (EXP-20261107-01)": next((ROOT / "experiments/EXP-20261107-01-qwen35-9b-public100/run/hundred").glob("v9-*/answers.jsonl"))}
RUNS.update({path.parent.parent.name: path for path in sorted(EXP_DIR.glob("run/*/*/answers.jsonl"))})


def rows(path: Path) -> dict[str, dict]:
    return {row["id"]: row for row in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if row}


def main() -> int:
    truth = rows(ROOT / "experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl")
    questions = rows(ROOT / "public_test/questions.jsonl")
    picked = rows(EXP_DIR / "out/public100.jsonl")
    verdicts = {}
    for name, path in RUNS.items():
        found = rows(path)
        done = [qid for qid in picked if qid in found]
        verdicts[name] = {qid: status(found.get(qid), truth[qid], questions[qid]["business_id"], True) for qid in done}
        count = Counter(verdicts[name].values())
        print(f"{name:36} chạy {len(done):3}/100  PA={(count['ok'] - count['wrong']) / max(len(done), 1):+.3f}  đúng={count['ok']} sai={count['wrong']} trống={count['blank']}")
    base = verdicts["A_gemma_v9"]
    for name in verdicts:
        if name.startswith(("B_", "C_", "D_")):
            common = [qid for qid in verdicts[name] if qid in base]
            gained = [qid for qid in common if base[qid] != "ok" and verdicts[name][qid] == "ok"]
            lost = [qid for qid in common if base[qid] == "ok" and verdicts[name][qid] != "ok"]
            print(f"  {name} so với A trên {len(common)} câu chung: +{len(gained)} {gained} / -{len(lost)} {lost}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
