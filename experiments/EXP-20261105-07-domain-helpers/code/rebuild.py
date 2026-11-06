from __future__ import annotations

import glob
import json
import os
import re
import sys


def finals(folder: str) -> dict[str, dict]:
    out = {}
    for path in glob.glob(f"{folder}/q_*.log"):
        found = re.search(r"^FINAL:\n(.*)$", open(path, encoding="utf-8").read(), flags=re.M)
        if found and found.group(1).strip() != "null":
            out[os.path.basename(path)[:-4]] = json.loads(found.group(1))
    return out


E = sys.argv[1]
for name, source in (("public", "public_test/questions.jsonl"), ("test", "train/split/test_questions.jsonl")):
    folders = sorted(os.path.dirname(path) for path in glob.glob(f"{E}/run/{name}/*/answers.jsonl"))
    merged: dict[str, dict] = {}
    for folder in folders:
        merged.update(finals(folder))
    ids = [json.loads(line)["id"] for line in open(source, encoding="utf-8") if line.strip()]
    missing = [i for i in ids if i not in merged]
    with open(f"{E}/out/answers_{name}.jsonl", "w", encoding="utf-8") as out:
        for i in ids:
            out.write(json.dumps(merged.get(i, {"id": i, "type": None, "answer": None}), ensure_ascii=False) + "\n")
    print(name, "folders", len(folders), "có FINAL", len(merged), "thiếu", missing)
    open(f"{E}/out/missing_{name}.txt", "w").write(" ".join(missing))
