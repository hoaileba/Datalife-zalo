from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from datamate.fmt import load_questions, validate_line

REPO = Path("/Users/lebahoai/Workspace/zalo/2026")
EXPERIMENT = REPO / "experiments" / "EXP-20261029-01-public-test-submission"
QUESTIONS = REPO / "public_test" / "questions.jsonl"
ANSWER_DIR = EXPERIMENT / "out" / "answers"
SUBMISSION = EXPERIMENT / "out" / "submission.jsonl"


def collect() -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    found: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for path in sorted(ANSWER_DIR.glob("*.jsonl")):
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                line = json.loads(raw)
            except json.JSONDecodeError as error:
                problems.append(f"{path.name}:{number} not valid json: {error}")
                continue
            try:
                validate_line(line)
            except ValueError as error:
                problems.append(f"{path.name}:{number} bad format -> {error}")
                continue
            qid = line["id"]
            if qid in found:
                problems.append(f"{path.name}:{number} duplicate id {qid}")
                continue
            found[qid] = line
    return found, tuple(problems)


def main() -> int:
    questions = load_questions(QUESTIONS)
    shop_of = {q["id"]: q["business_id"] for q in questions}
    found, problems = collect()

    lines: list[dict[str, Any]] = []
    missing: list[str] = []
    for question in questions:
        qid = question["id"]
        line = found.get(qid)
        if line is None:
            missing.append(qid)
            lines.append({"id": qid, "type": "abstain"})
        else:
            lines.append(line)

    unknown = sorted(set(found) - set(shop_of))

    SUBMISSION.parent.mkdir(parents=True, exist_ok=True)
    with SUBMISSION.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")

    per_shop: dict[str, Counter[str]] = defaultdict(Counter)
    per_type: Counter[str] = Counter()
    for line in lines:
        kind = line["type"]
        per_shop[shop_of[line["id"]]][kind] += 1
        per_type[kind] += 1

    answered = sum(v for k, v in per_type.items() if k != "abstain")
    print(f"submission: {SUBMISSION}")
    print(f"questions={len(questions)} lines={len(lines)} answered={answered} abstain={per_type['abstain']}")
    print(f"coverage={answered / len(questions):.4f}")
    print("\nper type:")
    for kind, n in sorted(per_type.items(), key=lambda kv: -kv[1]):
        print(f"  {kind:<14} {n}")
    print("\nper shop:")
    header = ("number", "percent", "list", "date", "string", "boolean", "table", "unanswerable", "abstain")
    print("  shop      total " + " ".join(f"{h[:6]:>6}" for h in header))
    for shop in sorted(per_shop):
        counts = per_shop[shop]
        total = sum(counts.values())
        row = " ".join(f"{counts.get(h, 0):>6}" for h in header)
        cov = (total - counts.get("abstain", 0)) / total if total else 0.0
        print(f"  {shop:<9} {total:>5} {row}   cov={cov:.2f}")
    if missing:
        print(f"\nTHIEU {len(missing)} id, da ghi abstain:")
        for qid in missing[:20]:
            print(f"  {qid} ({shop_of[qid]})")
    if unknown:
        print(f"\nID LA khong co trong questions.jsonl: {len(unknown)}")
        for qid in unknown[:20]:
            print(f"  {qid}")
    if problems:
        print(f"\nVAN DE {len(problems)} dong:")
        for problem in problems[:40]:
            print(f"  {problem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
