from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Sequence

from .llm import BACKENDS

DEFAULT_PROMPT = "v10"
DEFAULT_PARALLEL = 4
DEFAULT_SEED = 20261103
QUESTION_MODES = ("rewrite", "normalize")


class QuestionRun:
    """Mọi lời gọi LLM và lần chạy code của một câu hỏi, theo đúng thứ tự đã xảy ra, để ghi log thật."""

    def __init__(self, *, complete: Callable[[Sequence[dict[str, Any]]], str]) -> None:
        self._complete = complete
        self.replies: list[str] = []
        self.executions: list[tuple[str, Any]] = []

    def complete(self, messages: Sequence[dict[str, Any]]) -> str:
        reply = self._complete(messages)
        self.replies.append(reply)
        return reply

    def wrap_runner(self, runner: Callable[[str], Any]) -> Callable[[str], Any]:
        def run(code: str) -> Any:
            result = runner(code)
            self.executions.append((code, result))
            return result

        return run


def _last_output(result: Any) -> str | None:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if lines:
        return lines[-1].strip()
    return result.stderr.strip().splitlines()[-1] if result.stderr.strip() else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chuẩn hoá dữ liệu shop rồi trả lời từng câu (phân tích câu hỏi, agent); mỗi câu xong ghi ngay file nộp và log. Dataset chỉ đọc, file tạm ghi vào --work")
    parser.add_argument("--dataset", type=Path, required=True, help="thư mục có questions.jsonl, calendar.csv, rulebook.md, data/<shop>/")
    parser.add_argument("--work", type=Path, required=True, help="thư mục ghi được cho file tạm")
    parser.add_argument("--out", type=Path, required=True, help="đường dẫn file nộp")
    parser.add_argument("--log-dir", type=Path, default=None, help="mặc định <thư mục của --out>/logs")
    parser.add_argument("--backend", choices=sorted(BACKENDS), default=os.environ.get("LLM_BACKEND"), required=os.environ.get("LLM_BACKEND") is None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--question-mode", choices=QUESTION_MODES, default="rewrite")
    args = parser.parse_args(argv)
    dataset = args.dataset.resolve()
    questions_path = dataset / "questions.jsonl"
    if not questions_path.exists():
        raise ValueError(f"no questions.jsonl in {dataset}")
    norm_root = (args.work / "norm").resolve()
    os.environ["DATAMATE_NORM_ROOT"] = str(norm_root)

    import httpx
    import openai

    from datamate.shop import Shop

    from . import agent, prepare, submission
    from .fewshot import entities_of, linked_names
    from .llm import resolve_model
    from .question_rewrite import Rewrite, rewrite

    started = time.monotonic()
    log_dir = args.log_dir or args.out.parent / "logs"
    trace_dir = log_dir / "trace"
    runs_dir = args.work / "runs"
    for folder in (args.out.parent, trace_dir, runs_dir):
        folder.mkdir(parents=True, exist_ok=True)
    prepare.main(["--dataset", str(dataset), "--out", str(norm_root / dataset.name)])
    print(f"prepare xong sau {time.monotonic() - started:.0f}s", flush=True)

    model = resolve_model(backend=args.backend, model=args.model)
    complete = agent.llm_client(backend=args.backend, model=model, seed=args.seed)
    questions = [json.loads(line) for line in questions_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    calendar = dataset / "calendar.csv"
    entity_cache: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    entity_lock = threading.Lock()

    def entities(shop: str, as_of: str) -> dict[str, dict[str, str]]:
        with entity_lock:
            if (shop, as_of) not in entity_cache:
                entity_cache[shop, as_of] = entities_of(Shop(norm_root / dataset.name / shop, as_of=as_of, calendar=str(calendar)))
            return entity_cache[shop, as_of]

    def analyse(question: dict[str, Any], run: QuestionRun) -> Rewrite:
        names = linked_names(str(question["question"]), entities(str(question["business_id"]), str(question["as_of_date"])))
        try:
            if args.question_mode == "normalize":
                from .question_normalize import normalize_question

                return normalize_question(question, names=names, complete=run.complete, model=model)
            return rewrite(question, names=names, complete=run.complete, model=model)
        except (openai.OpenAIError, httpx.HTTPError, ValueError) as error:
            return Rewrite(id=str(question["id"]), original=str(question["question"]), rewritten=None, problem=f"api error: {type(error).__name__}: {str(error)[:120]}", model=model)

    def answer(question: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
        begun = time.monotonic()
        run = QuestionRun(complete=complete)
        shop = str(question["business_id"])
        analysis = analyse(question, run)
        enriched = question | ({"rewritten": analysis.rewritten, "shape": analysis.shape, "count": analysis.count, "needs": list(analysis.needs)} if analysis.problem is None else {})
        norm_dir = (norm_root / dataset.name / shop).resolve()
        work_dir = agent.prepare_workspace(runs_dir / str(question["id"]), raw_dir=(dataset / "data" / shop).resolve(), norm_dir=norm_dir, calendar=calendar)
        run_code = run.wrap_runner(agent.local_runner(work_dir.resolve(), as_of=str(question["as_of_date"])))
        error = None
        with (trace_dir / f"{question['id']}.log").open("w", encoding="utf-8") as log:
            system = agent.build_system(dataset=dataset, shop=shop, prompt=args.prompt, language="vi")
            try:
                hints = agent.user_hints(enriched, norm_dir=norm_dir, calendar=calendar, complete=run.complete)
                line = agent.solve(question=enriched, system=system, hints=hints, complete=run.complete, run_code=run_code, shop_dir=work_dir, log=log)
            except (openai.OpenAIError, httpx.HTTPError, ValueError, TypeError, AttributeError) as failure:
                line = None
                error = f"{type(failure).__name__}: {str(failure)[:200]}"
                log.write(f"{agent.SEPARATOR}\nFINAL:\nnull\nLỖI API: {error}\n")
        row, change = submission.submission_row(str(question["id"]), line)
        last = run.executions[-1] if run.executions else None
        record = {
            "id": question["id"],
            "answer": {key: value for key, value in row.items() if key != "id"},
            "elapsed_ms": int((time.monotonic() - begun) * 1000),
            "thinking": list(run.replies) or None,
            "code": last[0] if last else None,
            "output": _last_output(last[1]) if last else None,
            "code_runs": len(run.executions),
            "question_analysis": analysis.model_dump(),
            "submission_change": change,
            "error": error,
            "trace": f"trace/{question['id']}.log",
        }
        return row, line, record

    write_lock = threading.Lock()
    answered: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=args.parallel) as pool, args.out.open("w", encoding="utf-8") as sink, (log_dir / "logs.jsonl").open("w", encoding="utf-8") as logs:
        futures = {pool.submit(answer, question): question for question in questions}
        for future in as_completed(futures):
            row, _, record = future.result()
            with write_lock:
                answered[str(row["id"])] = row
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
                logs.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                logs.flush()
            print(f"{len(answered)}/{len(questions)} {row['id']} {row['type']} {record['elapsed_ms']}ms", flush=True)
    ordered = [answered.get(str(question["id"])) or submission.submission_row(str(question["id"]), None)[0] for question in questions]
    staged = args.out.with_suffix(".tmp")
    staged.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ordered), encoding="utf-8")
    os.replace(staged, args.out)
    print(f"file nộp {args.out}: {len(ordered)} câu, tổng {time.monotonic() - started:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
