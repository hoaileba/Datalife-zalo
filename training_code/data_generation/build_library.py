from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Sequence

ORACLE_WORKERS = 5


def _run(module: str, *arguments: str) -> None:
    subprocess.run([sys.executable, "-W", "ignore", "-m", module, *arguments], check=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dựng lại thư viện ví dụ src/datamate_agent/prompts/library.jsonl từ dữ liệu train: chuẩn hoá bảng, oracle sinh code theo mẫu câu trên cả 3000 câu, giữ câu train_* khớp gold, thêm ví dụ agent đã khớp gold, gắn shop")
    parser.add_argument("--train", type=Path, required=True, help="thư mục train được cấp: questions.jsonl, calendar.csv, rulebook.md, data/, split/")
    parser.add_argument("--agent-examples", type=Path, required=True, help="library_agent.jsonl")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected", type=Path, default=None, help="thư viện đang dùng khi chạy, để so SHA-256")
    args = parser.parse_args(argv)
    train = args.train.resolve()
    norm = args.work / "norm" / train.name
    oracle_out = args.work / "oracle_train.jsonl"
    args.work.mkdir(parents=True, exist_ok=True)
    _run("datamate_agent.prepare", "--dataset", str(train), "--out", str(norm))
    _run("datamate_agent.oracle", "--questions", str(train / "questions.jsonl"), "--answers", str(train / "answers.jsonl"), "--root", str(norm), "--calendar", str(train / "calendar.csv"), "--out", str(oracle_out), "--workers", str(ORACLE_WORKERS))
    train_ids = {json.loads(line)["id"] for line in (train / "split/train_questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    examples: dict[tuple[str, str], dict[str, object]] = {}
    for line in oracle_out.read_text(encoding="utf-8").splitlines():
        row = json.loads(line) if line.strip() else None
        if row and row["id"] in train_ids and row["ok"] and row["code"]:
            examples.setdefault((row["masked"], row["intent"]), {"question": row["question"], "masked": row["masked"], "answer_type": row["kind"], "code": row["code"], "intent": row["intent"], "requires": None})
    shops: dict[str, set[str]] = defaultdict(set)
    for line in (train / "questions.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            shops[row["question"]].add(row["business_id"])
    rows = list(examples.values()) + [json.loads(line) for line in args.agent_examples.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        row["shops"] = sorted(shops[row["question"]])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    digest = _sha256(args.out)
    print(f"library {len(rows)} examples, sha256 {digest}")
    if args.expected is not None:
        expected = _sha256(args.expected)
        if digest != expected:
            raise ValueError(f"rebuilt library differs from {args.expected}: {digest} != {expected}")
        print(f"matches {args.expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
