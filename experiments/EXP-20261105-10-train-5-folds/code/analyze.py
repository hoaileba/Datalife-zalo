from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys

sys.path.insert(0, "src")
from datamate_agent.score import is_correct

E, S = sys.argv[1], sys.argv[2]
BAD = {"biz_106", "biz_107", "biz_109", "biz_113", "biz_124", "biz_126"}
load = lambda p: {json.loads(l)["id"]: json.loads(l) for l in open(p, encoding="utf-8") if l.strip()}
G, Q = load("train/answers.jsonl"), load("train/questions.jsonl")
TEST = set(load("train/split/test_questions.jsonl"))
LIB = {json.loads(l)["question"] for l in open("src/datamate_agent/prompts/library.jsonl", encoding="utf-8")}
SOURCES = (f"{E}/run/*/*", "experiments/EXP-20261105-09-train-3000-coverage/run/*", "experiments/EXP-20261105-08-train-sample-200/run/*", "experiments/EXP-20261105-07-domain-helpers/run/test/*")
rows = {}
for pattern in SOURCES:
    for folder in glob.glob(pattern):
        for path in glob.glob(f"{folder}/q_*.log"):
            i = os.path.basename(path)[:-4]
            text = open(path, encoding="utf-8").read()
            found = re.search(r"^FINAL:\n(.*)$", text, flags=re.M)
            if not found:
                continue
            a = None if found.group(1).strip() == "null" else json.loads(found.group(1))
            if i in rows and a is None:
                continue
            if i in TEST:
                rows[i] = {"id": i, "test": True, "a": a}
                continue
            ass = text.split("ASSISTANCE:", 1)[-1]
            codes = re.findall(r"\[CALL\] (?:run|final)\n\[CODE\]\n(.*?)\n\[OUTPUT\]", ass, flags=re.S)
            top = re.search(r"^  FINAL (\w+): (.*)$", text.split("ASSISTANCE:", 1)[0], flags=re.M)
            rows[i] = {"id": i, "test": False, "a": a, "code": " ;; ".join(codes), "first": codes[0] if codes else "", "turns": len(re.findall(r"^Turn \d+", ass, flags=re.M)), "top": top.group(2) if top else "", "noshop": "shop has no" in ass, "error": "LỖI API" in text}


def status(i):
    a = rows[i]["a"]
    return "blank" if a is None or a.get("type") in (None, "abstain") else "ok" if is_correct(a, G[i]) else "wrong"


def line(ids):
    c = collections.Counter(status(i) for i in ids)
    n, r = len(ids), c["ok"] + c["wrong"]
    return f"n={n:4d} PA={(c['ok'] - c['wrong']) / max(n, 1):.3f} đúng={c['ok']:4d} sai={c['wrong']:4d} trống={c['blank']:3d} acc={c['ok'] / max(r, 1):.3f} cov={r / max(n, 1):.3f}"


ids = list(rows)
train = [i for i in ids if not rows[i]["test"]]
test = [i for i in ids if rows[i]["test"]]
print("tổng     ", line(ids))
print("train_*  ", line(train))
print("test_*   ", line(test), "(chỉ tính điểm)")
for label, group in (("24 shop", [i for i in ids if Q[i]["business_id"] not in BAD]), ("6 shop", [i for i in ids if Q[i]["business_id"] in BAD])):
    print(label, line(group))
print("24 shop, không trong thư viện", line([i for i in ids if Q[i]["business_id"] not in BAD and Q[i]["question"] not in LIB]))
print("24 shop, trong thư viện      ", line([i for i in ids if Q[i]["business_id"] not in BAD and Q[i]["question"] in LIB]))
print("theo shop (train_* + test_*):")
for shop in sorted({Q[i]["business_id"] for i in ids}):
    print(" ", shop, line([i for i in ids if Q[i]["business_id"] == shop]))
print("theo loại, 24 shop:")
for kind in sorted({g["type"] for g in G.values()}):
    print(f"  {kind:13s}", line([i for i in ids if G[i]["type"] == kind and Q[i]["business_id"] not in BAD]))
bad = [i for i in train if status(i) != "ok" and Q[i]["business_id"] not in BAD]
print("sai và trống của train_*, 24 shop:", len(bad))
print("lượt", sorted(collections.Counter(rows[i]["turns"] for i in bad).items()))
print("cặp loại", collections.Counter(((rows[i]["a"] or {}).get("type"), G[i]["type"]) for i in bad).most_common(12))


def short(v, n=46):
    s = json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + "…"


with open(f"{S}/bad_train.txt", "w", encoding="utf-8") as out:
    for i in sorted(bad, key=lambda k: Q[k]["business_id"]):
        r = rows[i]
        a = r["a"] or {}
        out.write(f"{i[2:8]} {Q[i]['business_id'][-3:]} {'L' if Q[i]['question'] in LIB else '-'} {status(i)[0]} t{r['turns']} | {Q[i]['question'][:92]}\n  gold {G[i]['type']}:{short(G[i].get('answer'))} | got {a.get('type')}:{short(a.get('answer'))}\n  code {r['code'][:118]!r}\n")
six = [i for i in train if Q[i]["business_id"] in BAD]
print("6 shop train_*: câu trả unanswerable", sum((rows[i]["a"] or {}).get("type") == "unanswerable" for i in six), "có shop has no", sum(rows[i]["noshop"] for i in six), "trên", len(six))
