from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

from datamate.shop import HELPERS, Shop, pct_change

from .fewshot import Example, entities_of, mask_question
from .intents import classify
from .score import is_correct

SAFE_BUILTINS = {"round": round, "int": int, "max": max, "all": all, "zip": zip}
OK_BAD_SHOP = "SHOPCRASH"


def env_of(shop: Shop) -> dict[str, Any]:
    return {"clock": shop.clock, "lines": shop.lines, "orders": shop.orders, "tables": shop.tables, "pd": pd, "pct_change": pct_change, **SAFE_BUILTINS, **{name: getattr(shop, name) for name in HELPERS}}


def solve_group(job: tuple[str, str, str, tuple[dict[str, Any], ...], str]) -> tuple[dict[str, Any], ...]:
    root, shop_id, as_of, rows, calendar = job
    try:
        shop = Shop(f"{root}/{shop_id}", as_of=as_of, calendar=calendar)
    except (ValueError, KeyError, TypeError) as error:
        return tuple({**row, "intent": OK_BAD_SHOP, "code": "", "got": f"{type(error).__name__}: {error}"[:200], "ok": False} for row in rows)
    entities = entities_of(shop)
    env = env_of(shop)
    out = []
    for row in rows:
        parsed = classify(row["question"], entities)
        if parsed is None:
            out.append({**row, "intent": "UNMATCHED", "code": "", "got": None, "ok": False})
            continue
        intent, kind, code = parsed
        try:
            got = eval(code, env)
            got = got.item() if hasattr(got, "item") else got
            ok = is_correct({"type": kind, "answer": got}, row["gold"])
        except (ValueError, KeyError, TypeError, IndexError, AttributeError, ZeroDivisionError) as error:
            got, ok = f"EXC {type(error).__name__}: {error}"[:200], False
        out.append({**row, "intent": intent, "kind": kind, "code": code, "masked": mask_question(row["question"], entities), "got": got if isinstance(got, (int, float, str, list, bool, dict)) else str(got), "ok": bool(ok)})
    return tuple(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sinh code helper từ mẫu câu, chấm với gold, ghi các cặp đúng thành thư viện few-shot")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--calendar", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--library", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    gold = {json.loads(raw)["id"]: json.loads(raw) for raw in args.answers.read_text(encoding="utf-8").splitlines() if raw.strip()}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for raw in args.questions.read_text(encoding="utf-8").splitlines():
        row = json.loads(raw)
        groups[(row["business_id"], row["as_of_date"])].append({**row, "gold": gold[row["id"]]})
    jobs = [(args.root, shop, as_of, tuple(rows), args.calendar) for (shop, as_of), rows in groups.items()]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = [row for batch in pool.map(solve_group, jobs, chunksize=4) for row in batch]
    args.out.write_text("\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in results), encoding="utf-8")
    table: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for row in results:
        cell = table[row["intent"]]
        cell[0] += 1
        cell[1] += int(row["ok"])
        cell[2] += int(str(row["got"]).startswith("EXC"))
    matched = [row for row in results if row["intent"] != "UNMATCHED"]
    print(f"total {len(results)} ok {sum(row['ok'] for row in results)} matched {len(matched)} wrong {sum(not row['ok'] for row in matched)}")
    for intent, (count, ok, failed) in sorted(table.items(), key=lambda pair: -pair[1][0]):
        print(f"{intent:26s} n={count:5d} ok={ok:5d} acc={ok / count:.2f} exc={failed}")
    if args.library:
        seen: dict[tuple[str, str], Example] = {}
        for row in results:
            if row["ok"]:
                seen.setdefault((row["masked"], row["intent"]), Example(question=row["question"], masked=row["masked"], answer_type=row["kind"], code=row["code"], intent=row["intent"]))
        args.library.write_text("\n".join(example.model_dump_json() for example in seen.values()) + "\n", encoding="utf-8")
        print(f"library {len(seen)} examples, {len({example.intent for example in seen.values()})} intents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
