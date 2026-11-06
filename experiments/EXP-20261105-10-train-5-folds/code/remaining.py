from __future__ import annotations

import glob
import json
import os
import re
import sys

E, number = sys.argv[1], sys.argv[2]
SOURCES = (f"{E}/run/*/*", "experiments/EXP-20261105-09-train-3000-coverage/run/*", "experiments/EXP-20261105-08-train-sample-200/run/*", "experiments/EXP-20261105-07-domain-helpers/run/test/*")
done = set()
for pattern in SOURCES:
    for folder in glob.glob(pattern):
        for path in glob.glob(f"{folder}/q_*.log"):
            found = re.search(r"^FINAL:\n(.*)$", open(path, encoding="utf-8").read(), flags=re.M)
            if found and found.group(1).strip() != "null":
                done.add(os.path.basename(path)[:-4])
rows = [line for line in open(f"{E}/inputs/fold_{number}.jsonl", encoding="utf-8") if json.loads(line)["id"] not in done]
open(f"{E}/inputs/todo_{number}.jsonl", "w", encoding="utf-8").writelines(rows)
print(number, "còn chạy", len(rows))
