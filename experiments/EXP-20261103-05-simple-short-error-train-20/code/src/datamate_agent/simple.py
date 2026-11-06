from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Sequence, TextIO

from datamate import Clock, fmt

from .connectors import ChatClient, OpenRouterClient
from .models import ConnectorConfig, ExecResult, ModelConfig, RetryConfig
from .modules.prompts import render
from .modules.score import is_correct
from .utils.events import EventLog

PROMPT = Path(__file__).resolve().parent / "prompts" / "simple.md"
IMAGE = "datamate-sandbox:0.1"
OUTPUT_LIMIT = 4000
CODE_TIMEOUT_S = 120
AGGREGATIONS = ("sum", "count_rows", "count_distinct", "mean", "max", "min", "ratio", "other")
ANSWER_TYPES = ("number", "percent", "date", "boolean", "string", "list", "table", "unanswerable")
RUN_PYTHON = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": "Chạy code phân tích dữ liệu, trả về stdout và stderr.",
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
    },
}
CONCLUDE = {
    "type": "function",
    "function": {
        "name": "conclude",
        "description": "Đưa ra nhận định sau khi phân tích. ok=true thì sang bước viết code tính đáp án; ok=false thì phân tích tiếp.",
        "parameters": {
            "type": "object",
            "properties": {
                "findings": {"type": "string", "description": "đã thấy gì: giá trị thật, số dòng sau khi lọc"},
                "table": {"type": "string", "description": "file bảng chính trong clean/, vd sales.csv; null nếu unanswerable"},
                "period_start": {"type": "string", "description": "ngày đầu kỳ YYYY-MM-DD; null nếu câu hỏi không theo kỳ"},
                "period_end": {"type": "string", "description": "ngày cuối kỳ YYYY-MM-DD; null nếu câu hỏi không theo kỳ"},
                "measure_column": {"type": "string", "description": "cột được tính, vd line_amount, base_quantity; null nếu đếm dòng"},
                "aggregation": {"type": "string", "enum": list(AGGREGATIONS)},
                "logic": {"type": "string", "description": "lọc gì, công thức gì"},
                "answer_type": {"type": "string", "enum": list(ANSWER_TYPES)},
                "ok": {"type": "boolean", "description": "đã đủ để tính đáp án chưa"},
            },
            "required": ["findings", "logic", "aggregation", "answer_type", "ok"],
        },
    },
}
RUN_FINAL = {
    "type": "function",
    "function": {
        "name": "run_final",
        "description": "Chạy code hoàn chỉnh tính đáp án theo logic đã nhận định. Dòng cuối cùng code in ra chính là đáp án.",
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
    },
}
ANALYSIS_TOOLS: tuple[dict[str, Any], ...] = (RUN_PYTHON, CONCLUDE)
FINAL_TOOLS: tuple[dict[str, Any], ...] = (RUN_FINAL,)

CodeRunner = Callable[[str], ExecResult]


def docker_runner(*, clean_dir: Path, raw_dir: Path, calendar: Path) -> CodeRunner:
    command = [
        "docker", "run", "--rm", "-i", "--network", "none", "--memory", "4g", "--cpus", "2",
        "-v", f"{clean_dir.resolve()}:/shop/clean:ro", "-v", f"{raw_dir.resolve()}:/shop/raw:ro",
        "-v", f"{calendar.resolve()}:/shop/calendar.csv:ro", "-w", "/shop", IMAGE, "python", "-",
    ]

    def run(code: str) -> ExecResult:
        started = time.monotonic()
        try:
            done = subprocess.run(command, input=code, capture_output=True, text=True, timeout=CODE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return ExecResult(exit_code=None, stdout="", stderr="", timed_out=True, duration_s=round(time.monotonic() - started, 3))
        return ExecResult(exit_code=done.returncode, stdout=done.stdout, stderr=done.stderr, timed_out=False, duration_s=round(time.monotonic() - started, 3))

    return run


def tet_lines() -> str:
    clock = Clock("2026-01-01")
    lines = []
    for year in range(2024, 2028):
        try:
            lines.append(f"- Tết {year}: {clock.tet(year)}; trước Tết {year}: {clock.before_tet(year)}")
        except ValueError:
            continue
    return "\n".join(lines)


def system_prompt(*, rulebook: str, clean_dir: Path, raw_dir: Path, shop: str) -> str:
    profile = (clean_dir / "PROFILE.md").read_text(encoding="utf-8").replace(f"work/clean/{shop}/", "clean/")
    readme = (raw_dir / "README.md").read_text(encoding="utf-8")
    return render(PROMPT.read_text(encoding="utf-8"), {"rulebook": rulebook.strip(), "profile": profile.strip(), "readme": readme.strip(), "tet": tet_lines()})


class AnalysisLoop:
    """Một câu hỏi: phân tích bằng code → nhận định → sinh code theo logic → lấy đáp án từ output của code."""

    def __init__(self, *, question: dict[str, Any], run_code: CodeRunner, clean_dir: Path, log: TextIO) -> None:
        self._question = question
        self._run_code = run_code
        self._clean_dir = clean_dir
        self._log = log
        self._measure: str | None = None
        self._analyzed = False
        self._answer_type: str | None = None

    @property
    def tools(self) -> tuple[dict[str, Any], ...]:
        return ANALYSIS_TOOLS if self._answer_type is None else FINAL_TOOLS

    def call(self, name: str, raw: str) -> tuple[str, dict[str, Any] | None]:
        try:
            arguments = json.loads(raw or "{}")
        except json.JSONDecodeError as error:
            return f"ERROR: tham số không phải JSON: {error}", None
        if name not in {tool["function"]["name"] for tool in self.tools}:
            return f"ERROR: lúc này chỉ gọi được {[tool['function']['name'] for tool in self.tools]}", None
        if name == "run_python":
            return self._analyze(str(arguments.get("code", ""))), None
        if name == "conclude":
            return self._conclude(arguments)
        return self._final(str(arguments.get("code", "")))

    def _analyze(self, code: str) -> str:
        _write(self._log, f"PHÂN TÍCH\n{code}")
        result = self._run_code(code)
        self._log_stderr(result)
        self._analyzed = self._analyzed or (result.exit_code == 0 and bool(result.stdout.strip()))
        return _format_exec(result)

    def _log_stderr(self, result: ExecResult) -> None:
        if result.exit_code and result.stderr:
            _write(self._log, f"TRACEBACK (không gửi cho model)\n{result.stderr}")

    def _conclude(self, arguments: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        _write(self._log, f"NHẬN ĐỊNH {json.dumps(arguments, ensure_ascii=False, indent=2)}")
        answer_type = str(arguments.get("answer_type"))
        if answer_type not in ANSWER_TYPES:
            return f"ERROR: answer_type phải thuộc {list(ANSWER_TYPES)}", None
        if not self._analyzed:
            return "ERROR: chưa có lần chạy code phân tích nào in ra kết quả. Hãy gọi run_python trước.", None
        if not arguments.get("ok"):
            return "Chưa đủ. Phân tích tiếp bằng run_python.", None
        if answer_type == "unanswerable":
            return "", fmt.answer_line(str(self._question["id"]), "unanswerable", reason=str(arguments.get("findings", "")))
        problem = self._check_plan(arguments)
        if problem is not None:
            return f"ERROR: {problem}. Sửa rồi gọi lại conclude.", None
        self._answer_type = answer_type
        self._measure = _optional(arguments.get("measure_column"))
        return f"Đã ghi nhận định. Giờ gọi run_final với code hoàn chỉnh theo đúng logic đó; dòng cuối cùng in ra đáp án kiểu {answer_type}, chỉ giá trị, không kèm chữ.", None

    def _check_plan(self, arguments: dict[str, Any]) -> str | None:
        tables = sorted(path.name for path in self._clean_dir.glob("*.csv") if not path.name.endswith(".dropped.csv"))
        table = _optional(arguments.get("table"))
        if table is None or Path(table).name not in tables:
            return f"table {table!r} không có; các bảng: {tables}"
        for field in ("period_start", "period_end"):
            value = _optional(arguments.get(field))
            if value is not None:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    return f"{field} {value!r} phải có dạng YYYY-MM-DD hoặc null"
        if str(arguments.get("aggregation")) not in AGGREGATIONS:
            return f"aggregation phải thuộc {list(AGGREGATIONS)}"
        measure = _optional(arguments.get("measure_column"))
        columns = (self._clean_dir / Path(table).name).open(encoding="utf-8").readline().strip().split(",")
        if measure is not None and measure not in columns:
            return f"measure_column {measure!r} không có trong {table}; các cột: {columns}"
        return None

    def _final(self, code: str) -> tuple[str, dict[str, Any] | None]:
        _write(self._log, f"CODE CUỐI\n{code}")
        if self._measure is not None and self._measure not in code:
            return f"ERROR: code không dùng cột {self._measure!r} như đã nhận định. Viết lại đúng logic.", None
        result = self._run_code(code)
        self._log_stderr(result)
        if result.exit_code != 0:
            return f"ERROR: code lỗi, sửa rồi gọi lại run_final.\n{_format_exec(result)}", None
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return "ERROR: code không in gì. Dòng cuối cùng phải print đáp án.", None
        _write(self._log, f"OUTPUT\n{_format_exec(result)}")
        try:
            value = _parse_value(lines[-1].strip(), str(self._answer_type))
            return "", fmt.answer_line(str(self._question["id"]), str(self._answer_type), value)
        except (ValueError, TypeError, SyntaxError) as error:
            return f"ERROR: dòng cuối {lines[-1]!r} không phải đáp án kiểu {self._answer_type}: {error}. Sửa code rồi gọi lại run_final.", None


def solve(
    *,
    question: dict[str, Any],
    system: str,
    client: ChatClient,
    run_code: CodeRunner,
    clean_dir: Path,
    max_turns: int,
    log: TextIO,
    conversation: Path | None = None,
) -> dict[str, Any] | None:
    user = f"Hôm nay là {question['as_of_date']}.\nCâu hỏi: {question['question']}"
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    loop = AnalysisLoop(question=question, run_code=run_code, clean_dir=clean_dir, log=log)
    _write(log, f"=== {question['id']} · {question['business_id']} · {user}")
    for turn in range(1, max_turns + 1):
        _save_conversation(conversation, messages)
        reply = client.complete(messages, loop.tools, shop=str(question["business_id"]))
        _write(log, f"\n--- turn {turn} · {reply.usage.prompt_tokens} → {reply.usage.completion_tokens} token")
        if reply.reasoning:
            _write(log, f"THINK\n{reply.reasoning}")
        if reply.content:
            _write(log, f"TEXT\n{reply.content}")
        if not reply.tool_calls:
            messages += [{"role": "assistant", "content": reply.content or ""}, {"role": "user", "content": "Hãy gọi tool."}]
            continue
        messages.append(
            {
                "role": "assistant",
                "content": reply.content or "",
                "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in reply.tool_calls],
            }
        )
        for call in reply.tool_calls:
            result, line = loop.call(call.name, call.arguments)
            if line is not None:
                _save_conversation(conversation, messages)
                return line
            _write(log, f"RESULT\n{result}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    _save_conversation(conversation, messages)
    _write(log, f"\n=== hết {max_turns} turn, không có đáp án")
    return None


def _save_conversation(path: Path | None, messages: Sequence[dict[str, Any]]) -> None:
    if path is not None:
        path.write_text(json.dumps(list(messages), ensure_ascii=False, indent=2), encoding="utf-8")


def _optional(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return None if text.lower() in ("", "null", "none") else text


def _format_exec(result: ExecResult) -> str:
    status = "timeout" if result.timed_out else f"exit {result.exit_code}"
    stderr = _last_error_line(result.stderr) if result.exit_code else ""
    output = result.stdout + (f"\n{stderr}" if stderr else "")
    if len(output) > OUTPUT_LIMIT:
        output = f"{output[:OUTPUT_LIMIT // 2]}\n... [cắt {len(output) - OUTPUT_LIMIT} ký tự] ...\n{output[-OUTPUT_LIMIT // 2:]}"
    return f"[{status}]\n{output}"


def _last_error_line(stderr: str) -> str:
    """Model nhỏ lặp lại code khi nhận traceback dài, sửa được khi chỉ nhận dòng lỗi (EXP-20261103-04)."""
    lines = [line for line in stderr.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _parse_value(text: str, answer_type: str) -> Any:
    if answer_type in ("date", "string"):
        return text.strip().strip("\"'")
    if answer_type in ("number", "percent"):
        number = float(text.replace(" ", ""))
        return fmt.percent(number) if answer_type == "percent" else fmt.quantity(number)
    if answer_type == "boolean":
        lowered = text.strip().lower()
        if lowered not in ("true", "false"):
            raise ValueError("phải là True hoặc False")
        return lowered == "true"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return ast.literal_eval(text)


def _write(log: TextIO, text: str) -> None:
    log.write(text + "\n")
    log.flush()


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" in raw and not raw.lstrip().startswith("#"):
            key, value = raw.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    if "OPENROUTER_KEY" in os.environ:
        os.environ.setdefault("OPENROUTER_API_KEY", os.environ["OPENROUTER_KEY"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent + tool → sinh code → chạy code → kết quả")
    parser.add_argument("--dataset", type=Path, default=Path("public_test"))
    parser.add_argument("--clean", type=Path, default=Path("artifacts/normalize-public/clean"))
    parser.add_argument("--questions", type=Path, default=None, help="mặc định là questions.jsonl của dataset")
    parser.add_argument("--question", nargs="*", default=None, help="chỉ chạy các id này")
    parser.add_argument("--reference", type=Path, default=None, help="file đáp án để chấm")
    parser.add_argument("--model", default="google/gemma-3-12b-it")
    parser.add_argument("--tool-choice", default="required", choices=["auto", "required"])
    parser.add_argument("--seed", type=int, default=20261103)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path("artifacts/simple-runs"))
    args = parser.parse_args(argv)
    _load_env(Path(".env"))
    os.environ["DATAMATE_CALENDAR"] = str((args.dataset / "calendar.csv").resolve())
    rows = [json.loads(raw) for raw in (args.questions or args.dataset / "questions.jsonl").read_text(encoding="utf-8").splitlines() if raw.strip()]
    questions = [q for q in rows if not args.question or q["id"] in args.question]
    if not questions:
        raise ValueError(f"no question matches {args.question}")
    reference = {} if args.reference is None else {r["id"]: r for r in map(json.loads, args.reference.read_text(encoding="utf-8").splitlines())}
    out = args.out / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    rulebook = (args.dataset / "rulebook.md").read_text(encoding="utf-8")
    client = OpenRouterClient(
        ConnectorConfig.from_env(),
        model=ModelConfig(name=args.model, temperature=0.0, seed=args.seed, max_output_tokens=4096, tool_choice=args.tool_choice),
        retry=RetryConfig(max_attempts=10),
        events=EventLog(out / "api.jsonl"),
    )

    def one(question: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
        shop = str(question["business_id"])
        clean_dir, raw_dir = args.clean / shop, args.dataset / "data" / shop
        system = system_prompt(rulebook=rulebook, clean_dir=clean_dir, raw_dir=raw_dir, shop=shop)
        with (out / f"{question['id']}.log").open("w", encoding="utf-8") as log:
            try:
                line = solve(question=question, system=system, client=client, run_code=docker_runner(clean_dir=clean_dir, raw_dir=raw_dir, calendar=args.dataset / "calendar.csv"), clean_dir=clean_dir, max_turns=args.max_turns, log=log, conversation=out / f"{question['id']}.conversation.json")
            except Exception as error:
                _write(log, f"\n=== LỖI\n{traceback.format_exc()}")
                return question, None, f"{type(error).__name__}: {str(error)[:120]}"
            _write(log, f"\n=== KẾT QUẢ {json.dumps(line, ensure_ascii=False)} · {_verdict(line, reference.get(question['id']))}")
        print(f"xong {question['id']} {_verdict(line, reference.get(question['id']))}", flush=True)
        return question, line, None

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        results = list(pool.map(one, questions))
    right = wrong = blank = failed = 0
    with (out / "answers.jsonl").open("w", encoding="utf-8") as handle:
        for question, line, error in results:
            want = reference.get(question["id"])
            verdict = "LỖI API" if error is not None else _verdict(line, want)
            failed += error is not None
            right += verdict == "ĐÚNG"
            wrong += verdict == "SAI"
            blank += line is None and error is None
            if line is not None:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
            print(f"{question['id']} {question['business_id']} {verdict:<9} model={None if line is None else line.get('answer')!r} đúng={None if want is None else want.get('answer')!r} | {error or question['question']}")
    print(f"\nđúng {right} · sai {wrong} · trống {blank} · lỗi {failed} · điểm {right - wrong}/{len(results)} · log: {out}")
    return 0


def _verdict(line: dict[str, Any] | None, want: dict[str, Any] | None) -> str:
    if line is None:
        return "TRỐNG"
    if want is None:
        return "chưa chấm"
    return "ĐÚNG" if is_correct(line, want) else "SAI"


if __name__ == "__main__":
    raise SystemExit(main())
