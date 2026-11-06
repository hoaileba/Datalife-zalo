from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from ..models import ExecResult, ToolResult, VerifyResult
from ..models.config import PromptLanguage
from ..utils.events import EventLog
from .executor import Executor
from .paths import PathSpace, WorkLayout
from .prompts import submission_script
from .verify import Verifier

TEXT_SUFFIXES = frozenset({".md", ".txt", ".csv", ".tsv", ".json", ".jsonl", ".py", ".yaml", ".yml", ".log"})
LIST_LIMIT = 500
DEFAULT_READ_LINES = 400

TOOL_TEXT: dict[str, dict[str, str]] = {
    "vi": {
        "list_dir": "Liệt kê file và thư mục con, kèm kích thước. path bắt đầu bằng data/ hoặc work/.",
        "read_file": "Đọc file text (md, csv, jsonl...) theo dòng, có số dòng. xlsx/sqlite thì dùng run_python với peek.",
        "read_file.offset": "dòng bắt đầu, tính từ 0",
        "read_file.limit": "số dòng tối đa, mặc định 400",
        "run_python": "Chạy một đoạn Python hoàn chỉnh trong thư mục chứa data/ và work/. Trả exit code, stdout, stderr. Chỉ thấy những gì đã print.",
        "submit": "Nộp code định nghĩa answer(question, clock) -> (type, value). Harness chạy answer cho mọi câu của shop và kiểm format. ACCEPTED thì kết thúc, NOT ACCEPTED thì sửa và nộp lại.",
    },
    "en": {
        "list_dir": "List files and subfolders with sizes. path starts with data/ or work/.",
        "read_file": "Read a text file (md, csv, jsonl...) by lines, with line numbers. For xlsx/sqlite use run_python with peek.",
        "read_file.offset": "first line, counted from 0",
        "read_file.limit": "maximum number of lines, default 400",
        "run_python": "Run a complete Python snippet in a folder that contains data/ and work/. Returns exit code, stdout, stderr. You only see what you print.",
        "submit": "Hand in code that defines answer(question, clock) -> (type, value). The harness runs answer on every question of the shop and checks the format. ACCEPTED ends the run; on NOT ACCEPTED fix and submit again.",
    },
}


def tool_specs(language: PromptLanguage) -> tuple[dict[str, Any], ...]:
    text = TOOL_TEXT[language]
    return (
        _spec("list_dir", text["list_dir"], {"path": {"type": "string"}}, required=("path",)),
        _spec(
            "read_file",
            text["read_file"],
            {
                "path": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0, "description": text["read_file.offset"]},
                "limit": {"type": "integer", "minimum": 1, "description": text["read_file.limit"]},
            },
            required=("path",),
        ),
        _spec("run_python", text["run_python"], {"code": {"type": "string"}}, required=("code",)),
        _spec("submit", text["submit"], {"code": {"type": "string"}}, required=("code",)),
    )


def _spec(name: str, description: str, properties: dict[str, Any], *, required: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False},
        },
    }


class ToolBox:
    """Bốn tool của một shop agent; mọi đường dẫn đi qua PathSpace, mọi lần gọi đều có event."""

    def __init__(
        self,
        *,
        shop: str,
        language: PromptLanguage,
        space: PathSpace,
        layout: WorkLayout,
        executor: Executor,
        verifier: Verifier,
        output_limit: int,
        events: EventLog,
    ) -> None:
        self._shop = shop
        self._specs = tool_specs(language)
        self._space = space
        self._layout = layout
        self._executor = executor
        self._verifier = verifier
        self._output_limit = output_limit
        self._events = events
        self._scratch_count = 0
        self.last_verify: VerifyResult | None = None
        self._handlers: dict[str, Callable[[dict[str, Any]], ToolResult]] = {
            "list_dir": self._list_dir,
            "read_file": self._read_file,
            "run_python": self._run_python,
            "submit": self._submit,
        }

    @property
    def specs(self) -> tuple[dict[str, Any], ...]:
        return self._specs

    def call(self, name: str, raw_arguments: str) -> ToolResult:
        started = time.monotonic()
        handler = self._handlers.get(name)
        if handler is None:
            return self._refuse(name, f"unknown tool: {name}", started)
        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as error:
            return self._refuse(name, f"arguments are not valid json: {error}", started)
        if not isinstance(arguments, dict):
            return self._refuse(name, "arguments must be a json object", started)
        try:
            result = handler(arguments)
        except (ValueError, TypeError, FileNotFoundError, IsADirectoryError, NotADirectoryError, UnicodeDecodeError) as error:
            return self._refuse(name, str(error), started)
        self._events.emit("tool", shop=self._shop, tool=name, ok=True, finished=result.finished, duration_s=round(time.monotonic() - started, 3), arguments=arguments, result=_head(result.logged))
        return result

    def _refuse(self, name: str, message: str, started: float) -> ToolResult:
        self._events.emit("tool", shop=self._shop, tool=name, ok=False, error=message, duration_s=round(time.monotonic() - started, 3))
        return ToolResult(content=f"ERROR: {message}")

    def _list_dir(self, arguments: dict[str, Any]) -> ToolResult:
        target = self._space.resolve(_required(arguments, "path"), write=False)
        if not target.is_dir():
            raise NotADirectoryError(f"not a directory: {arguments['path']}")
        entries = sorted((p for p in target.iterdir() if self._space.is_visible(p)), key=lambda p: (not p.is_dir(), p.name))
        rows = [f"{p.name}/" if p.is_dir() else f"{p.name}  {p.stat().st_size} bytes" for p in entries[:LIST_LIMIT]]
        if len(entries) > LIST_LIMIT:
            rows.append(f"... {len(entries) - LIST_LIMIT} more")
        return ToolResult(content="\n".join(rows) or "(empty)")

    def _read_file(self, arguments: dict[str, Any]) -> ToolResult:
        target = self._space.resolve(_required(arguments, "path"), write=False)
        if target.suffix.lower() not in TEXT_SUFFIXES:
            raise ValueError(f"not a text file, read it with run_python and datamate.peek: {arguments['path']}")
        offset = int(arguments.get("offset", 0))
        limit = int(arguments.get("limit", DEFAULT_READ_LINES))
        if offset < 0 or limit < 1:
            raise ValueError("offset must be >= 0 and limit >= 1")
        lines = target.read_text(encoding="utf-8-sig").splitlines()
        chunk = lines[offset : offset + limit]
        body = "\n".join(f"{offset + i + 1:>6}  {line}" for i, line in enumerate(chunk))
        tail = f"\n[lines {offset + 1}-{offset + len(chunk)} of {len(lines)}]"
        return ToolResult(content=self._clip(body) + tail, full=body + tail)

    def _run_python(self, arguments: dict[str, Any]) -> ToolResult:
        code = _required(arguments, "code")
        self._scratch_count += 1
        script = self._layout.scratch(self._shop) / f"step_{self._scratch_count:03d}.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(code, encoding="utf-8")
        result = self._executor.run(script)
        self._events.emit("exec", shop=self._shop, script=self._space.virtual(script), exit_code=result.exit_code, timed_out=result.timed_out, duration_s=result.duration_s)
        return ToolResult(content=self._format_exec(result, clip=True), full=self._format_exec(result, clip=False))

    def _submit(self, arguments: dict[str, Any]) -> ToolResult:
        code = _required(arguments, "code")
        script = self._layout.script(self._shop)
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(submission_script(shop=self._shop, code=code), encoding="utf-8")
        verdict = self._verifier.run_script(self._shop)
        self.last_verify = verdict
        self._events.emit("verify", shop=self._shop, ok=verdict.ok, problems=list(verdict.problems), total=verdict.total, answered=verdict.answered, abstain=verdict.abstain, unanswerable=verdict.unanswerable)
        if not verdict.ok:
            return ToolResult(content="NOT ACCEPTED\n" + _format_verify(verdict))
        return ToolResult(content="ACCEPTED\n" + _format_answers(self._layout.answers(self._shop)), finished=True)

    def _format_exec(self, result: ExecResult, *, clip: bool) -> str:
        shown = self._clip if clip else _same
        status = "timed out" if result.timed_out else f"exit {result.exit_code}"
        parts = [f"[{status}, {result.duration_s}s]"]
        if result.stdout:
            parts.append("stdout:\n" + shown(result.stdout))
        if result.stderr:
            parts.append("stderr:\n" + shown(result.stderr))
        return "\n".join(parts)

    def _clip(self, text: str) -> str:
        if len(text) <= self._output_limit:
            return text
        half = self._output_limit // 2
        return f"{text[:half]}\n... [cut {len(text) - 2 * half} chars] ...\n{text[-half:]}"


def _same(text: str) -> str:
    return text


def _required(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing argument: {key}")
    return value


def _format_verify(result: VerifyResult) -> str:
    head = f"total={result.total} answered={result.answered} unanswerable={result.unanswerable} abstain={result.abstain}"
    if result.ok:
        return head + "\nno problems"
    return head + "\nproblems:\n" + "\n".join(f"- {p}" for p in result.problems)


def _format_answers(path: Path) -> str:
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            line = json.loads(raw)
            rows.append(f"{line['id']} = {line['type']} {json.dumps(line.get('answer'), ensure_ascii=False)}")
    return "\n".join(rows)


def _head(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else f"{text[:limit]}\n... [{len(text) - limit} ký tự nữa, xem steps.jsonl]"
