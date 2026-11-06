from __future__ import annotations

import json
import random
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EXPERIMENT = Path(__file__).resolve().parents[1]
QUESTIONS = REPO / "public_test" / "questions.jsonl"
CLAUDE_SUBMISSION = REPO / "experiments" / "EXP-20261029-01-public-test-submission" / "out" / "submission.jsonl"
SEED = 20261031
PER_GROUP = 10
MULTI_TABLE_SHOPS = frozenset({"dev_002", "dev_003", "dev_004", "dev_005", "dev_006", "dev_008", "dev_010", "dev_012", "dev_013", "dev_014"})
JOIN_CONCEPTS = (
    "nhom", "nhap", " no ", "cong no", "ton kho", " ton ", "lai gop", "lai rong", "laix", "gia von", "hoat chat", "ke don",
    "nha cung cap", "han dung", "het han", "lo ", "bao hanh", "gop", "giao", "hoa hong", "tho ", "nhan vien",
    "ship", "voucher", "quy doi", "may cu",
)


def fold(text: str) -> str:
    stripped = "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn")
    return " " + stripped.replace("đ", "d") + " "


def needs_join(question: dict[str, str]) -> bool:
    return question["business_id"] in MULTI_TABLE_SHOPS and any(concept in fold(question["question"]) for concept in JOIN_CONCEPTS)


def main() -> int:
    questions = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    rng = random.Random(SEED)
    joined = sorted((q for q in questions if needs_join(q)), key=lambda q: q["id"])
    multi = rng.sample(joined, PER_GROUP)
    taken = {q["id"] for q in multi}
    rest = sorted((q for q in questions if q["id"] not in taken), key=lambda q: q["id"])
    randoms = rng.sample(rest, PER_GROUP)
    claude = {json.loads(l)["id"]: json.loads(l) for l in CLAUDE_SUBMISSION.read_text(encoding="utf-8").splitlines() if l.strip()}
    sample = [{**q, "group": "multi_table"} for q in multi] + [{**q, "group": "random"} for q in randoms]
    (EXPERIMENT / "inputs" / "questions.jsonl").write_text(
        "".join(json.dumps({k: q[k] for k in ("id", "business_id", "question", "as_of_date")}, ensure_ascii=False) + "\n" for q in sample),
        encoding="utf-8",
    )
    (EXPERIMENT / "inputs" / "groups.json").write_text(json.dumps({q["id"]: q["group"] for q in sample}, indent=2), encoding="utf-8")
    (EXPERIMENT / "out" / "claude_reference.jsonl").write_text(
        "".join(json.dumps(claude[q["id"]], ensure_ascii=False) + "\n" for q in sample), encoding="utf-8"
    )
    print(f"join candidates={len(joined)} sampled={len(sample)} shops={len({q['business_id'] for q in sample})}")
    for q in sample:
        print(q["group"], q["business_id"], q["id"], "|", q["question"], "| claude:", claude[q["id"]]["type"], json.dumps(claude[q["id"]].get("answer"), ensure_ascii=False)[:60])
    return 0


if __name__ == "__main__":
    sys.exit(main())
