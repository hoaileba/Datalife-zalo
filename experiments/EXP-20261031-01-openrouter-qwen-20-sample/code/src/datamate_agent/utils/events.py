from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER_NAME = "datamate_agent"
CONSOLE_FIELD_LIMIT = 160


class EventLog:
    """Event JSON Lines một dòng một event, ghi an toàn từ nhiều thread, kèm một dòng gọn ra console."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._logger = logging.getLogger(LOGGER_NAME)

    @property
    def path(self) -> Path:
        return self._path

    def emit(self, event: str, **fields: Any) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": event, **fields}
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        self._logger.info("%s %s", event, _console_view(fields))


def _console_view(fields: dict[str, Any]) -> str:
    parts = []
    for key, value in fields.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        if len(text) > CONSOLE_FIELD_LIMIT:
            text = text[:CONSOLE_FIELD_LIMIT] + "…"
        parts.append(f"{key}={text}")
    return " ".join(parts)


def configure_console(*, file: Path | None = None, level: int = logging.INFO) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    formatter = logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if file is not None:
        handlers.append(logging.FileHandler(file, encoding="utf-8"))
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
