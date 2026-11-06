from __future__ import annotations

import collections
import glob
import json
import sys

EXP_DIR = sys.argv[1]
sys.argv = ["final_score", "experiments/EXP-20261105-07-domain-helpers"]
source = open("experiments/EXP-20261105-07-domain-helpers/code/final_score.py", encoding="utf-8").read().split("st = {i:")[0]
exec(source)

def runs(split: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(glob.glob(f"{EXP_DIR}/run/{split}/*/answers.jsonl")) + sorted(glob.glob(f"{EXP_DIR}/run/{split}_retry/*/answers.jsonl")):
        for raw in open(path, encoding="utf-8"):
            row = json.loads(raw)
            if row.get("type") is not None:
                out[row["id"]] = row
    return out

def report(name: str, old: dict, new: dict, gold: dict, questions: dict, entity: bool) -> dict:
    merged = {**old, **new}
    before = {i: status(old.get(i), gold[i], questions[i]["business_id"], entity) for i in questions}
    after = {i: status(merged.get(i), gold[i], questions[i]["business_id"], entity) for i in questions}
    print(f"{name} trước", line(list(before.values())))
    print(f"{name} sau  ", line(list(after.values())))
    print(f"{name} chạy lại có đáp án {len(new)}; thành đúng {sum(before[i] != 'ok' and after[i] == 'ok' for i in questions)}; từ đúng thành sai/trống {sum(before[i] == 'ok' and after[i] != 'ok' for i in questions)}")
    for i in questions:
        if before[i] == "ok" and after[i] != "ok":
            print("   LOST", i, questions[i]["business_id"], questions[i]["question"][:80], json.dumps(merged.get(i), ensure_ascii=False)[:120])
    return merged

public = report("public", load("experiments/EXP-20261105-07-domain-helpers/out/submission.jsonl"), runs("public"), G, Q, True)
TQ = load("train/split/test_questions.jsonl")
TG = {i: row for i, row in load("train/answers.jsonl").items() if i in TQ}
TOLD = load("experiments/EXP-20261105-07-domain-helpers/out/answers_test.jsonl")
report("test", TOLD, runs("test"), TG, TQ, False)
with open(f"{EXP_DIR}/out/answers_public_merged.jsonl", "w", encoding="utf-8") as handle:
    for i in Q:
        handle.write(json.dumps(public.get(i, {"id": i, "type": "abstain"}), ensure_ascii=False) + "\n")
