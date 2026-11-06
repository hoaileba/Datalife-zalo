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
load = lambda path: {json.loads(line)["id"]: json.loads(line) for line in open(path, encoding="utf-8") if line.strip()}
REF = load("experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl")
BASE = {row["id"]: row for row in json.load(open(f"{S}/rows2.json"))}
GROUPS = json.load(open(f"{E}/inputs/groups.json"))
BUCKETS = json.load(open(f"{E}/out/buckets.json"))["ids"]
SAME = set(json.load(open(f"{S}/same_entity.json")))
FN = re.compile(r"\b(revenue|order_count|quantity|average_order|cancel_rate|cancelled_orders|ranking|sold_orders|customer_count|item_count|sale_price|price_effect|debt_added|debt_repaid|debt_at|debt_aged|debtors|debtor_count|purchase_cost|avg_purchase_price|top_supplier|stock_big|stock_value|stock|purchase_minus_sold|gross_profit|net_profit|expenses|unsold_count|due_orders|best_month|repeat_vehicles|pct_change|increasing)\(")


def status(row):
    if row is None or row.get("type") in (None, "abstain"):
        return "blank"
    return "ok" if is_correct(row, REF[row["id"]]) else "wrong"


def line(ids, get):
    c = collections.Counter(get(i) for i in ids)
    return f"đúng {c['ok']:3d} sai {c['wrong']:3d} trống {c['blank']:2d} điểm {c['ok'] - c['wrong']:+4d}"


arms = {}
for arm in ("remind", "neutral"):
    directory = os.path.dirname(glob.glob(f"{E}/run/{arm}/*/answers.jsonl")[0])
    answers = load(f"{directory}/answers.jsonl")
    arms[arm] = {i: status(answers.get(i)) for i in GROUPS["ignored"] + GROUPS["control"]}
    first = {}
    for i in arms[arm]:
        path = f"{directory}/{i}.log"
        text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        codes = re.findall(r"\[CALL\] (?:run|final)\n\[CODE\]\n(.*?)\n\[OUTPUT\]", text.split("ASSISTANCE:", 1)[-1], flags=re.S)
        match = FN.search(codes[0]) if codes else None
        first[i] = match.group(1) if match else None
    arms[arm + "_first"] = first
    turns = [len(re.findall(r"^Turn \d+", open(f"{directory}/{i}.log", encoding="utf-8").read(), flags=re.M)) for i in arms[arm]]
    print(arm, "answers", len(answers), "lượt TB", round(sum(turns) / len(turns), 2))
for name, ids in GROUPS.items():
    print(f"\n{name} n={len(ids)}")
    print("  gốc    ", line(ids, lambda i: BASE[i]["status"]))
    for arm in ("remind", "neutral"):
        ignored = sum(arms[arm + "_first"][i] == "revenue" and BASE[i]["top_fn"] != "revenue" for i in ids)
        print(f"  {arm:7s}", line(ids, lambda i: arms[arm][i]), f"bỏ ví dụ {ignored}")
        flips = collections.Counter((BASE[i]["status"], arms[arm][i]) for i in ids)
        print("         ", {f"{a}->{b}": n for (a, b), n in sorted(flips.items()) if a != b})
print("\ntheo nhóm nguyên nhân, nhánh remind, câu nằm trong mẫu")
for bucket, ids in sorted(BUCKETS.items()):
    picked = [i for i in ids if i in arms["remind"]]
    if picked:
        print(f"  {bucket:42s} n={len(picked):3d} remind {line(picked, lambda i: arms['remind'][i])}  neutral {line(picked, lambda i: arms['neutral'][i])}")
