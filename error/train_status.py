from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from datamate_agent.score import is_correct

BROKEN = {"biz_106", "biz_109", "biz_124"}
SOURCES = (
    ("EXP-08", "experiments/EXP-20261105-08-train-sample-200/run/*"),
    ("EXP-09", "experiments/EXP-20261105-09-train-3000-coverage/run/*"),
    ("EXP-10", "experiments/EXP-20261105-10-train-5-folds/run/*/*"),
    ("EXP-07", "experiments/EXP-20261105-07-domain-helpers/run/test/*"),
    ("EXP-20261106-01", "experiments/EXP-20261106-01-deterministic-fixes/run/test*/*"),
    ("EXP-20261106-03", "experiments/EXP-20261106-03-optional-order-id/run/three/*"),
    ("EXP-20261106-04", "experiments/EXP-20261106-04-pos-header-detail/run/three/*"),
)


def load(path: str) -> dict[str, dict]:
    return {json.loads(line)["id"]: json.loads(line) for line in open(ROOT / path, encoding="utf-8") if line.strip()}


def latest_answers() -> tuple[dict[str, dict], dict[str, str]]:
    answers, source = {}, {}
    for name, pattern in SOURCES:
        for folder in sorted(glob.glob(str(ROOT / pattern))):
            for path in glob.glob(f"{folder}/q_*.log"):
                found = re.search(r"^FINAL:\n(.*)$", open(path, encoding="utf-8").read(), flags=re.M)
                if found and found.group(1).strip() != "null":
                    key = os.path.basename(path)[:-4]
                    answers[key], source[key] = json.loads(found.group(1)), name
    return answers, source


def kind(answer: dict, gold: dict) -> str:
    got, want = answer.get("type"), gold.get("type")
    if got in (None, "abstain"):
        return "bỏ trống"
    if is_correct(answer, gold):
        return "đúng"
    if want == "unanswerable":
        return "đáng lẽ unanswerable"
    if got == "unanswerable":
        return "unanswerable nhầm"
    if got != want:
        return "sai dạng đáp án"
    if want in ("number", "percent"):
        try:
            gap = abs(float(answer["answer"]) - float(gold["answer"])) / max(abs(float(gold["answer"])), 1e-9)
        except (TypeError, ValueError):
            return "sai giá trị"
        return "số lệch dưới 10%" if gap < 0.1 else "số lệch lớn"
    return "sai giá trị"


def line(values: list[str]) -> str:
    count = collections.Counter(values)
    right, blank = count["đúng"], count["bỏ trống"]
    wrong = len(values) - right - blank
    return f"n={len(values):4d} PA={(right - wrong) / max(len(values), 1):+.3f} đúng={right:4d} sai={wrong:4d} trống={blank:3d}"


def main() -> None:
    gold = load("train/answers.jsonl")
    splits = {"train_*": load("train/split/train_questions.jsonl"), "test_*": load("train/split/test_questions.jsonl")}
    library = {json.loads(line)["question"] for line in open(ROOT / "src/datamate_agent/prompts/library.jsonl", encoding="utf-8")}
    answers, source = latest_answers()
    rows = []
    for split, questions in splits.items():
        for qid, question in questions.items():
            answer = answers.get(qid)
            rows.append({"id": qid, "split": split, "shop": question["business_id"], "question": question["question"], "ran": answer is not None, "source": source.get(qid), "kind": kind(answer, gold[qid]) if answer else None, "got": answer, "gold": gold[qid], "broken_shop": question["business_id"] in BROKEN, "in_library": question["question"] in library})
    (Path(__file__).parent / "train_test_status.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    for split in splits:
        part = [row for row in rows if row["split"] == split]
        ran = [row for row in part if row["ran"]]
        print(f"== {split}: tổng {len(part)}, đã chạy {len(ran)}, chưa chạy {len(part) - len(ran)}")
        print("   nguồn", dict(collections.Counter(row["source"] for row in ran)))
        print("   tất cả đã chạy   ", line([row["kind"] for row in ran]))
        print("   41 shop còn lại   ", line([row["kind"] for row in ran if not row["broken_shop"]]))
        print("   3 shop POS (kiểu 2)", line([row["kind"] for row in ran if row["broken_shop"]]))
        print("   shop chạy được, câu có trong thư viện   ", line([row["kind"] for row in ran if not row["broken_shop"] and row["in_library"]]))
        print("   shop chạy được, câu không có trong thư viện ", line([row["kind"] for row in ran if not row["broken_shop"] and not row["in_library"]]))
        print("   kiểu lỗi, shop chạy được", collections.Counter(row["kind"] for row in ran if not row["broken_shop"] and row["kind"] != "đúng").most_common())
        print("   kiểu lỗi, 3 shop POS (kiểu 2)", collections.Counter(row["kind"] for row in ran if row["broken_shop"] and row["kind"] != "đúng").most_common())
        print("   chưa chạy theo shop", sorted(collections.Counter(row["shop"] for row in part if not row["ran"]).items()))


if __name__ == "__main__":
    main()
