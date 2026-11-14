from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from .score import is_correct

VALUE_TYPES = frozenset({"number", "percent", "string", "date", "boolean", "list", "table"})
REQUIRED_LOG_FIELDS = ("id", "answer", "elapsed_ms", "thinking")
PRIVATE_QUESTIONS = 500
TIME_LIMIT_S = 6 * 3600


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_submission(questions: Sequence[str], rows: Sequence[dict[str, Any]]) -> list[str]:
    problems = []
    counts = Counter(str(row.get("id")) for row in rows)
    problems += [f"missing answer for {qid}" for qid in questions if qid not in counts]
    problems += [f"duplicate answer for {qid}" for qid, count in counts.items() if count > 1]
    problems += [f"answer for unknown id {qid}" for qid in counts if qid not in set(questions)]
    for row in rows:
        kind = row.get("type")
        if kind in VALUE_TYPES and "answer" not in row:
            problems.append(f"{row.get('id')}: type {kind} without answer")
        elif kind not in VALUE_TYPES | {"unanswerable", "abstain"}:
            problems.append(f"{row.get('id')}: unknown type {kind}")
    return problems


def check_logs(questions: Sequence[str], records: Sequence[dict[str, Any]]) -> list[str]:
    problems = []
    seen = Counter(str(record.get("id")) for record in records)
    problems += [f"no log record for {qid}" for qid in questions if qid not in seen]
    for record in records:
        missing = [field for field in REQUIRED_LOG_FIELDS if field not in record]
        if missing:
            problems.append(f"{record.get('id')}: log misses {missing}")
        elapsed = record.get("elapsed_ms")
        if not isinstance(elapsed, int) or elapsed < 0:
            problems.append(f"{record.get('id')}: elapsed_ms must be a non-negative integer, got {elapsed!r}")
        thinking = record.get("thinking")
        if thinking is not None and not (isinstance(thinking, list) and all(isinstance(text, str) for text in thinking)):
            problems.append(f"{record.get('id')}: thinking must be null or a list of strings")
        if record.get("code") is not None and "output" not in record:
            problems.append(f"{record.get('id')}: code without output")
    return problems


def pa(rows: Sequence[dict[str, Any]], gold: dict[str, dict[str, Any]]) -> float:
    verdicts = Counter("blank" if row.get("type") == "abstain" else "ok" if is_correct(row, gold[row["id"]]) else "wrong" for row in rows if row.get("id") in gold)
    return (verdicts["ok"] - verdicts["wrong"]) / len(gold)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kiểm một lần chạy predict.sh theo mục 10 của Docker guideline: đủ câu, định dạng, log, thời gian, độ lặp lại giữa hai lần chạy")
    parser.add_argument("--data", type=Path, required=True, help="thư mục test đã chạy, có questions.jsonl")
    parser.add_argument("--result", type=Path, required=True, help="thư mục /result của lần chạy")
    parser.add_argument("--other", type=Path, default=None, help="thư mục /result của lần chạy thứ hai trên cùng dữ liệu")
    parser.add_argument("--gold", type=Path, default=None, help="answers.jsonl (tập train) để tính PA")
    parser.add_argument("--wall-seconds", type=float, default=None, help="tổng thời gian lần chạy, gồm nạp model")
    parser.add_argument("--load-seconds", type=float, default=0.0, help="thời gian nạp model trong tổng trên")
    args = parser.parse_args(argv)
    questions = [str(row["id"]) for row in _rows(args.data / "questions.jsonl")]
    rows = _rows(args.result / "submission.jsonl")
    records = _rows(args.result / "logs" / "logs.jsonl")
    problems = check_submission(questions, rows) + check_logs(questions, records)
    print(f"câu hỏi {len(questions)}, dòng nộp {len(rows)}, bản ghi log {len(records)}, loại đáp án {dict(Counter(row.get('type') for row in rows))}")
    elapsed = [record["elapsed_ms"] for record in records if isinstance(record.get("elapsed_ms"), int)]
    if elapsed:
        print(f"elapsed_ms mỗi câu: trung bình {sum(elapsed) / len(elapsed):.0f}, lớn nhất {max(elapsed)}")
    if args.wall_seconds is not None and questions:
        per_question = (args.wall_seconds - args.load_seconds) / len(questions)
        projected = args.load_seconds + per_question * PRIVATE_QUESTIONS
        print(f"ước lượng {PRIVATE_QUESTIONS} câu: {projected / 3600:.2f} giờ ({'trong' if projected <= TIME_LIMIT_S else 'VƯỢT'} giới hạn 6 giờ)")
    gold = {str(row["id"]): row for row in _rows(args.gold)} if args.gold else None
    if gold is not None:
        print(f"PA lần chạy này: {pa(rows, {qid: gold[qid] for qid in questions if qid in gold}):+.3f}")
    if args.other is not None:
        other = {str(row["id"]): row for row in _rows(args.other / "submission.jsonl")}
        same = sum(row == other.get(str(row["id"])) for row in rows)
        print(f"hai lần chạy giống nhau {same}/{len(rows)} câu")
        if gold is not None:
            subset = {qid: gold[qid] for qid in questions if qid in gold}
            first, second = pa(rows, subset), pa(list(other.values()), subset)
            print(f"PA lần 2: {second:+.3f}, chênh {abs(first - second):.3f} ({'đạt' if abs(first - second) <= 0.03 else 'VƯỢT'} ngưỡng 0,03)")
    for problem in problems:
        print("LỖI", problem)
    print("OK" if not problems else f"{len(problems)} lỗi")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
