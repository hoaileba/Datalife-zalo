from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from ..models import ExecResult, ToolResult, VerifyResult
from ..utils.events import EventLog
from .executor import Executor
from .paths import PathSpace, WorkLayout
from .verify import Verifier

TEXT_SUFFIXES = frozenset({".md", ".txt", ".csv", ".tsv", ".json", ".jsonl", ".py", ".yaml", ".yml", ".log"})
LIST_LIMIT = 500
DEFAULT_READ_LINES = 400

TOOL_SPECS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "Liệt kê file và thư mục con, kèm kích thước. Đường dẫn bắt đầu bằng data/ hoặc work/.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Đọc file text (md, jsonl, csv, py) theo dòng, có số dòng. File xlsx/sqlite thì dùng run_python với datamate.peek.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0, "description": "dòng bắt đầu, tính từ 0"},
                    "limit": {"type": "integer", "minimum": 1, "description": "số dòng tối đa"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Ghi đè toàn bộ một file trong work/.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "Chạy Python. Truyền code (đoạn khám phá) hoặc path (script trong work/), không truyền cả hai. Trả exit code, stdout, stderr.",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}, "path": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_answers",
            "description": "Kiểm file đáp án của shop: đủ id, đúng format, chính sách abstain. Không chạy lại script.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Nộp bài. Harness chạy lại script và so với file đáp án; lệch thì trả lỗi và bạn làm tiếp.",
            "parameters": {
                "type": "object",
                "properties": {"report": {"type": "string"}},
                "required": ["report"],
                "additionalProperties": False,
            },
        },
    },
)


class ToolBox:
    """Sáu tool của một shop agent; mọi đường dẫn đi qua PathSpace, mọi lần gọi đều có event."""

    def __init__(
        self,
        *,
        shop: str,
        space: PathSpace,
        layout: WorkLayout,
        executor: Executor,
        verifier: Verifier,
        output_limit: int,
        events: EventLog,
    ) -> None:
        self._shop = shop
        self._space = space
        self._layout = layout
        self._executor = executor
        self._verifier = verifier
        self._output_limit = output_limit
        self._events = events
        self._scratch_count = 0
        self.last_report: str | None = None
        self.last_verify: VerifyResult | None = None
        self._handlers: dict[str, Callable[[dict[str, Any]], ToolResult]] = {
            "list_dir": self._list_dir,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "run_python": self._run_python,
            "check_answers": self._check_answers,
            "finish": self._finish,
        }

    @property
    def specs(self) -> tuple[dict[str, Any], ...]:
        return TOOL_SPECS

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
        self._events.emit("tool", shop=self._shop, tool=name, ok=True, finished=result.finished, duration_s=round(time.monotonic() - started, 3), arguments=_summarise(arguments))
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

    def _write_file(self, arguments: dict[str, Any]) -> ToolResult:
        target = self._space.resolve(_required(arguments, "path"), write=True)
        if target.parent == self._layout.answers_dir():
            raise ValueError("answers files are written by your script with fmt.write_answers, not by write_file")
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return ToolResult(content=f"wrote {len(content)} chars to {self._space.virtual(target)}")

    def _run_python(self, arguments: dict[str, Any]) -> ToolResult:
        code, path = arguments.get("code"), arguments.get("path")
        if (code is None) == (path is None):
            raise ValueError("pass exactly one of code or path")
        if code is not None:
            if not isinstance(code, str) or not code.strip():
                raise ValueError("code must be a non-empty string")
            self._scratch_count += 1
            script = self._layout.scratch(self._shop) / f"step_{self._scratch_count:03d}.py"
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(code, encoding="utf-8")
        else:
            script = self._space.resolve(str(path), write=True)
            if not script.is_file():
                raise FileNotFoundError(f"script not found: {path}")
        result = self._executor.run(script)
        self._events.emit("exec", shop=self._shop, script=self._space.virtual(script), exit_code=result.exit_code, timed_out=result.timed_out, duration_s=result.duration_s)
        return ToolResult(content=self._format_exec(result, clip=True), full=self._format_exec(result, clip=False))

    def _check_answers(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=_format_verify(self._verifier.check_file(self._shop)))

    def _finish(self, arguments: dict[str, Any]) -> ToolResult:
        report = _required(arguments, "report")
        verdict = self._verifier.verify(self._shop)
        self.last_verify = verdict
        self._events.emit("verify", shop=self._shop, ok=verdict.ok, problems=list(verdict.problems), total=verdict.total, answered=verdict.answered, abstain=verdict.abstain, unanswerable=verdict.unanswerable)
        if not verdict.ok:
            return ToolResult(content="NOT ACCEPTED\n" + _format_verify(verdict))
        self.last_report = report
        return ToolResult(content="ACCEPTED\n" + _format_verify(verdict), finished=True)

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


def _summarise(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: (value if not isinstance(value, str) or len(value) <= 120 else f"<{len(value)} chars>") for key, value in arguments.items()}
