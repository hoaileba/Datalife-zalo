from __future__ import annotations

import glob
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments/EXP-20261107-04-example-selection/code"))
sys.argv = ["final_score", str(ROOT / "experiments/EXP-20261105-07-domain-helpers")]
exec((ROOT / "experiments/EXP-20261105-07-domain-helpers/code/final_score.py").read_text(encoding="utf-8").split("Q, G = load(")[0])

from follow_rate import parts, skeleton

EXP_DIR = ROOT / "experiments/EXP-20261107-05-train1000"
RUN = ROOT / "experiments/EXP-20261107-04-example-selection/run/public1000_v10"
ORACLE = ROOT / "experiments/EXP-20261106-04-pos-header-detail/out/oracle_public.jsonl"


def rows(path: Path | str) -> dict[str, dict]:
    return {row["id"]: row for row in map(json.loads, Path(path).read_text(encoding="utf-8").splitlines()) if row}


def stage(*, answer: dict | None, gold: dict, oracle: dict, examples: list[str], final: str | None) -> str:
    kind = (answer or {}).get("type")
    if gold["type"] == "unanswerable":
        return "gold không trả lời được, agent vẫn trả lời"
    if kind in (None, "abstain", "unanswerable"):
        return "agent bỏ trống / báo không trả lời được"
    if not oracle["ok"]:
        return "oracle cũng sai (thiếu helper hoặc dữ liệu)"
    if final is None:
        return "không có code cuối"
    want = skeleton(oracle["code"])
    if skeleton(final) == want:
        return "đúng hàm, sai tham số / kỳ / tên" if kind == gold["type"] else "đúng hàm, sai dạng đáp án"
    ranks = [index for index, code in enumerate(examples) if skeleton(code) == want]
    if ranks[:1] == [0]:
        return "top-1 đúng hàm, model không theo"
    if ranks:
        return "ví dụ đúng hàm ở hạng 2–4"
    return "không ví dụ nào đúng hàm"


def main() -> int:
    run = Path(sorted(glob.glob(str(RUN / "*")))[-1])
    questions = rows(ROOT / "public_test/questions.jsonl")
    truth = rows(ROOT / "experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl")
    submission = rows(ROOT / "experiments/EXP-20261107-04-example-selection/out/submission.jsonl")
    oracle = {qid: row | {"ok": row["ok"] in (True, "True")} for qid, row in rows(ORACLE).items()}
    report = []
    for qid, question in questions.items():
        verdict = status(submission.get(qid), truth[qid], question["business_id"], True)
        if verdict == "ok":
            continue
        log = (run / f"{qid}.log").read_text(encoding="utf-8")
        examples, final = parts(log)
        where = stage(answer=submission.get(qid), gold=truth[qid], oracle=oracle[qid], examples=examples, final=final)
        report.append({"id": qid, "set": "public", "shop": question["business_id"], "verdict": verdict, "stage": where, "question": question["question"], "gold": truth[qid], "got": submission.get(qid), "final_code": final, "oracle_code": oracle[qid]["code"] if oracle[qid]["ok"] else None, "top1": examples[0] if examples else None, "examples": examples})
    print(f"{len(report)} câu public không đúng")
    for name, count in Counter(item["stage"] for item in report).most_common():
        sub = [item for item in report if item["stage"] == name]
        print(f"  {name:44} {count:3}  (sai {sum(item['verdict'] == 'wrong' for item in sub)}, trống {sum(item['verdict'] == 'blank' for item in sub)})")
    (EXP_DIR / "out/errors_public_v10.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
