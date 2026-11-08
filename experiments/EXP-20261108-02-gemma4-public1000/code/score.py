from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.argv = ["final_score", str(ROOT / "experiments/EXP-20261105-07-domain-helpers")]
exec((ROOT / "experiments/EXP-20261105-07-domain-helpers/code/final_score.py").read_text(encoding="utf-8").split("Q, G = load(")[0])

EXP_DIR = ROOT / "experiments/EXP-20261108-02-gemma4-public1000"
RUNS = (ROOT / "experiments/EXP-20261108-01-gemma4-vllm/run/public100", EXP_DIR / "run/remaining900")


def rows(path: Path | str) -> dict[str, dict]:
    return {row["id"]: row for row in map(json.loads, Path(path).read_text(encoding="utf-8").splitlines()) if row}


def main() -> int:
    folders = [sorted(path for path in run.iterdir() if path.is_dir())[-1] for run in RUNS]
    questions = rows(ROOT / "public_test/questions.jsonl")
    truth = rows(ROOT / "experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl")
    gemma4 = {}
    for folder in folders:
        gemma4 |= rows(folder / "answers.jsonl")
    (EXP_DIR / "out/answers_public_gemma4.jsonl").write_text("".join(json.dumps(gemma4[qid], ensure_ascii=False) + "\n" for qid in questions if qid in gemma4), encoding="utf-8")
    api = {path.stem for folder in folders for path in folder.glob("q_*.log") if "LỖI API" in path.read_text(encoding="utf-8")}
    sets = {"gemma-3 nộp (EXP-04)": rows(ROOT / "experiments/EXP-20261107-04-example-selection/out/submission.jsonl"), "gemma-3 v10 (EXP-04)": rows(ROOT / "experiments/EXP-20261107-04-example-selection/out/answers_public_v10.jsonl"), "gemma-4 v10 (vLLM)": gemma4}
    verdict = {name: {qid: status(found.get(qid), truth[qid], questions[qid]["business_id"], True) for qid in questions} for name, found in sets.items()}
    print(f"đủ đáp án gemma-4: {len(gemma4)}/1000, lỗi API: {len(api)}")
    for name, found in verdict.items():
        count = Counter(found.values())
        print(f"{name:22} PA={(count['ok'] - count['wrong']) / 1000:+.3f}  đúng={count['ok']} sai={count['wrong']} trống={count['blank']}")
    old, new = verdict["gemma-3 v10 (EXP-04)"], verdict["gemma-4 v10 (vLLM)"]
    print("gemma-4 so với gemma-3: được", sum(old[q] != "ok" and new[q] == "ok" for q in questions), "mất", sum(old[q] == "ok" and new[q] != "ok" for q in questions))
    print("câu lỗi API, gemma-3 cùng câu:", dict(Counter(old[q] for q in api)))
    no_api = [q for q in questions if q not in api]
    for name in ("gemma-3 v10 (EXP-04)", "gemma-4 v10 (vLLM)"):
        count = Counter(verdict[name][q] for q in no_api)
        print(f"  bỏ {len(api)} câu lỗi API: {name:22} đúng={count['ok']} sai={count['wrong']} trống={count['blank']}")
    (EXP_DIR / "out/api_errors.json").write_text(json.dumps(sorted(api)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
