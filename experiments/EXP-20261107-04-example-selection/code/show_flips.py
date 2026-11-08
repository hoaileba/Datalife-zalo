from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).parent))
from split_cause import exp03_log

EXP_DIR = ROOT / "experiments/EXP-20261107-04-example-selection"
PAIR = re.compile(r"^- (.*)\n  FINAL (\w+): (.*)$", re.M)


def first_pair(log: str) -> tuple[str, str] | None:
    user = log.split("\nUSER:\n", 1)[1].split("\nASSISTANCE:", 1)[0] if "\nUSER:\n" in log else ""
    found = PAIR.search(user)
    return (found.group(1), found.group(3)) if found else None


def final_code(log: str) -> str:
    codes = re.findall(r"^\[CODE\]\n(.*)", log, re.M)
    return codes[-1] if codes else "-"


def main() -> int:
    group = sys.argv[1]
    lib = [json.loads(line) for line in (ROOT / "src/datamate_agent/prompts/library.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    before = {json.loads(line)["question"] for line in (EXP_DIR / "out/library_before.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    agent_made = {row["question"] for row in lib[1109:]}
    cause = json.loads((EXP_DIR / "out/cause_tfidf_sure.json").read_text(encoding="utf-8"))
    route = json.loads((EXP_DIR / "out/route_public1000.json").read_text(encoding="utf-8"))
    answers03 = {row["id"]: row for row in map(json.loads, (ROOT / "experiments/EXP-20261107-03-gates-public1000/out/answers_public_final.jsonl").read_text(encoding="utf-8").splitlines()) if row}
    run = Path(sorted(glob.glob(str(EXP_DIR / "run/public1000/*")))[-1])
    for row in map(json.loads, (EXP_DIR / "out/changed_vs_exp03_public1000.jsonl").read_text(encoding="utf-8").splitlines()):
        where = cause.get(row["id"], route[row["id"]])
        if where != group:
            continue
        old_log = exp03_log(row["id"], answers03.get(row["id"])) or ""
        new_log = (run / f"{row['id']}.log").read_text(encoding="utf-8")
        old_top, new_top = first_pair(old_log), first_pair(new_log)
        tag = "agent" if new_top and new_top[0] in agent_made else "cũ" if new_top and new_top[0] in before else "train mới"
        print(f"== {row['id']} {row['exp03']}→{row['exp04']}  {row['question']}")
        print(f"   truth={json.dumps(row['truth'].get('answer'), ensure_ascii=False)[:90]}")
        print(f"   03: {json.dumps((row['got_exp03'] or {}).get('answer'), ensure_ascii=False)[:70]} | code {final_code(old_log)[:110]}")
        print(f"   04: {json.dumps((row['got_exp04'] or {}).get('answer'), ensure_ascii=False)[:70]} | code {final_code(new_log)[:110]}")
        if old_top != new_top:
            print(f"   top03: {old_top[1][:100] if old_top else '-'}")
            print(f"   top04 [{tag}]: {new_top[1][:100] if new_top else '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
