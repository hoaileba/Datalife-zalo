from __future__ import annotations

import argparse
import contextvars
import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

EXPERIMENT = Path(__file__).resolve().parents[1]
ROOT = EXPERIMENT.parents[1]
SNAPSHOT = EXPERIMENT / "code/src"
INPUTS = EXPERIMENT / "code/inputs"
OUT = EXPERIMENT / "out"
LOGS = EXPERIMENT / "logs"
SEED = 20261103
PARALLEL = 5
PROMPT = "v10"
IDENTITY: contextvars.ContextVar[str | None] = contextvars.ContextVar("question_id", default=None)
LOCK = threading.Lock()
ORDER_CASES = ("q_08f075b54698", "q_0f7d15097a8c", "q_2927db159ea7", "q_3ef55d803554", "q_66ee0467ce9e", "q_856d8521b9ea", "q_95a45f58351b", "q_b3c75e9f2c97", "q_c76ae61c6092")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rows(path: Path) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if row}


def redact(text: str) -> str:
    base = os.environ.get("VLLM_BASE_URL", "")
    host = urlparse(base).hostname if base else None
    for value in (base, host, os.environ.get("VLLM_API_KEY", "")):
        if value and len(value) > 5:
            text = text.replace(value, "<connection-config>")
    return text


def event(name: str, **payload: Any) -> None:
    line = json.dumps({"at": timestamp(), "event": name, **payload}, ensure_ascii=False, default=str)
    with LOCK, (LOGS / "events.jsonl").open("a", encoding="utf-8") as sink:
        sink.write(redact(line) + "\n")


def step(number: int, action: str, result: str, next_step: str) -> None:
    with LOCK, (EXPERIMENT / "STEPS.md").open("a", encoding="utf-8") as sink:
        sink.write(f"\n## {timestamp()} — bước {number}/7\nĐã làm: {action}\nKết quả: {result}\nBước tiếp: {next_step}\n")


def setup() -> tuple[Any, Any, Any, Any]:
    if not (SNAPSHOT / "datamate_agent/question_normalize.py").exists():
        raise ValueError("source snapshot is missing")
    sys.path.insert(0, str(SNAPSHOT))
    os.environ["DATAMATE_NORM_ROOT"] = str(INPUTS / "norm")
    os.environ["PYTHONPATH"] = str(SNAPSHOT)
    os.environ["PYTHONWARNINGS"] = "ignore"
    from datamate_agent import agent, question_normalize, question_rewrite, submission

    return agent, question_normalize, question_rewrite, submission


def request_identity(messages: Sequence[dict[str, Any]]) -> str | None:
    return IDENTITY.get()


def logged_client(*, backend: str, model: str, seed: int) -> Callable[[Sequence[dict[str, Any]]], str]:
    import httpx
    import openai
    from datamate_agent import agent
    from datamate_agent.llm import openai_client

    if backend != "vllm":
        raise ValueError("this experiment only permits vllm")
    client = openai_client(backend=backend, timeout=agent.READ_TIMEOUT_S, max_retries=0)

    def complete(messages: Sequence[dict[str, Any]]) -> str:
        question_id = request_identity(messages)
        prompt_json = json.dumps(tuple(messages), ensure_ascii=False, sort_keys=True)
        prompt_hash = digest(prompt_json)
        for attempt in range(agent.RATE_LIMIT_TRIES):
            started = time.monotonic()
            parts: list[str] = []
            usage = None
            event("model_request", id=question_id, model=model, seed=seed, attempt=attempt, prompt_hash=prompt_hash, messages=messages)
            try:
                with client.chat.completions.create(model=model, messages=list(messages), temperature=0, seed=seed, stream=True, stream_options={"include_usage": True}) as stream:
                    for chunk in stream:
                        if chunk.usage is not None:
                            usage = chunk.usage.model_dump()
                        if chunk.choices and chunk.choices[0].delta.content:
                            parts.append(chunk.choices[0].delta.content)
                        if time.monotonic() - started > agent.REPLY_DEADLINE_S:
                            raise ValueError(f"reply exceeded {agent.REPLY_DEADLINE_S}s after {sum(map(len, parts))} chars")
                reply = "".join(parts)
                event("model_response", id=question_id, model=model, attempt=attempt, prompt_hash=prompt_hash, seconds=time.monotonic() - started, usage=usage, usage_status="available" if usage is not None else "unavailable", reply=reply)
                return reply
            except (openai.OpenAIError, httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
                event("model_error", id=question_id, model=model, attempt=attempt, prompt_hash=prompt_hash, seconds=time.monotonic() - started, usage=usage, partial_reply="".join(parts), error_type=type(error).__name__, error=redact(str(error)))
                retryable = isinstance(error, (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError, json.JSONDecodeError, httpx.TransportError))
                if not retryable or attempt == agent.RATE_LIMIT_TRIES - 1:
                    raise ValueError(redact(f"{type(error).__name__}: {error}")) from None
                time.sleep(agent.RATE_LIMIT_WAIT_S)
        raise ValueError("no completion attempt was made")

    return complete


def instrument(agent: Any, normalizer: Any) -> None:
    agent.llm_client = logged_client
    original = normalizer.normalize_question
    original_hints = agent.user_hints
    original_solve = agent.solve

    def normalize_logged(question: dict[str, Any], **kwargs: Any) -> Any:
        token = IDENTITY.set(str(question["id"]))
        try:
            result = original(question, **kwargs)
            state = "rejected" if result.problem is not None else "unchanged" if result.rewritten == result.original else "accepted"
            event("normalization_decision", id=question["id"], status=state, result=result.model_dump())
            return result
        finally:
            IDENTITY.reset(token)

    normalizer.normalize_question = normalize_logged

    def hints_logged(question: dict[str, Any], **kwargs: Any) -> str:
        token = IDENTITY.set(str(question["id"]))
        try:
            return original_hints(question, **kwargs)
        finally:
            IDENTITY.reset(token)

    def solve_logged(*, question: dict[str, Any], **kwargs: Any) -> Any:
        token = IDENTITY.set(str(question["id"]))
        started = time.monotonic()
        try:
            result = original_solve(question=question, **kwargs)
            event("question_result", id=question["id"], seconds=time.monotonic() - started, result=result)
            return result
        finally:
            IDENTITY.reset(token)

    agent.user_hints = hints_logged
    agent.solve = solve_logged


def check_server() -> None:
    from datamate_agent.llm import openai_client, resolve_model

    model = resolve_model(backend="vllm", model=None)
    if model != "gemma-12b":
        raise ValueError("expected VLLM_MODEL gemma-12b for this experiment")
    client = openai_client(backend="vllm", timeout=30, max_retries=0)
    available = tuple(item.id for item in client.models.list().data)
    event("server_models", model=model, available=available)
    if model not in available:
        raise ValueError("configured model is not in server model inventory")
    print(json.dumps({"event": "server_ready", "model": model, "available_models": available}, ensure_ascii=False), flush=True)


def preprocess(module: Any, *, questions: Path, out: Path) -> None:
    module.main(["--backend", "vllm", "--dataset", str(ROOT / "public_test"), "--questions", str(questions), "--parallel", str(PARALLEL), "--seed", str(SEED), "--mode", "normalize", "--out", str(out)])


def solve(agent: Any, *, questions: Path, analysis: Path, out: Path) -> Path:
    agent.main(["--backend", "vllm", "--dataset", str(ROOT / "public_test"), "--questions", str(questions), "--parallel", str(PARALLEL), "--seed", str(SEED), "--prompt", PROMPT, "--rewrites", str(analysis), "--out", str(out)])
    found = sorted(folder for folder in out.iterdir() if folder.is_dir())
    return found[-1] / "answers.jsonl"


def smoke(agent: Any, normalizer: Any, rewrite: Any) -> None:
    from datamate_agent.llm import resolve_model

    model = resolve_model(backend="vllm", model=None)
    complete = logged_client(backend="vllm", model=model, seed=SEED)
    synthetic = (
        {"id": "smoke-orders", "question": "Hnay tổng bnhiu đh z?", "as_of_date": "2026-11-09"},
        {"id": "smoke-subtract", "question": "Tháng 5/2026 nhập trừ bán bnhiu cái?", "as_of_date": "2026-11-09"},
        {"id": "smoke-name", "question": "bnhiu Bánh mì Sao Mai bán được hôm qua?", "as_of_date": "2026-11-09"},
    )
    outputs = tuple(normalizer.normalize_question(row, names=("Bánh mì Sao Mai",) if row["id"] == "smoke-name" else (), complete=complete, model=model) for row in synthetic)
    (OUT / "smoke_synthetic.jsonl").write_text("".join(row.model_dump_json() + "\n" for row in outputs), encoding="utf-8")
    if all(row.problem is not None for row in outputs):
        raise ValueError("all synthetic normalization smoke outputs were rejected")
    first = next(iter(rows(INPUTS / "questions.jsonl").values()))
    questions = OUT / "smoke_questions.jsonl"
    questions.write_text(json.dumps(first, ensure_ascii=False) + "\n", encoding="utf-8")
    preprocess(rewrite, questions=questions, out=OUT / "smoke_analysis.jsonl")
    answers = solve(agent, questions=questions, analysis=OUT / "smoke_analysis.jsonl", out=OUT / "smoke_runs")
    event("smoke_complete", synthetic_ids=tuple(row["id"] for row in synthetic), public_ids=(first["id"],), answers=str(answers.relative_to(EXPERIMENT)), scored=False)
    step(4, "chạy smoke synthetic và một câu public không chấm gold", "cache/agent có output; không chọn prompt bằng điểm smoke", "full 1000 câu mới từ đầu, không ghép đáp án smoke")


def score() -> dict[str, Any]:
    questions, reference, baseline, submitted = (rows(path) for path in (INPUTS / "questions.jsonl", INPUTS / "reference.jsonl", INPUTS / "baseline_submission.jsonl", OUT / "submission.jsonl"))
    if set(submitted) != set(questions):
        raise ValueError("submission does not cover exactly 1000 question ids")
    namespace: dict[str, Any] = {"NORM_PATH": INPUTS / "norm/public_test"}
    previous = sys.argv
    try:
        sys.argv = ["score", "unused"]
        exec(compile((INPUTS / "score_prefix.py").read_text(encoding="utf-8"), "frozen_score_prefix", "exec"), namespace)
    finally:
        sys.argv = previous
    status = namespace["status"]
    verdicts = {qid: status(submitted[qid], reference[qid], question["business_id"], True) for qid, question in questions.items()}
    strict = {qid: status(submitted[qid], reference[qid], question["business_id"], False) for qid, question in questions.items()}
    old = {qid: status(baseline[qid], reference[qid], question["business_id"], True) for qid, question in questions.items()}
    count, count_strict = Counter(verdicts.values()), Counter(strict.values())
    rewrites = rows(OUT / "analysis_normalize.jsonl")
    norm_counts = Counter("api_errors" if str(row.get("problem", "")).startswith("api error:") else "rejected" if row.get("problem") is not None else "unchanged" if row.get("rewritten") == row["original"] else "accepted" for row in rewrites.values())
    run = sorted(folder for folder in (OUT / "agent_runs").iterdir() if folder.is_dir())[-1]
    api = sum("LỖI API" in path.read_text(encoding="utf-8") for path in run.glob("q_*.log"))
    subgroup = Counter(verdicts[qid] for qid in ORDER_CASES)
    timing = json.loads((OUT / "timing.json").read_text(encoding="utf-8"))
    metrics = {
        "score_lenient": (count["ok"] - count["wrong"]) / len(questions),
        "accuracy_lenient": count["ok"] / max(count["ok"] + count["wrong"], 1),
        "coverage_lenient": (count["ok"] + count["wrong"]) / len(questions),
        "right_lenient": count["ok"], "wrong_lenient": count["wrong"], "blank_lenient": count["blank"],
        "score_strict": (count_strict["ok"] - count_strict["wrong"]) / len(questions),
        "accuracy_strict": count_strict["ok"] / max(count_strict["ok"] + count_strict["wrong"], 1),
        "coverage_strict": (count_strict["ok"] + count_strict["wrong"]) / len(questions),
        "right_strict": count_strict["ok"], "wrong_strict": count_strict["wrong"], "blank_strict": count_strict["blank"],
        "normalization_accepted": norm_counts["accepted"], "normalization_rejected": norm_counts["rejected"], "normalization_unchanged": norm_counts["unchanged"], "normalization_api_errors": norm_counts["api_errors"],
        "agent_api_errors": api, "normalization_seconds": timing["normalization_seconds"], "agent_seconds": timing["agent_seconds"], "total_seconds": timing["total_seconds"],
        "gained_vs_parent": sum(old[qid] != "ok" and verdicts[qid] == "ok" for qid in questions),
        "lost_vs_parent": sum(old[qid] == "ok" and verdicts[qid] != "ok" for qid in questions),
        "delta_score_vs_parent": ((count["ok"] - count["wrong"]) - (Counter(old.values())["ok"] - Counter(old.values())["wrong"])) / len(questions),
        "order_count_9_right": subgroup["ok"], "order_count_9_wrong": subgroup["wrong"], "order_count_9_blank": subgroup["blank"],
    }
    manifest = json.loads((EXPERIMENT / "manifest.json").read_text(encoding="utf-8"))
    if set(metrics) != set(manifest["metrics"]):
        raise ValueError("computed metrics differ from preregistration")
    (OUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    flips = tuple({"id": qid, "question": questions[qid], "baseline_verdict": old[qid], "variant_verdict": verdicts[qid], "submitted": submitted[qid], "baseline": baseline[qid], "reference": reference[qid], "normalization": rewrites[qid]} for qid in questions if old[qid] != verdicts[qid])
    (OUT / "changed_cases.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in flips), encoding="utf-8")
    (OUT / "verdicts.jsonl").write_text("".join(json.dumps({"id": qid, "lenient": verdicts[qid], "strict": strict[qid], "baseline": old[qid]}) + "\n" for qid in questions), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
    event("scored", metrics=metrics)
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("check", "smoke", "full", "score"))
    args = parser.parse_args()
    os.chdir(ROOT)
    agent, normalizer, rewrite, submission = setup()
    instrument(agent, normalizer)
    if args.stage == "check":
        check_server()
        return 0
    if args.stage == "smoke":
        check_server()
        smoke(agent, normalizer, rewrite)
        return 0
    if args.stage == "score":
        score()
        return 0
    check_server()
    started = time.monotonic()
    step(5, "bắt đầu full normalization trên 1000 câu", "snapshot cố định; không tái dùng output smoke", "agent 1000 câu sau normalization")
    preprocess(rewrite, questions=INPUTS / "questions.jsonl", out=OUT / "analysis_normalize.jsonl")
    normalized = time.monotonic()
    step(5, "hoàn tất normalization 1000 câu", f"thời gian {normalized - started:.3f}s; output out/analysis_normalize.jsonl", "agent full 1000 từ snapshot")
    answers = solve(agent, questions=INPUTS / "questions.jsonl", analysis=OUT / "analysis_normalize.jsonl", out=OUT / "agent_runs")
    solved = time.monotonic()
    submission.build_submission(answers, INPUTS / "questions.jsonl", OUT / "submission.jsonl")
    timing = {"normalization_seconds": normalized - started, "agent_seconds": solved - normalized, "total_seconds": time.monotonic() - started}
    (OUT / "timing.json").write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")
    step(6, "hoàn tất agent và gom submission", "1000 câu đã đi qua luồng mới; chưa kết luận hiệu quả trước chấm", "chấm strict/lenient, đối chiếu gained/lost và đóng thực nghiệm")
    score()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        event("runner_failed", error_type=type(error).__name__, error=redact(str(error)))
        print(json.dumps({"event": "runner_failed", "error_type": type(error).__name__, "error": redact(str(error))}, ensure_ascii=False), flush=True)
        raise SystemExit(1) from None
