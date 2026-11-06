from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from ..models import load_run_config
from ..modules.paths import WorkLayout
from ..modules.runlog import render_full_transcript
from .run import build_pipeline


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chạy harness cho đúng một câu hỏi, ghi toàn bộ input/output từng turn ra một file log")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--question", required=True, help="id câu hỏi trong questions_file của config")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--out", required=True, type=Path, help="thư mục chứa lần probe")
    parser.add_argument("--log", required=True, type=Path, help="file log ghi nối, vd test.log")
    parser.add_argument("--reference", type=Path, default=None, help="submission.jsonl để so đáp án")
    args = parser.parse_args(argv)
    base = load_run_config(args.config)
    question = _find(base.questions_path, args.question)
    probe_dir = args.out.resolve() / f"{args.question}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    probe_dir.mkdir(parents=True)
    question_file = probe_dir / "question.jsonl"
    question_file.write_text(json.dumps(question, ensure_ascii=False) + "\n", encoding="utf-8")
    config = base.model_copy(
        update={
            "run_id": f"probe-{args.question}",
            "questions_file": str(question_file),
            "truth_file": None,
            "output_dir": probe_dir / "run",
            "shops": (str(question["business_id"]),),
            "max_turns": args.max_turns,
        }
    )
    pipeline = build_pipeline(config, merge_only=False)
    state, _, _ = pipeline.run(merge_only=False)
    shop = str(question["business_id"])
    layout = WorkLayout(config.output_dir)
    answers = _by_id(layout.answers(shop)) if state.shops[shop].status == "verified" else {}
    reference = _by_id(args.reference).get(args.question) if args.reference is not None else None
    text = render_full_transcript(
        shop_log=pipeline.run_log.shop(shop),
        question=question,
        outcome=state.shops[shop],
        answer=answers.get(args.question),
        reference=reference,
    )
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return 0


def _find(path: Path, qid: str) -> dict[str, Any]:
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            row = json.loads(raw)
            if row["id"] == qid:
                return row
    raise ValueError(f"question not found: {qid}")


def _by_id(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = (json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip())
    return {row["id"]: row for row in rows}


if __name__ == "__main__":
    raise SystemExit(main())
