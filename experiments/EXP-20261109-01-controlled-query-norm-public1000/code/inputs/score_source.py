from __future__ import annotations

import collections
import glob
import json
import re
import sys
import unicodedata

import pandas as pd

sys.path.insert(0, "src")
from datamate_agent.score import is_correct

E = sys.argv[1]
load = lambda p: {json.loads(l)["id"]: json.loads(l) for l in open(p, encoding="utf-8") if l.strip()}


def fold(x):
    t = unicodedata.normalize("NFD", str(x)).casefold().replace("đ", "d")
    return " ".join(re.sub(r"[^0-9a-z]+", " ", "".join(c for c in t if not unicodedata.combining(c))).split())


cache = {}


def rows_of(shop):
    if shop not in cache:
        out = []
        for p in glob.glob(f"artifacts/norm/public_test/{shop}/*.csv"):
            if p.endswith(".dropped.csv"):
                continue
            d = pd.read_csv(p, dtype=str, nrows=200000).fillna("")
            cols = [c for c in d.columns if re.search(r"customer|khach|ten|name|code|ma|supplier|ncc|staff|nv|nhan", c, flags=re.I) and not re.search(r"item|source", c, flags=re.I)]
            if cols:
                out.extend(set(" | ".join(fold(v) for v in t) for t in d[cols].drop_duplicates().itertuples(index=False)))
        cache[shop] = out
    return cache[shop]


def same(shop, a, b):
    a, b = fold(a), fold(b)
    return a == b or (bool(a) and bool(b) and any(a in r and b in r for r in rows_of(shop)))


def status(a, g, shop, entity):
    if a is None or a.get("type") in (None, "abstain"):
        return "blank"
    if is_correct(a, g):
        return "ok"
    if entity and a["type"] == g["type"]:
        if g["type"] == "string" and same(shop, a.get("answer"), g.get("answer")):
            return "ok"
        if g["type"] == "list" and isinstance(a.get("answer"), list) and all(isinstance(x, str) for x in g["answer"]) and len(a["answer"]) == len(g["answer"]) and all(same(shop, x, y) for x, y in zip(a["answer"], g["answer"])):
            return "ok"
        if g["type"] == "table" and len(a["answer"]["rows"]) == len(g["answer"]["rows"]) and all(same(shop, x[0], y[0]) and x[1:] == y[1:] for x, y in zip(a["answer"]["rows"], g["answer"]["rows"])):
            return "ok"
    return "wrong"


def line(values):
    c = collections.Counter(values)
    n = len(values)
    answered = c["ok"] + c["wrong"]
    return f"n={n:4d} điểm={c['ok'] - c['wrong']:+5d} PA={(c['ok'] - c['wrong']) / max(n, 1):.3f} đúng={c['ok']:4d} sai={c['wrong']:4d} trống={c['blank']:3d} acc={c['ok'] / max(answered, 1):.3f} cov={answered / max(n, 1):.3f}"


Q, G = load("public_test/questions.jsonl"), load("experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl")
A = load(f"{E}/out/submission.jsonl")
OLD = load("experiments/EXP-20261105-03-submission-unanswerable-format/out/submission.jsonl")
USED = set(json.load(open("experiments/EXP-20261104-05-public-1000-v7/inputs/used_before.json")))
st = {i: status(A.get(i), G[i], Q[i]["business_id"], True) for i in Q}
st0 = {i: status(OLD.get(i), G[i], Q[i]["business_id"], True) for i in Q}
strict = {i: status(A.get(i), G[i], Q[i]["business_id"], False) for i in Q}
print("public nộp, coi mã và tên cùng đối tượng là đúng", line(list(st.values())))
print("public nộp, chấm chặt                           ", line(list(strict.values())))
print("bản nộp 0.524, cùng cách chấm                   ", line(list(st0.values())))
print("thành đúng", sum(st0[i] != "ok" and st[i] == "ok" for i in Q), "từ đúng thành sai hoặc trống", sum(st0[i] == "ok" and st[i] != "ok" for i in Q))
print("chưa từng dùng", line([s for i, s in st.items() if i not in USED]))
for shop in sorted({q["business_id"] for q in Q.values()}):
    ids = [i for i in Q if Q[i]["business_id"] == shop]
    print(shop, line([st[i] for i in ids]), "| trước", line([st0[i] for i in ids]).split()[2])
for kind in sorted({g["type"] for g in G.values()}):
    print(f"{kind:13s}", line([st[i] for i in Q if G[i]["type"] == kind]))
said = [i for i in Q if (A.get(i) or {}).get("type") == "unanswerable"]
print("model unanswerable", len(said), "đúng", sum(st[i] == "ok" for i in said), "sai", sum(st[i] == "wrong" for i in said))
Qt, Gt, At = load("train/split/test_questions.jsonl"), load("train/split/test_answers.jsonl"), load(f"{E}/out/answers_test.jsonl")
BAD = {"biz_106", "biz_107", "biz_109", "biz_113", "biz_124", "biz_126"}
st2 = {i: status(At.get(i), Gt[i], Qt[i]["business_id"], False) for i in Qt}
print("test tất cả  ", line(list(st2.values())))
print("test 24 shop ", line([s for i, s in st2.items() if Qt[i]["business_id"] not in BAD]))
print("test 6 shop  ", line([s for i, s in st2.items() if Qt[i]["business_id"] in BAD]))
