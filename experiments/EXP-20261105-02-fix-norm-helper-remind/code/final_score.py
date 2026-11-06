from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys

sys.path.insert(0, "src")
from datamate_agent.score import is_correct

E = sys.argv[1]
load = lambda path: {json.loads(line)["id"]: json.loads(line) for line in open(path, encoding="utf-8") if line.strip()}
P5 = "experiments/EXP-20261104-05-public-1000-v7"
SETS = {"public": (f"{P5}/inputs/claude_reference.jsonl", "public_test/questions.jsonl"), "test": ("train/split/test_answers.jsonl", "train/split/test_questions.jsonl")}
USED = set(json.load(open(f"{P5}/inputs/used_before.json")))
OLD = load(glob.glob(f"{P5}/run/*/answers.jsonl")[0])


def status(row, truth):
    if row is None or row.get("type") in (None, "abstain"):
        return "blank"
    return "ok" if is_correct(row, truth) else "wrong"


def summary(values):
    c = collections.Counter(values)
    answered = c["ok"] + c["wrong"]
    return f"{len(values):5d} {c['ok'] - c['wrong']:+5d} {c['ok']:4d} {c['wrong']:4d} {c['blank']:3d} {c['ok'] / max(answered, 1):.3f} {answered / max(len(values), 1):.3f}"


for name, (ref, questions) in SETS.items():
    truth, q = load(ref), load(questions)
    path = glob.glob(f"{E}/run/{name}/*/answers.jsonl")[0]
    answers, folder = load(path), os.path.dirname(path)
    st = {i: status(answers.get(i), truth[i]) for i in q}
    print(f"\n== {name}  n score right wrong blank acc cov\nall   {summary(list(st.values()))}")
    if name == "public":
        print("untouched", summary([s for i, s in st.items() if i not in USED]))
        print("used     ", summary([s for i, s in st.items() if i in USED]))
        before = {i: status(OLD.get(i), truth[i]) for i in q}
        print("EXP-05   ", summary(list(before.values())))
        print("wrong/blank->ok", sum(before[i] != "ok" and st[i] == "ok" for i in q), "ok->wrong/blank", sum(before[i] == "ok" and st[i] != "ok" for i in q))
    print("-- shop")
    for shop in sorted({row["business_id"] for row in q.values()}):
        ids = [i for i in q if q[i]["business_id"] == shop]
        extra = f" | EXP-05 {summary([before[i] for i in ids])}" if name == "public" else ""
        print(shop, summary([st[i] for i in ids]), extra)
    print("-- reference type")
    for kind in sorted({row["type"] for row in truth.values() if row["id"] in q}):
        print(f"{kind:13s}", summary([st[i] for i in q if truth[i]["type"] == kind]))
    said = [i for i in q if (answers.get(i) or {}).get("type") == "unanswerable"]
    print("model unanswerable", len(said), "right", sum(st[i] == "ok" for i in said), "wrong", sum(st[i] == "wrong" for i in said))
    logs = {i: open(f"{folder}/{i}.log", encoding="utf-8").read() for i in q if os.path.exists(f"{folder}/{i}.log")}
    turns = [len(re.findall(r"^Turn \d+", text, flags=re.M)) for text in logs.values()]
    print("turns mean", round(sum(turns) / len(turns), 2), "max", max(turns), "api error", sum("LỖI API" in text for text in logs.values()), "null type", sum((answers.get(i) or {}).get("type") is None for i in q), "abstain", sum((answers.get(i) or {}).get("type") == "abstain" for i in q))
    first = [re.search(r"\[CALL\] (\w+)", text.split("ASSISTANCE:", 1)[-1]) for text in logs.values()]
    print("skip READ", sum(match is None or match.group(1) != "read" for match in first))
