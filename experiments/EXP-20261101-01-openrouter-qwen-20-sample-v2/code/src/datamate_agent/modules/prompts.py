from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import datamate
from datamate.periods import Clock, Period

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

ABSTAIN_FORBIDDEN = """**Lần chạy này không cho phép `abstain`.** Mọi câu phải có đáp án: số / chuỗi / list / table
có khả năng đúng cao nhất, hoặc `unanswerable` khi khớp rulebook §7. Hai cách đọc ra hai số thì chọn
cách bám **đúng chữ** rulebook hơn, ghi cách còn lại vào notes. Harness từ chối file có `abstain`."""

ABSTAIN_ALLOWED = """`{"id": ..., "type": "abstain"}` là bỏ trống, luôn 0 điểm. EV một câu có xác suất đúng `p` là
`2p − 1`: **chỉ trả lời khi `p > 0.5`**. Bỏ trống khi:
- không xác định được cột nào mang thông tin câu hỏi cần, sau khi đã đọc hết README;
- hai cách đọc luật ra hai số khác nhau mà rulebook không phân xử được;
- kết quả không qua được sanity check của chính mình."""


def render(template: str, values: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ValueError(f"no value for placeholder: {key}")
        return values[key]

    return PLACEHOLDER.sub(replace, template)


def system_prompt(*, rulebook: str, allow_abstain: bool) -> str:
    template = (PROMPT_DIR / "system.md").read_text(encoding="utf-8")
    return render(
        template,
        {
            "abstain_policy": ABSTAIN_ALLOWED if allow_abstain else ABSTAIN_FORBIDDEN,
            "rulebook": rulebook.strip(),
            "toolkit_reference": toolkit_reference(),
        },
    )


def task_prompt(*, shop: str, questions: Sequence[Mapping[str, Any]]) -> str:
    if not questions:
        raise ValueError(f"shop has no questions: {shop}")
    as_of = sorted(str(q["as_of_date"]) for q in questions)
    template = (PROMPT_DIR / "task.md").read_text(encoding="utf-8")
    return render(
        template,
        {"shop": shop, "question_count": str(len(questions)), "as_of_min": as_of[0], "as_of_max": as_of[-1]},
    )


def script_skeleton(*, shop: str, questions: Sequence[Mapping[str, Any]]) -> str:
    if not questions:
        raise ValueError(f"shop has no questions: {shop}")
    entries = []
    for question in questions:
        label = f"{question['question']} | as_of {question['as_of_date']}"
        entries.append(f"    {json.dumps(str(question['id']))}: {json.dumps(label, ensure_ascii=False)},\n")
    entries_text = "".join(entries)
    template = (PROMPT_DIR / "script_template.py.txt").read_text(encoding="utf-8")
    return render(template, {"shop": shop, "questions_by_id": "{\n" + entries_text + "}"})


def toolkit_reference() -> str:
    rows: list[str] = []
    for name in sorted(datamate.__all__):
        member = getattr(datamate, name)
        if inspect.isfunction(member):
            rows.append(f"- `{name}{inspect.signature(member)}`")
    for owner in (Clock, Period):
        for name, member in vars(owner).items():
            if name.startswith("_"):
                continue
            if inspect.isfunction(member):
                rows.append(f"- `{owner.__name__}.{name}{inspect.signature(member)}`")
            elif isinstance(member, property):
                rows.append(f"- `{owner.__name__}.{name}` (property)")
        for name in getattr(owner, "model_fields", {}):
            rows.append(f"- `{owner.__name__}.{name}` (field)")
    for name, member in inspect.getmembers(datamate.fmt, inspect.isfunction):
        if not name.startswith("_") and member.__module__ == datamate.fmt.__name__:
            rows.append(f"- `fmt.{name}{inspect.signature(member)}`")
    return "\n".join(dict.fromkeys(rows))
