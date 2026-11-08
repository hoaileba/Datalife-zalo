from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Sequence

from .llm import BACKENDS

DEFAULT_PROMPT = "v10"
DEFAULT_PARALLEL = 4


def _latest_run(folder: Path) -> Path:
    runs = sorted(path for path in folder.iterdir() if path.is_dir())
    if not runs:
        raise ValueError(f"agent wrote no run under {folder}")
    return runs[-1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chuẩn hoá dữ liệu shop, phân tích câu hỏi, chạy agent, gom file nộp; dataset chỉ đọc, mọi thứ ghi vào --work")
    parser.add_argument("--dataset", type=Path, required=True, help="thư mục có questions.jsonl, calendar.csv, data/<shop>/")
    parser.add_argument("--work", type=Path, required=True, help="thư mục ghi được")
    parser.add_argument("--out", type=Path, required=True, help="đường dẫn file nộp")
    parser.add_argument("--backend", choices=sorted(BACKENDS), default=os.environ.get("LLM_BACKEND"), required=os.environ.get("LLM_BACKEND") is None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    args = parser.parse_args(argv)
    dataset = args.dataset.resolve()
    questions = dataset / "questions.jsonl"
    if not questions.exists():
        raise ValueError(f"no questions.jsonl in {dataset}")
    norm_root = (args.work / "norm").resolve()
    os.environ["DATAMATE_NORM_ROOT"] = str(norm_root)

    from . import agent, prepare, question_rewrite, submission

    model = ["--model", args.model] if args.model else []
    started = time.monotonic()
    prepare.main(["--dataset", str(dataset), "--out", str(norm_root / dataset.name)])
    print(f"prepare xong sau {time.monotonic() - started:.0f}s", flush=True)
    analysis = args.work / "analysis.jsonl"
    question_rewrite.main(["--backend", args.backend, *model, "--dataset", str(dataset), "--questions", str(questions), "--parallel", str(args.parallel), "--out", str(analysis)])
    print(f"phân tích câu hỏi xong sau {time.monotonic() - started:.0f}s", flush=True)
    runs = args.work / "runs"
    agent.main(["--backend", args.backend, *model, "--dataset", str(dataset), "--prompt", args.prompt, "--rewrites", str(analysis), "--parallel", str(args.parallel), "--out", str(runs)])
    print(f"agent xong sau {time.monotonic() - started:.0f}s", flush=True)
    changes = submission.build_submission(_latest_run(runs) / "answers.jsonl", questions, args.out)
    print(f"file nộp {args.out}, {dict(changes)}, tổng {time.monotonic() - started:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
