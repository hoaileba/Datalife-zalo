from __future__ import annotations

import json
import logging
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

LOGGER_NAME = "datamate_agent"
DETAIL_LOGGER_NAME = "datamate_agent.tools"
DETAIL_EVENTS = frozenset({"api_call", "api_retry", "tool", "exec", "tool_repeat"})
CONSOLE_FIELD_LIMIT = 160
DETAIL_INLINE_LIMIT = 120


class EventLog:
    """Event JSON Lines một dòng một event, ghi an toàn từ nhiều thread, kèm một dòng gọn ra console."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._logger = logging.getLogger(LOGGER_NAME)
        self._detail = logging.getLogger(DETAIL_LOGGER_NAME)

    @property
    def path(self) -> Path:
        return self._path

    def emit(self, event: str, **fields: Any) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": event, **fields}
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        if event in DETAIL_EVENTS:
            self._detail.info("%s", _detail_view(event, fields))
        else:
            self._logger.info("%s %s", event, _console_view(fields))


def _console_view(fields: dict[str, Any]) -> str:
    parts = []
    for key, value in fields.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        if len(text) > CONSOLE_FIELD_LIMIT:
            text = text[:CONSOLE_FIELD_LIMIT] + "…"
        parts.append(f"{key}={text}")
    return " ".join(parts)


def _detail_view(event: str, fields: dict[str, Any]) -> str:
    head: list[str] = [event]
    blocks: list[str] = []
    for key, value in fields.items():
        if isinstance(value, dict):
            for inner, item in value.items():
                _place(f"{key}.{inner}", item, head, blocks)
        else:
            _place(key, value, head, blocks)
    return " ".join(head) + "".join(blocks)


def _place(key: str, value: Any, head: list[str], blocks: list[str]) -> None:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if "\n" in text or len(text) > DETAIL_INLINE_LIMIT:
        indented = "\n".join("    " + line for line in text.splitlines())
        blocks.append(f"\n  {key}:\n{indented}")
    else:
        head.append(f"{key}={text}")


class TqdmHandler(logging.Handler):
    """In log ra stderr qua tqdm.write để không làm vỡ thanh progress đang chạy."""

    def emit(self, record: logging.LogRecord) -> None:
        from tqdm import tqdm

        tqdm.write(self.format(record), file=sys.stderr)


def configure_console(*, files: Sequence[Path] = (), detail_files: Sequence[Path] = (), level: int = logging.INFO) -> None:
    formatter = logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S")
    _attach(logging.getLogger(LOGGER_NAME), [TqdmHandler(), *_file_handlers(files)], formatter, level)
    detail = logging.getLogger(DETAIL_LOGGER_NAME)
    detail.propagate = False
    _attach(detail, _file_handlers(detail_files), formatter, level)


def _file_handlers(paths: Sequence[Path]) -> list[logging.Handler]:
    handlers: list[logging.Handler] = []
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, mode="a", encoding="utf-8"))
    return handlers


def _attach(logger: logging.Logger, handlers: Sequence[logging.Handler], formatter: logging.Formatter, level: int) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
