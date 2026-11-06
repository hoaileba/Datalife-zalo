from __future__ import annotations

import json
import random
import sys
from collections import defaultdict

out = sys.argv[1]
questions = [json.loads(line) for line in open("train/questions.jsonl", encoding="utf-8") if line.strip()]
answers = {json.loads(line)["id"]: json.loads(line) for line in open("train/answers.jsonl", encoding="utf-8") if line.strip()}
rng = random.Random(20261105)
groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
for row in questions:
    groups[(row["business_id"], answers[row["id"]]["type"])].append(row)
ordered = []
for key in sorted(groups):
    rows = groups[key]
    rng.shuffle(rows)
    ordered.extend(rows)
folds: list[list[dict]] = [[] for _ in range(5)]
for index, row in enumerate(ordered):
    folds[index % 5].append(row)
for number, rows in enumerate(folds, start=1):
    rng.shuffle(rows)
    with open(f"{out}/fold_{number}.jsonl", "w", encoding="utf-8") as handle:
        handle.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    print(number, len(rows), len({row["id"] for row in rows}), len({row["business_id"] for row in rows}))
