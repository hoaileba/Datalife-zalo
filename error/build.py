from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.argv = ["final_score", str(ROOT / "experiments/EXP-20261105-07-domain-helpers")]
exec((ROOT / "experiments/EXP-20261105-07-domain-helpers/code/final_score.py").read_text(encoding="utf-8").split("st = {i:")[0])

SUBMISSION = Path(__file__).parent / "answers_public_current.jsonl"
LABELS = json.loads((Path(__file__).parent / "labels_public.json").read_text(encoding="utf-8"))
group_of = {qid: group for group, row in LABELS.items() for qid in row["ids"]}
answers = load(str(SUBMISSION))
statuses = {i: status(answers.get(i), G[i], Q[i]["business_id"], True) for i in Q}
rows = []
for i, state in statuses.items():
    if state == "ok":
        continue
    rows.append({"id": i, "shop": Q[i]["business_id"], "group": group_of.get(i, "?"), "status": state, "question": Q[i]["question"], "got": answers.get(i), "ref": G[i]})
(Path(__file__).parent / "public_errors.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
print(line(list(statuses.values())))
print("theo nhóm", sorted(collections.Counter(row["group"] for row in rows).items()))
print("theo shop", collections.Counter(row["shop"] for row in rows).most_common())
print("đã sửa (nhãn cũ nay đúng)", sorted(collections.Counter(group_of[i] for i, s in statuses.items() if s == "ok" and i in group_of).items()))
