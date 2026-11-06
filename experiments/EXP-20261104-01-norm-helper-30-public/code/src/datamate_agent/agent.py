from __future__ import annotations

import argparse
import functools
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence, TextIO

import openai
import pandas as pd
from pydantic import BaseModel, ConfigDict

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
SRC_DIR = Path(__file__).resolve().parents[1]
NORM_ROOT = Path("artifacts/norm")
PREAMBLE = """import pandas as pd
from datamate.shop import Shop, pct_change
shop = Shop("norm", as_of="{{as_of}}", calendar="calendar.csv")
clock, lines, orders, tables = shop.clock, shop.lines, shop.orders, shop.tables
revenue, order_count, quantity, average_order, cancel_rate, ranking = shop.revenue, shop.order_count, shop.quantity, shop.average_order, shop.cancel_rate, shop.ranking
"""
READ_HINT = """
Bảng trên đã nạp sẵn, không đọc lại file. Viết code ngắn bằng hàm có sẵn, ví dụ:
print(revenue(clock.yesterday()))
print(pct_change(revenue(clock.this_month()), revenue(clock.last_month_same_days())))
print(order_count(clock.month(7, 2025), item="Tên hàng"))
Chỉ dùng lines, orders, tables khi không hàm nào khớp câu hỏi."""
FILE_READS = ("read_csv", "read_excel", "sqlite3")
DISTINCT_LIMIT = 12
RATE_LIMIT_TRIES = 30
RATE_LIMIT_WAIT_S = 20
HIDDEN_NORM_COLUMNS = frozenset({"source_file", "source_sheet", "source_row"})
MAX_REASONING_TURNS = 10
MAX_FINAL_TRIES = 3
CODE_TIMEOUT_S = 120
HEADER_SCAN = 15
META_ROWS = 200
META_SAMPLES = 3
CELL_LIMIT = 30
MAX_READ_ROWS = 10
SEPARATOR = "--------"
HIDDEN_FILES = frozenset({"README.md", "questions.jsonl"})
ANSWER_TYPES = ("number", "percent", "date", "boolean", "string", "list", "table", "unanswerable")
DATE_ANSWER = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
REASONING = {"type": "string", "description": "đã biết gì, còn thiếu gì, đủ để tính đáp án chưa"}


class ToolCall(BaseModel):
    """Một lời gọi tool do model yêu cầu."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    arguments: str


class Reply(BaseModel):
    """Một lượt trả lời của model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str | None
    thinking: str | None
    tool_calls: tuple[ToolCall, ...]


class CodeResult(BaseModel):
    """Kết quả chạy một đoạn code."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exit_code: int | None
    stdout: str
    stderr: str


def _tool(name: str, description: str, properties: dict[str, Any], required: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {"reasoning": REASONING, **properties}, "required": ["reasoning", *required]},
        },
    }


RUN_PYTHON = _tool(
    "run_python",
    "Chạy code Python để xem dữ liệu. pd, lines, orders, tables, clock và các hàm số đo đã có sẵn, không cần import. Trả về những gì print.",
    {"code": {"type": "string"}},
    ("code",),
)
READ_DATA = _tool(
    "read_data",
    "Đọc nguyên văn tên cột và num_row dòng đầu (tối đa 10) của file. Excel, sqlite thì đọc mọi sheet, mọi bảng. Không lọc, không tính. Bắt buộc gọi trước khi viết code dùng file đó.",
    {"file_path": {"type": "string"}, "num_row": {"type": "integer"}},
    ("file_path", "num_row"),
)
FINAL_CODE = _tool(
    "final_code",
    "Code tính đáp án, pd, lines, orders, tables, clock và các hàm số đo đã có sẵn. Dòng in cuối cùng là đáp án. unanswerable thì code để trống.",
    {"answer_type": {"type": "string", "enum": list(ANSWER_TYPES)}, "code": {"type": "string"}},
    ("answer_type", "code"),
)

Complete = Callable[[Sequence[dict[str, Any]], Sequence[dict[str, Any]]], Reply]
RunCode = Callable[[str], CodeResult]


def openrouter_client(*, model: str, seed: int) -> Complete:
    client = openai.OpenAI(base_url=os.environ["OPENROUTER_BASE_URL"], api_key=os.environ["OPENROUTER_API_KEY"], timeout=300, max_retries=2)

    def complete(messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply:
        for attempt in range(RATE_LIMIT_TRIES):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=list(messages),
                    tools=list(tools),
                    tool_choice="required",
                    temperature=0,
                    seed=seed,
                    extra_body={"provider": {"require_parameters": True}},
                )
                break
            except openai.RateLimitError:
                if attempt == RATE_LIMIT_TRIES - 1:
                    raise
                time.sleep(RATE_LIMIT_WAIT_S)
        message = response.choices[0].message
        calls = tuple(ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "") for c in (message.tool_calls or ()))
        thinking = getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)
        return Reply(content=message.content, thinking=thinking, tool_calls=calls)

    return complete


def preamble(as_of: str) -> str:
    return PREAMBLE.replace("{{as_of}}", as_of)


def local_runner(shop_dir: Path, *, as_of: str) -> RunCode:
    env = {**os.environ, "PYTHONPATH": str(SRC_DIR), "PYTHONWARNINGS": "ignore"}

    def run(code: str) -> CodeResult:
        try:
            done = subprocess.run([sys.executable, "-"], input=preamble(as_of) + code, cwd=shop_dir, env=env, capture_output=True, text=True, timeout=CODE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return CodeResult(exit_code=None, stdout="", stderr=f"TimeoutError: code chạy quá {CODE_TIMEOUT_S}s")
        return CodeResult(exit_code=done.returncode, stdout=done.stdout, stderr=done.stderr)

    return run


def format_result(result: CodeResult) -> str:
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    error = lines[-1] if result.exit_code != 0 and lines else ""
    return f"[exit {result.exit_code}]\n{result.stdout}{error}"


def parse_answer(text: str, answer_type: str) -> Any:
    value = text.strip().strip("\"'")
    if answer_type in ("number", "percent"):
        number = float(value.replace(",", ""))
        rounded = round(number, 2)
        return int(rounded) if answer_type == "number" and rounded.is_integer() else rounded
    if answer_type == "date":
        if not DATE_ANSWER.match(value):
            raise ValueError("date phải có dạng YYYY-MM-DD hoặc YYYY-MM")
        return value
    if answer_type == "boolean":
        if value.lower() not in ("true", "false"):
            raise ValueError("boolean phải là True hoặc False")
        return value.lower() == "true"
    if answer_type == "string":
        return value
    parsed = json.loads(text.replace("'", '"'))
    expected = list if answer_type == "list" else dict
    if not isinstance(parsed, expected):
        raise ValueError(f"{answer_type} phải in ra {expected.__name__} dạng JSON")
    return parsed


def solve(*, question: dict[str, Any], system: str, complete: Complete, run_code: RunCode, shop_dir: Path, log: TextIO) -> dict[str, Any] | None:
    user = f"Hôm nay là {question['as_of_date']}.\nCâu hỏi: {question['question']}"
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    one_line = system.replace("\n", " ")
    _write(log, f"SYSTEM PROMPT:\n{one_line}\n{SEPARATOR}\nUSER:\n{user}\n\n{SEPARATOR}\nASSISTANCE:")
    turn = reasoning_turns = final_tries = 0
    last_code: str | None = None
    read_files: set[str] = set()
    line: dict[str, Any] | None = None
    while line is None and (reasoning_turns < MAX_REASONING_TURNS or final_tries < MAX_FINAL_TRIES):
        forced = reasoning_turns >= MAX_REASONING_TURNS
        if forced and final_tries == 0:
            messages.append({"role": "user", "content": f"Đã hết {MAX_REASONING_TURNS} lượt reasoning. Gọi final_code ngay, dựa trên thông tin đã có."})
        tools = (READ_DATA,) if turn == 0 else (FINAL_CODE,) if forced else (READ_DATA, RUN_PYTHON, FINAL_CODE)
        reply = complete(messages, tools)
        _log_reply(log, turn, reply)
        turn += 1
        messages.append(_assistant_message(reply))
        if not reply.tool_calls:
            messages.append({"role": "user", "content": "Hãy gọi tool."})
        calls = reply.tool_calls
        for call in calls:
            output, line = _call_tool(call, question=question, run_code=run_code, shop_dir=shop_dir, log=log, last_code=last_code, read_files=read_files)
            if call.name == "run_python":
                last_code = _code_of(call)
            if line is not None:
                break
            _write(log, f"[RESULT GỬI CHO MODEL]\n{output}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
        if any(call.name == "final_code" for call in calls):
            final_tries += 1
        elif not forced:
            reasoning_turns += 1
        else:
            final_tries += 1
    _write(log, f"{SEPARATOR}\nFINAL:\n{json.dumps(line, ensure_ascii=False)}")
    return line


def _log_reply(log: TextIO, turn: int, reply: Reply) -> None:
    _write(log, f"Turn {turn}:")
    if reply.thinking:
        _write(log, f"[THINKING]\n{reply.thinking}")
    if reply.content:
        _write(log, f"[TEXT]\n{reply.content}")
    if not reply.tool_calls:
        _write(log, "[KHÔNG GỌI TOOL]")


def _assistant_message(reply: Reply) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": reply.content or ""}
    if reply.tool_calls:
        message["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in reply.tool_calls]
    return message


def _arguments(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _code_of(call: ToolCall) -> str:
    return str(_arguments(call.arguments).get("code", "")).strip()


def _write(log: TextIO, text: str) -> None:
    log.write(text + "\n")
    log.flush()


def _call_tool(call: ToolCall, *, question: dict[str, Any], run_code: RunCode, shop_dir: Path, log: TextIO, last_code: str | None, read_files: set[str]) -> tuple[str, dict[str, Any] | None]:
    arguments = _arguments(call.arguments)
    code = _code_of(call)
    _write(log, f"[REASONING]\n{arguments.get('reasoning', '')}\n[CALL] {call.name}")
    if call.name == "read_data":
        file_path = str(arguments.get("file_path", ""))
        _write(log, f"[ARGS] file_path={file_path} num_row={arguments.get('num_row')}")
        if Path(file_path).name in read_files:
            return f"ERROR: đã đọc {file_path} rồi. Dùng thông tin đã có, gọi final_code hoặc run_python.", None
        output = read_data(shop_dir, file_path=file_path, num_row=_row_count(arguments.get("num_row")))
        if output.startswith("ERROR"):
            return output, None
        read_files.add(Path(file_path).name)
        return output + READ_HINT, None
    unread = _unread_files(code, shop_dir=shop_dir, read_files=read_files)
    if unread and call.name in ("run_python", "final_code") and arguments.get("answer_type") != "unanswerable":
        _write(log, f"[CODE]\n{code}")
        return f"ERROR: chưa đọc file {unread}. Gọi read_data trước khi viết code dùng file đó.", None
    if any(name in code for name in FILE_READS) and "norm/" in code:
        _write(log, f"[CODE]\n{code}")
        return "ERROR: bảng trong norm/ đã nạp sẵn. Dùng hàm có sẵn, hoặc lines, orders, tables[...]; không đọc file.", None
    if call.name == "run_python":
        _write(log, f"[CODE]\n{code}")
        if code == last_code:
            return "ERROR: code y hệt lần trước, kết quả sẽ không đổi. Hãy sửa code.", None
        return format_result(_run_logged(code, run_code=run_code, log=log)), None
    if call.name == "final_code":
        return _final(arguments, code=code, question=question, run_code=run_code, log=log)
    return f"ERROR: không có tool {call.name}", None


def _row_count(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return MAX_READ_ROWS


def _unread_files(code: str, *, shop_dir: Path, read_files: set[str]) -> list[str]:
    names = {p.name for p in (shop_dir / "raw").iterdir() if p.is_file() and p.name not in HIDDEN_FILES}
    return sorted(name for name in names if name in code and name not in read_files)


def _run_logged(code: str, *, run_code: RunCode, log: TextIO) -> CodeResult:
    result = run_code(code)
    _write(log, "[OUTPUT]\n" + result.stdout + result.stderr)
    return result


def _final(arguments: dict[str, Any], *, code: str, question: dict[str, Any], run_code: RunCode, log: TextIO) -> tuple[str, dict[str, Any] | None]:
    answer_type = str(arguments.get("answer_type"))
    if answer_type not in ANSWER_TYPES:
        return f"ERROR: answer_type phải thuộc {list(ANSWER_TYPES)}", None
    if answer_type == "unanswerable":
        return "", {"id": question["id"], "type": "unanswerable", "answer": None, "reason": str(arguments.get("reasoning", ""))}
    _write(log, f"[CODE]\n{code}")
    result = _run_logged(code, run_code=run_code, log=log)
    lines = [text for text in result.stdout.splitlines() if text.strip()]
    if result.exit_code != 0 or not lines:
        return f"ERROR: code chưa in ra đáp án.\n{format_result(result)}", None
    try:
        return "", {"id": question["id"], "type": answer_type, "answer": parse_answer(lines[-1], answer_type)}
    except (ValueError, json.JSONDecodeError) as error:
        return f"ERROR: dòng cuối {lines[-1]!r} không phải đáp án kiểu {answer_type}: {error}", None


@functools.lru_cache(maxsize=None)
def norm_metadata(norm_dir: Path) -> str:
    return "\n\n".join(f"## norm/{path.name}\n{_describe_norm(path)}" for path in sorted(norm_dir.glob("*.csv")) if not path.name.endswith(".dropped.csv"))


def _describe_norm(path: Path) -> str:
    frame = pd.read_csv(path, dtype=object, encoding="utf-8")
    lines = [f"{len(frame)} dòng"]
    for column in frame.columns:
        if column in HIDDEN_NORM_COLUMNS:
            continue
        values = frame[column].dropna()
        distinct = list(dict.fromkeys(_cell(value) for value in values))
        if not distinct:
            continue
        shown = distinct if len(distinct) <= DISTINCT_LIMIT else distinct[:META_SAMPLES]
        lines.append(f"- {column}: {'mọi giá trị' if len(distinct) <= DISTINCT_LIMIT else 'ví dụ'} {shown}")
    return "\n".join(lines)


def _header_row(raw: pd.DataFrame) -> int:
    counts = [int(raw.iloc[i].notna().sum()) for i in range(min(HEADER_SCAN, len(raw)))]
    widest = max(counts)
    for index, count in enumerate(counts):
        values = raw.iloc[index].dropna().tolist()
        if count >= max(2, int(widest * 0.6)) and all(isinstance(value, str) for value in values):
            return index
    return counts.index(widest)


def _cell(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()[:CELL_LIMIT]


def read_data(shop_dir: Path, *, file_path: str, num_row: int) -> str:
    path = shop_dir / file_path
    if ".." in Path(file_path).parts or Path(file_path).is_absolute() or not path.is_file() or path.name in HIDDEN_FILES:
        return f"ERROR: không có file {file_path!r}"
    count = max(1, min(int(num_row), MAX_READ_ROWS))
    blocks = []
    for name, raw in _raw_tables(path, count=count):
        if raw.empty:
            blocks.append(f"## {name}\nbảng rỗng")
            continue
        header = _header_row(raw)
        columns = " | ".join(_full_cell(value) for value in raw.iloc[header].tolist())
        rows = [" | ".join(_full_cell(value) for value in row) for row in raw.iloc[header + 1 : header + 1 + count].itertuples(index=False)]
        blocks.append("\n".join([f"## {name} (header ở dòng index {header})", f"Cột: {columns}", *rows]))
    return "\n\n".join(blocks) if blocks else f"ERROR: không đọc được file {file_path!r}"


def _raw_tables(path: Path, *, count: int) -> list[tuple[str, pd.DataFrame]]:
    limit = HEADER_SCAN + count
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return [(path.name, pd.read_csv(path, header=None, nrows=limit, dtype=object, encoding="utf-8-sig", on_bad_lines="skip"))]
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return [(f"sheet {sheet}", pd.read_excel(path, sheet_name=sheet, header=None, nrows=limit, dtype=object)) for sheet in pd.ExcelFile(path).sheet_names]
    if suffix in (".sqlite", ".sqlite3", ".db"):
        with sqlite3.connect(path) as connection:
            names = [row[0] for row in connection.execute("select name from sqlite_master where type='table'")]
            frames = [(f"bảng {name}", pd.read_sql_query(f'select * from "{name}" limit {count}', connection)) for name in names]
        return [(name, pd.concat([pd.DataFrame([list(f.columns)], columns=f.columns), f], ignore_index=True)) for name, f in frames]
    return []


def _full_cell(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def prepare_workspace(work_dir: Path, *, raw_dir: Path, norm_dir: Path, calendar: Path) -> Path:
    work_dir.mkdir(parents=True)
    (work_dir / "norm").symlink_to(norm_dir, target_is_directory=True)
    (work_dir / "raw").symlink_to(raw_dir, target_is_directory=True)
    shutil.copy(calendar, work_dir / "calendar.csv")
    return work_dir


def build_system(*, dataset: Path, shop: str, prompt: str, language: str) -> str:
    shop_dir = dataset / "data" / shop
    norm_dir = NORM_ROOT / dataset.name / shop
    readme = shop_dir / "README.md"
    readme_text = readme.read_text(encoding="utf-8").strip() if readme.exists() else ""
    context = "\n".join([f"Shop: {shop}", "", "# Các bảng đã chuẩn hoá", "", norm_metadata(norm_dir), "", "# README của shop (mô tả file gốc)", "", readme_text])
    template = (PROMPT_DIR / prompt / f"system.{language}.md").read_text(encoding="utf-8")
    rulebook = (dataset / "rulebook.md").read_text(encoding="utf-8").strip()
    return template.replace("{{rulebook}}", rulebook).replace("{{context}}", context)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ReAct agent: reasoning tối đa 10 lượt → code tính đáp án")
    parser.add_argument("--dataset", type=Path, default=Path("public_test"))
    parser.add_argument("--question", nargs="*", default=None)
    parser.add_argument("--questions", type=Path, default=None, help="file jsonl thay cho questions.jsonl của dataset")
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--prompt", default="v4", help="thư mục version trong prompts/")
    parser.add_argument("--model", default="google/gemma-3-12b-it")
    parser.add_argument("--language", default="vi", choices=["vi", "en"])
    parser.add_argument("--seed", type=int, default=20261103)
    parser.add_argument("--out", type=Path, default=Path("logs/agent"))
    args = parser.parse_args(argv)
    source = args.questions or args.dataset / "questions.jsonl"
    rows = [json.loads(raw) for raw in source.read_text(encoding="utf-8").splitlines() if raw.strip()]
    questions = [row for row in rows if not args.question or row["id"] in args.question]
    if not questions:
        raise ValueError(f"no question matches {args.question}")
    out = args.out / f"{args.prompt}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True)
    complete = openrouter_client(model=args.model, seed=args.seed)

    def answer(question: dict[str, Any]) -> dict[str, Any] | None:
        shop = str(question["business_id"])
        raw_dir = (args.dataset / "data" / shop).resolve()
        norm_dir = (NORM_ROOT / args.dataset.name / shop).resolve()
        work_dir = prepare_workspace(out / "work" / str(question["id"]), raw_dir=raw_dir, norm_dir=norm_dir, calendar=args.dataset / "calendar.csv")
        with (out / f"{question['id']}.log").open("w", encoding="utf-8") as log:
            system = build_system(dataset=args.dataset, shop=shop, prompt=args.prompt, language=args.language)
            try:
                return solve(question=question, system=system, complete=complete, run_code=local_runner(work_dir.resolve(), as_of=str(question["as_of_date"])), shop_dir=work_dir, log=log)
            except openai.OpenAIError as error:
                _write(log, f"{SEPARATOR}\nFINAL:\nnull\nLỖI API: {type(error).__name__}: {str(error)[:200]}")
                return None

    with ThreadPoolExecutor(max_workers=args.parallel) as pool, (out / "answers.jsonl").open("w", encoding="utf-8") as answers:
        for question, line in zip(questions, pool.map(answer, questions)):
            row = line or {"id": question["id"], "type": None, "answer": None}
            answers.write(json.dumps(row, ensure_ascii=False) + "\n")
            answers.flush()
            print(json.dumps(row, ensure_ascii=False), flush=True)
    print(f"log: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
