from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from datamate.shop import Shop
from datamate_agent.agent import NORM_ROOT
from datamate_agent.fewshot import entities_of, load_library, mask_question


def public_items() -> list[tuple[str, str, str, str, str]]:
    """Câu public mà oracle giải đúng: (id, shop, câu, câu đã che, loại câu của oracle)."""
    oracle = [json.loads(line) for line in (ROOT / "experiments/EXP-20261106-04-pos-header-detail/out/oracle_public.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    questions = {row["id"]: row for row in map(json.loads, (ROOT / "public_test/questions.jsonl").read_text(encoding="utf-8").splitlines())}
    entities: dict[str, dict] = {}
    items = []
    for row in oracle:
        if not row["ok"] or row["intent"] == "UNMATCHED":
            continue
        question = questions[row["id"]]
        shop = question["business_id"]
        if shop not in entities:
            entities[shop] = entities_of(Shop(NORM_ROOT / "public_test" / shop, as_of=question["as_of_date"], calendar=str(ROOT / "public_test/calendar.csv")))
        items.append((row["id"], shop, question["question"], mask_question(question["question"], entities[shop]), row["intent"]))
    return items


def main() -> int:
    library = load_library()
    loo1 = loo4 = 0
    for example in library.examples:
        found = library.nearest(example.masked, exclude=example.question)
        loo1 += found[0].intent == example.intent
        loo4 += example.intent in {item.intent for item in found}
    print(f"thư viện {len(library.examples)} ví dụ, leave-one-out: top-1 {loo1 / len(library.examples):.1%}, top-4 {loo4 / len(library.examples):.1%}")
    items = public_items()
    top1 = top4 = 0
    for _, _, question, masked, intent in items:
        found = library.nearest(masked, exclude=question)
        top1 += found[0].intent == intent
        top4 += intent in {item.intent for item in found}
    print(f"public oracle đúng ({len(items)} câu): top-1 {top1 / len(items):.1%}, top-4 {top4 / len(items):.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
