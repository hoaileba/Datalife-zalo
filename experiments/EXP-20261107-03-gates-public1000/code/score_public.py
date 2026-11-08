from __future__ import annotations

import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.argv = ["final_score", str(ROOT / "experiments/EXP-20261105-07-domain-helpers")]
exec((ROOT / "experiments/EXP-20261105-07-domain-helpers/code/final_score.py").read_text(encoding="utf-8").split("Q, G = load(")[0])

EXP_DIR = ROOT / "experiments/EXP-20261107-03-gates-public1000"


def rows(path: Path | str) -> dict[str, dict]:
    return {row["id"]: row for row in map(json.loads, Path(path).read_text(encoding="utf-8").splitlines()) if row}


def main() -> int:
    run = Path(glob.glob(str(EXP_DIR / "run/public1000/*"))[0])
    questions = rows(ROOT / "public_test/questions.jsonl")
    truth = rows(ROOT / "experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl")
    old = rows(ROOT / "error/answers_public_current.jsonl")
    submitted = rows(ROOT / "experiments/EXP-20261105-07-domain-helpers/out/submission.jsonl")
    new = rows(run / "answers.jsonl")
    labels = json.loads((ROOT / "error/labels_public.json").read_text(encoding="utf-8"))
    group_of = {qid: group for group, row in labels.items() for qid in row["ids"]}
    verdict = {name: {qid: status(found.get(qid), truth[qid], questions[qid]["business_id"], True) for qid in questions} for name, found in (("đã nộp 0,811 (EXP-07)", submitted), ("gemma cũ 0,849", old), ("mới (EXP-20261107-03)", new))}
    for name, found in verdict.items():
        count = Counter(found.values())
        print(f"{name:24} PA={(count['ok'] - count['wrong']) / 1000:+.3f}  đúng={count['ok']} sai={count['wrong']} trống={count['blank']}")
    for base in ("gemma cũ 0,849", "đã nộp 0,811 (EXP-07)"):
        pairs = Counter((verdict[base][qid], verdict["mới (EXP-20261107-03)"][qid]) for qid in questions)
        print(f"so với {base}:", dict(sorted(pairs.items())))
    gained = [qid for qid in questions if verdict["gemma cũ 0,849"][qid] != "ok" and verdict["mới (EXP-20261107-03)"][qid] == "ok"]
    lost = [qid for qid in questions if verdict["gemma cũ 0,849"][qid] == "ok" and verdict["mới (EXP-20261107-03)"][qid] != "ok"]
    print("được theo nhóm lỗi cũ:", Counter(group_of.get(qid, "?") for qid in gained))
    logs = {path.stem: path.read_text(encoding="utf-8") for path in run.glob("q_*.log")}
    events = {"từ chối dạng": lambda text: re.search(r"ERROR: câu hỏi cần", text) is not None, "cổng kỳ ngoài dữ liệu": lambda text: "shop has no sales data in" in text, "unanswerable → bỏ trống": lambda text: "code lỗi, không có bằng chứng" in text, "lỗi API": lambda text: "LỖI API" in text}
    for name, test in events.items():
        hit = [qid for qid, text in logs.items() if test(text)]
        outcome = Counter((verdict["gemma cũ 0,849"][qid], verdict["mới (EXP-20261107-03)"][qid]) for qid in hit)
        print(f"{name:26} {len(hit):4} câu, cũ→mới: {dict(outcome)}")
    out = [{"id": qid, "question": questions[qid]["question"], "old": verdict["gemma cũ 0,849"][qid], "new": verdict["mới (EXP-20261107-03)"][qid], "group_old": group_of.get(qid), "truth": truth[qid], "got_old": old.get(qid), "got_new": new.get(qid)} for qid in gained + lost]
    (EXP_DIR / "out/changed_vs_old.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in out), encoding="utf-8")
    print("mất:", len(lost))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
