from __future__ import annotations

import contextlib
import glob
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datamate_agent.agent import PREAMBLE, parse_answer, prepare_code

RUN_DIRS = ("experiments/EXP-20261106-01-deterministic-fixes/run/*_retry/*", "experiments/EXP-20261106-01-deterministic-fixes/run/public/*", "experiments/EXP-20261105-07-domain-helpers/run/public/*")
FINAL_CODE = re.compile(r"\[CALL\] final\n\[CODE\]\n(.*?)\n\[OUTPUT\]", re.S)


def final_code(qid: str) -> str | None:
    for pattern in RUN_DIRS:
        for log in sorted(glob.glob(str(ROOT / pattern / f"{qid}.log")), reverse=True):
            text = Path(log).read_text(encoding="utf-8")
            if '"type": null' in text.split("FINAL:\n")[-1][:40] or "\nnull\n" in text[-300:]:
                continue
            found = FINAL_CODE.findall(text)
            return found[-1] if found else None
    return None


questions = [json.loads(line) for line in (ROOT / "public_test/questions.jsonl").read_text(encoding="utf-8").splitlines()]
answers = {json.loads(line)["id"]: json.loads(line) for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()}
groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
for row in questions:
    groups[(row["business_id"], row["as_of_date"])].append(row)
out = {}
for (shop, as_of), rows in groups.items():
    env: dict = {}
    setup = PREAMBLE.replace("{{as_of}}", as_of).replace('Shop("norm"', f'Shop("{ROOT}/artifacts/norm/public_test/{shop}"').replace('calendar="calendar.csv"', f'calendar="{ROOT}/public_test/calendar.csv"')
    exec(setup, env)
    for row in rows:
        old = answers.get(row["id"])
        code = final_code(row["id"])
        if not old or old.get("type") in (None, "abstain", "unanswerable") or code is None:
            continue
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                exec(prepare_code(code), dict(env))
            value = parse_answer([text for text in buffer.getvalue().splitlines() if text.strip()][-1], old["type"])
        except Exception as error:
            value = f"EXC {type(error).__name__}: {str(error)[:80]}"
        if value != old.get("answer"):
            out[row["id"]] = {"id": row["id"], "type": old["type"], "answer": value, "old": old.get("answer"), "code": code}
Path(sys.argv[2]).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in out.values()), encoding="utf-8")
print("đáp án đổi khi chạy lại code FINAL cũ:", len(out))
