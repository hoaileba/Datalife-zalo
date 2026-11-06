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
BAD = {"biz_106", "biz_107", "biz_109", "biz_113", "biz_124", "biz_126"}
load = lambda p: {json.loads(l)["id"]: json.loads(l) for l in open(p, encoding="utf-8") if l.strip()}
G = load("train/answers.jsonl")
TEST = set(load("train/split/test_questions.jsonl"))
LIB = {json.loads(l)["question"] for l in open("src/datamate_agent/prompts/library.jsonl", encoding="utf-8")}
SOURCES = (f"{E}/run/*/*", "experiments/EXP-20261105-09-train-3000-coverage/run/*", "experiments/EXP-20261105-08-train-sample-200/run/*", "experiments/EXP-20261105-07-domain-helpers/run/test/*")


def finals():
    out, null = {}, set()
    for pattern in SOURCES:
        for folder in glob.glob(pattern):
            for path in glob.glob(f"{folder}/q_*.log"):
                found = re.search(r"^FINAL:\n(.*)$", open(path, encoding="utf-8").read(), flags=re.M)
                if not found:
                    continue
                key = os.path.basename(path)[:-4]
                if found.group(1).strip() == "null":
                    null.add(key)
                else:
                    out[key] = json.loads(found.group(1))
    return out, null - set(out)


def status(a, i):
    return "blank" if a.get("type") in (None, "abstain") else "ok" if is_correct(a, G[i]) else "wrong"


def line(values):
    c = collections.Counter(values)
    n, r = len(values), c["ok"] + c["wrong"]
    return f"n={n:4d} điểm={c['ok'] - c['wrong']:+5d} PA={(c['ok'] - c['wrong']) / max(n, 1):.3f} đúng={c['ok']:4d} sai={c['wrong']:4d} trống={c['blank']:3d} acc={c['ok'] / max(r, 1):.3f} cov={r / max(n, 1):.3f}"


A, null = finals()
done_all = []
for number in range(1, 6):
    Q = load(f"{E}/inputs/fold_{number}.jsonl")
    ids = [i for i in Q if i in A]
    st = {i: status(A[i], i) for i in ids}
    print(f"tập {number} xong {len(ids)}/{len(Q)} {line(list(st.values()))}")
    if len(sys.argv) > 2:
        print("   24 shop           ", line([s for i, s in st.items() if Q[i]["business_id"] not in BAD]))
        print("   6 shop thiếu lines", line([s for i, s in st.items() if Q[i]["business_id"] in BAD]))
        print("   không có trong thư viện, 24 shop", line([s for i, s in st.items() if Q[i]["business_id"] not in BAD and Q[i]["question"] not in LIB]))
    done_all += list(st.values())
print("tổng", line(done_all), "lỗi mạng chưa có đáp án", len(null))
