from __future__ import annotations

import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).parent))
from split_cause import exp03_log

EXP_DIR = ROOT / "experiments/EXP-20261107-04-example-selection"
PAIR = re.compile(r"^- (.*)\n  FINAL (\w+): (.*)$", re.M)
CALL = re.compile(r"([A-Za-z_]\w*)\s*\(")
KEYWORD = re.compile(r"(by|metric)\s*=\s*['\"](\w+)['\"]")
IGNORED = frozenset({"round", "int", "len", "sum", "float", "abs", "list", "str"})


def skeleton(code: str) -> tuple:
    calls = [name for name in CALL.findall(code) if name not in IGNORED and not name.startswith(("clock", "month", "day", "between", "this_", "last_"))]
    return tuple(sorted(set(calls))), tuple(sorted(set(KEYWORD.findall(code)))), "sold_orders" in code and "order_total" in code


def parts(log: str) -> tuple[list[str], str | None]:
    user = log.split("\nUSER:\n", 1)[1].split("\nASSISTANCE:", 1)[0] if "\nUSER:\n" in log else ""
    codes = re.findall(r"^\[CODE\]\n(.*)", log, re.M)
    return [match.group(3) for match in PAIR.finditer(user)], codes[-1] if codes else None


def main() -> int:
    route = json.loads((EXP_DIR / "out/route_public1000.json").read_text(encoding="utf-8"))
    answers03 = {row["id"]: row for row in map(json.loads, (ROOT / "experiments/EXP-20261107-03-gates-public1000/out/answers_public_final.jsonl").read_text(encoding="utf-8").splitlines()) if row}
    run = Path(sorted(glob.glob(str(EXP_DIR / "run/public1000/*")))[-1])
    table = Counter()
    for qid in route:
        for name, log in (("EXP-03 (v10)", exp03_log(qid, answers03.get(qid)) or ""), ("EXP-04 (v11)", (run / f"{qid}.log").read_text(encoding="utf-8"))):
            examples, final = parts(log)
            if not examples or final is None:
                table[name, "không có code"] += 1
                continue
            matched = [index for index, code in enumerate(examples) if skeleton(code) == skeleton(final)]
            table[name, "theo top-1" if matched[:1] == [0] else f"theo ví dụ {matched[0] + 1}" if matched else "tự viết"] += 1
    for name in ("EXP-03 (v10)", "EXP-04 (v11)"):
        print(name, {key: value for (who, key), value in sorted(table.items()) if who == name})
    return 0


if __name__ == "__main__" and len(sys.argv) == 1:
    raise SystemExit(main())


def accuracy() -> int:
    route = json.loads((EXP_DIR / "out/route_public1000.json").read_text(encoding="utf-8"))
    answers03 = {row["id"]: row for row in map(json.loads, (ROOT / "experiments/EXP-20261107-03-gates-public1000/out/answers_public_final.jsonl").read_text(encoding="utf-8").splitlines()) if row}
    changed = {row["id"]: row for row in map(json.loads, (EXP_DIR / "out/changed_vs_exp03_public1000.jsonl").read_text(encoding="utf-8").splitlines())}
    run = Path(sorted(glob.glob(str(EXP_DIR / "run/public1000/*")))[-1])
    lost_top1_right = Counter()
    for qid, row in changed.items():
        if row["exp03"] != "ok":
            continue
        old_examples, old_final = parts(exp03_log(qid, answers03.get(qid)) or "")
        new_examples, new_final = parts((run / f"{qid}.log").read_text(encoding="utf-8"))
        right_top1 = bool(new_examples) and old_final is not None and skeleton(new_examples[0]) == skeleton(old_final)
        lost_top1_right[route[qid], "top-1 EXP-04 cùng hàm với code đúng của EXP-03" if right_top1 else "top-1 khác"] += 1
    for key, value in sorted(lost_top1_right.items()):
        print("mất:", key, value)
    return 0


if __name__ == "__main__" and len(sys.argv) > 1:
    accuracy()
