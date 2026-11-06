from __future__ import annotations

import argparse
import ast
import functools
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal, Sequence, TextIO

import openai
import pandas as pd
from pydantic import BaseModel, ConfigDict

from datamate.shop import Shop

from .fewshot import entities_of, format_examples, load_library, mask_question, question_hints

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
SRC_DIR = Path(__file__).resolve().parents[1]
NORM_ROOT = Path("artifacts/norm")
PREAMBLE = """import pandas as pd
from datamate.shop import HELPERS, Shop, pct_change
shop = Shop("norm", as_of="{{as_of}}", calendar="calendar.csv")
clock, lines, orders, tables = shop.clock, shop.lines, shop.orders, shop.tables
globals().update({name: getattr(shop, name) for name in HELPERS})
def _show(value):
    if isinstance(value, (pd.Index, pd.Series)):
        return value.tolist() if isinstance(value, pd.Index) else value.to_dict()
    return value.item() if hasattr(value, "item") else value
"""
READ_HINT = """
Bảng trên đã nạp sẵn, không đọc lại file. Viết FINAL theo ví dụ trong câu hỏi, đổi kỳ và tên cho đúng câu hỏi."""
DISTINCT_LIMIT = 12
RATE_LIMIT_TRIES = 60
RATE_LIMIT_WAIT_S = 5
NORM_READ = re.compile(r"""pd\.read_csv\(\s*f?['"](?:\./)?norm/([^'"]+?)\.csv['"][^()]*\)""")
DATE_WITH_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]00:00:00$")
ZERO_HINT = "\nKết quả rỗng hoặc 0: kiểm lại trước khi nộp. Cột year, month là số nguyên, ngày là datetime, không so với chuỗi. Dùng hàm có sẵn nếu được."
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
NO_DATA_ERROR = "shop has no"
HIDDEN_FILES = frozenset({"README.md", "questions.jsonl"})
ANSWER_TYPES = ("number", "percent", "date", "boolean", "string", "list", "table", "unanswerable")
DATE_ANSWER = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
FINAL_LINE = re.compile(r"^\s*\**FINAL\**\s*:?\s*\**([a-z]+)\**", re.MULTILINE)
READ_LINE = re.compile(r"^\s*\**READ\**\s*:?\s*`?([^\s`]+)`?", re.MULTILINE)
CODE_FENCE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.DOTALL)
FORMAT_ERROR = "ERROR: không thấy lệnh. Trả lời bằng một trong ba dạng: READ norm/<file>.csv, khối ```python để chạy thử, hoặc FINAL <type> kèm khối ```python."


class Action(BaseModel):
    """Một lệnh đọc được từ câu trả lời của model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["read", "run", "final", "none"]
    reasoning: str
    path: str = ""
    code: str = ""
    answer_type: str = ""
    kept: str


class RunState:
    """Những gì đã xảy ra trong một câu hỏi, để chặn lặp và chặn bỏ cuộc sớm."""

    def __init__(self) -> None:
        self.read_files: set[str] = set()
        self.last_code: str | None = None
        self.ran_code = False
        self.helper_refused = False
        self.refused_unanswerable = False


class CodeResult(BaseModel):
    """Kết quả chạy một đoạn code."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exit_code: int | None
    stdout: str
    stderr: str


Complete = Callable[[Sequence[dict[str, Any]]], str]
RunCode = Callable[[str], CodeResult]


def openrouter_client(*, model: str, seed: int) -> Complete:
    client = openai.OpenAI(base_url=os.environ["OPENROUTER_BASE_URL"], api_key=os.environ["OPENROUTER_API_KEY"], timeout=300, max_retries=2)

    def complete(messages: Sequence[dict[str, Any]]) -> str:
        for attempt in range(RATE_LIMIT_TRIES):
            try:
                response = client.chat.completions.create(model=model, messages=list(messages), temperature=0, seed=seed)
                if response.choices:
                    return response.choices[0].message.content or ""
                problem: Exception = ValueError(f"provider returned no choices: {getattr(response, 'error', None)}")
            except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError) as error:
                problem = error
            if attempt == RATE_LIMIT_TRIES - 1:
                raise problem
            time.sleep(RATE_LIMIT_WAIT_S)
        raise ValueError("no completion attempt was made")

    return complete


def parse_action(text: str) -> Action:
    """Lệnh đầu tiên trong câu trả lời: FINAL, rồi khối code, rồi READ. Phần sau lệnh bị bỏ để model không tự bịa kết quả."""
    final = FINAL_LINE.search(text)
    fence = CODE_FENCE.search(text)
    read = READ_LINE.search(text)
    if final and final.group(1) in ANSWER_TYPES:
        reasoning = text[: final.start()].strip()
        answer_type = final.group(1)
        block = CODE_FENCE.search(text, final.end())
        if block:
            return Action(kind="final", reasoning=reasoning, code=block.group(1).strip(), answer_type=answer_type, kept=text[: block.end()])
        inline = text[final.end() :].strip().split("\n")[0].strip(" :`")
        return Action(kind="final", reasoning=reasoning, code=inline, answer_type=answer_type, kept=text[: final.end() + len(inline) + 2].rstrip())
    if fence and READ_LINE.match(fence.group(1)):
        return Action(kind="read", reasoning=text[: fence.start()].strip(), path=READ_LINE.match(fence.group(1)).group(1), kept=text[: fence.end()])
    if fence and (not read or fence.start() < read.start()):
        return Action(kind="run", reasoning=text[: fence.start()].strip(), code=fence.group(1).strip(), kept=text[: fence.end()])
    if read:
        return Action(kind="read", reasoning=text[: read.start()].strip(), path=read.group(1), kept=text[: read.end()])
    return Action(kind="none", reasoning=text.strip(), kept=text)


def preamble(as_of: str) -> str:
    return PREAMBLE.replace("{{as_of}}", as_of)


def local_runner(shop_dir: Path, *, as_of: str) -> RunCode:
    env = {**os.environ, "PYTHONPATH": str(SRC_DIR), "PYTHONWARNINGS": "ignore"}

    def run(code: str) -> CodeResult:
        try:
            done = subprocess.run([sys.executable, "-"], input=preamble(as_of) + prepare_code(code), cwd=shop_dir, env=env, capture_output=True, text=True, timeout=CODE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return CodeResult(exit_code=None, stdout="", stderr=f"TimeoutError: code chạy quá {CODE_TIMEOUT_S}s")
        return CodeResult(exit_code=done.returncode, stdout=done.stdout, stderr=done.stderr)

    return run


def prepare_code(code: str) -> str:
    """Code model viết, đổi đọc file norm/ thành bảng đã nạp và in biểu thức cuối như REPL."""
    rewritten = NORM_READ.sub(lambda match: f'tables["{match.group(1)}"]', code)
    try:
        tree = ast.parse(rewritten)
    except SyntaxError:
        return rewritten
    last = tree.body[-1] if tree.body else None
    if isinstance(last, ast.Expr) and not (isinstance(last.value, ast.Call) and getattr(last.value.func, "id", None) == "print"):
        tree.body[-1] = ast.parse(f"print(_show({ast.unparse(last.value)}))").body[0]
        return ast.unparse(tree)
    return rewritten


def format_result(result: CodeResult) -> str:
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    error = lines[-1] if result.exit_code != 0 and lines else ""
    hint = ZERO_HINT if result.exit_code == 0 and result.stdout.strip() in ("0", "0.0", "[]") else ""
    return f"[exit {result.exit_code}]\n{result.stdout}{error}{hint}"


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
    parsed = ast.literal_eval(text.strip())
    expected = list if answer_type == "list" else dict
    if not isinstance(parsed, expected):
        raise ValueError(f"{answer_type} phải in ra {expected.__name__} dạng JSON")
    return parsed


def solve(*, question: dict[str, Any], system: str, hints: str, complete: Complete, run_code: RunCode, shop_dir: Path, log: TextIO) -> dict[str, Any] | None:
    user = f"Hôm nay là {question['as_of_date']}.\nCâu hỏi: {question['question']}\n{hints}".rstrip()
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    one_line = system.replace("\n", " ")
    _write(log, f"SYSTEM PROMPT:\n{one_line}\n{SEPARATOR}\nUSER:\n{user}\n\n{SEPARATOR}\nASSISTANCE:")
    state = RunState()
    line: dict[str, Any] | None = None
    turn = 0
    while line is None and turn < MAX_REASONING_TURNS + MAX_FINAL_TRIES:
        forced = turn >= MAX_REASONING_TURNS
        if turn == MAX_REASONING_TURNS:
            messages.append({"role": "user", "content": f"Đã hết {MAX_REASONING_TURNS} lượt. Trả lời FINAL ngay, dựa trên thông tin đã có."})
        action = parse_action(complete(messages))
        _write(log, f"Turn {turn}:\n[REASONING]\n{action.reasoning}\n[CALL] {action.kind}")
        messages.append({"role": "assistant", "content": action.kept})
        output, line = _execute(action, turn=turn, forced=forced, question=question, run_code=run_code, shop_dir=shop_dir, log=log, state=state)
        turn += 1
        if line is None:
            _write(log, f"[RESULT GỬI CHO MODEL]\n{output}")
            messages.append({"role": "user", "content": f"Kết quả:\n{output}"})
    _write(log, f"{SEPARATOR}\nFINAL:\n{json.dumps(line, ensure_ascii=False)}")
    return line


def _write(log: TextIO, text: str) -> None:
    log.write(text + "\n")
    log.flush()


def _execute(action: Action, *, turn: int, forced: bool, question: dict[str, Any], run_code: RunCode, shop_dir: Path, log: TextIO, state: RunState) -> tuple[str, dict[str, Any] | None]:
    if action.kind == "none":
        return FORMAT_ERROR, None
    if turn == 0 and action.kind != "read":
        return "ERROR: lượt đầu chỉ được READ một bảng trong norm/. " + _files_hint(shop_dir), None
    if forced and action.kind != "final":
        return "ERROR: đã hết lượt, chỉ còn FINAL.", None
    if action.kind == "read":
        _write(log, f"[ARGS] file_path={action.path}")
        if Path(action.path).name in state.read_files:
            return f"ERROR: đã đọc {action.path} rồi. Dùng thông tin đã có, viết FINAL hoặc khối python.", None
        output = read_data(shop_dir, file_path=action.path, num_row=MAX_READ_ROWS)
        if output.startswith("ERROR"):
            return f"{output}. {_files_hint(shop_dir)}", None
        state.read_files.add(Path(action.path).name)
        return output + READ_HINT, None
    if action.kind == "run":
        _write(log, f"[CODE]\n{action.code}")
        if action.code == state.last_code:
            return "ERROR: code y hệt lần trước, kết quả sẽ không đổi. Hãy sửa code.", None
        state.last_code = action.code
        result = _run_logged(action.code, run_code=run_code, log=log)
        state.ran_code = state.ran_code or result.exit_code == 0
        state.helper_refused = state.helper_refused or NO_DATA_ERROR in result.stderr
        return format_result(result), None
    return _final(action, question=question, run_code=run_code, log=log, state=state, forced=forced)


def _files_hint(shop_dir: Path) -> str:
    names = sorted(path.name for path in (shop_dir / "norm").glob("*.csv") if not path.name.endswith(".dropped.csv"))
    return f"Các bảng có thật: {names}"


def _run_logged(code: str, *, run_code: RunCode, log: TextIO) -> CodeResult:
    result = run_code(code)
    _write(log, "[OUTPUT]\n" + result.stdout + result.stderr)
    return result


def _final(action: Action, *, question: dict[str, Any], run_code: RunCode, log: TextIO, state: RunState, forced: bool) -> tuple[str, dict[str, Any] | None]:
    answer_type = action.answer_type
    if answer_type == "unanswerable":
        if not (state.helper_refused or state.ran_code or forced or state.refused_unanswerable):
            state.refused_unanswerable = True
            return "ERROR: chưa chạy code nào. Dữ liệu thường đủ để trả lời: thử hàm có sẵn trước, chỉ FINAL unanswerable nếu hàm báo shop không có thông tin đó.", None
        return "", {"id": question["id"], "type": "unanswerable", "answer": None, "reason": action.reasoning}
    _write(log, f"[CODE]\n{action.code}")
    result = _run_logged(action.code, run_code=run_code, log=log)
    state.helper_refused = state.helper_refused or NO_DATA_ERROR in result.stderr
    lines = [text for text in result.stdout.splitlines() if text.strip()]
    if result.exit_code != 0 or not lines:
        return f"ERROR: code chưa in ra đáp án.\n{format_result(result)}", None
    value = lines[-1].strip()
    if DATE_WITH_TIME.match(value):
        answer_type, value = "date", value[:10]
    try:
        return "", {"id": question["id"], "type": answer_type, "answer": parse_answer(value, answer_type)}
    except (ValueError, SyntaxError) as error:
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


def user_hints(question: dict[str, Any], *, norm_dir: Path, calendar: Path) -> str:
    """Ví dụ gần nhất từ thư viện và tên riêng, kỳ nhận ra trong câu hỏi."""
    entities = entities_of(Shop(norm_dir, as_of=str(question["as_of_date"]), calendar=str(calendar)))
    examples = format_examples(load_library().nearest(mask_question(str(question["question"]), entities)))
    linked = question_hints(str(question["question"]), entities)
    recognised = f"\nNhận ra trong câu: {linked}" if linked else ""
    return f"{recognised}\n\nCâu tương tự đã làm đúng ở shop khác (đổi kỳ, tên cho đúng câu hỏi của bạn):\n{examples}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ReAct agent: reasoning tối đa 10 lượt → code tính đáp án")
    parser.add_argument("--dataset", type=Path, default=Path("public_test"))
    parser.add_argument("--question", nargs="*", default=None)
    parser.add_argument("--questions", type=Path, default=None, help="file jsonl thay cho questions.jsonl của dataset")
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--prompt", default="v6", help="thư mục version trong prompts/")
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
                hints = user_hints(question, norm_dir=norm_dir, calendar=args.dataset / "calendar.csv")
                return solve(question=question, system=system, hints=hints, complete=complete, run_code=local_runner(work_dir.resolve(), as_of=str(question["as_of_date"])), shop_dir=work_dir, log=log)
            except (openai.OpenAIError, ValueError, TypeError, AttributeError) as error:
                _write(log, f"{SEPARATOR}\nFINAL:\nnull\nLỖI API: {type(error).__name__}: {str(error)[:200]}")
                return None

    with ThreadPoolExecutor(max_workers=args.parallel) as pool, (out / "answers.jsonl").open("w", encoding="utf-8") as answers:
        futures = {pool.submit(answer, question): question for question in questions}
        for future in as_completed(futures):
            line = future.result()
            row = line or {"id": futures[future]["id"], "type": None, "answer": None}
            answers.write(json.dumps(row, ensure_ascii=False) + "\n")
            answers.flush()
            print(json.dumps(row, ensure_ascii=False), flush=True)
    print(f"log: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
