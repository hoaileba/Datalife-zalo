from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import datamate
from datamate.periods import Clock, Period

from ..models.config import PromptLanguage

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
HIDDEN_SHOP_FILES = frozenset({"questions.jsonl"})

ABSTAIN_POLICY: dict[tuple[PromptLanguage, bool], str] = {
    ("vi", False): """**Lần chạy này không cho phép `abstain`.** Mọi câu phải có đáp án: giá trị có khả năng đúng cao
nhất, hoặc `unanswerable` khi khớp một trường hợp ở trên. Hai cách đọc ra hai số thì chọn cách bám **đúng
chữ** rulebook hơn. Harness từ chối `abstain`.""",
    ("vi", True): """`("abstain", None)` là bỏ trống, luôn 0 điểm. EV một câu có xác suất đúng `p` là `2p − 1`: **chỉ trả
lời khi `p > 0.5`**. Bỏ trống khi không xác định được cột nào mang thông tin câu hỏi cần, hoặc hai cách đọc
luật ra hai số mà rulebook không phân xử được.""",
    ("en", False): """**This run does not allow `abstain`.** Every question needs an answer: the most likely value, or
`unanswerable` when one of the cases above applies. When two readings give two numbers, pick the one that
follows the rulebook's **literal wording**. The harness rejects `abstain`.""",
    ("en", True): """`("abstain", None)` leaves the question blank and always scores 0. A question you get right with
probability `p` is worth `2p − 1`: **answer only when `p > 0.5`**. Abstain when you cannot tell which column
holds what the question needs, or when two readings of the rules give two numbers and the rulebook does not
decide between them.""",
}

TASK: dict[PromptLanguage, str] = {
    "vi": "Trả lời mọi câu hỏi ở mục Context, rồi nộp bằng `submit`.",
    "en": "Answer every question under Context, then hand in with `submit`.",
}

CONTEXT_LABELS: dict[PromptLanguage, dict[str, str]] = {
    "vi": {"shop": "Shop", "questions": "Câu hỏi", "files": "File trong", "readme": "README của shop, nguyên văn"},
    "en": {"shop": "Shop", "questions": "Questions", "files": "Files in", "readme": "Shop README, verbatim"},
}


def render(template: str, values: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ValueError(f"no value for placeholder: {key}")
        return values[key]

    return PLACEHOLDER.sub(replace, template)


def system_prompt(*, language: PromptLanguage, rulebook: str, allow_abstain: bool, context: str) -> str:
    template = (PROMPT_DIR / f"system.{language}.md").read_text(encoding="utf-8")
    return render(
        template,
        {
            "abstain_policy": ABSTAIN_POLICY[(language, allow_abstain)],
            "rulebook": rulebook.strip(),
            "toolkit_reference": toolkit_reference(),
            "context": context,
        },
    )


def task_prompt(*, language: PromptLanguage) -> str:
    return TASK[language]


def shop_context(*, language: PromptLanguage, shop: str, questions: Sequence[Mapping[str, Any]], shop_dir: Path) -> str:
    if not questions:
        raise ValueError(f"shop has no questions: {shop}")
    readme = shop_dir / "README.md"
    if not readme.exists():
        raise ValueError(f"shop has no README.md: {shop_dir}")
    labels = CONTEXT_LABELS[language]
    rows = [json.dumps({"id": q["id"], "question": q["question"], "as_of_date": q["as_of_date"]}, ensure_ascii=False) for q in questions]
    files = sorted(path for path in shop_dir.rglob("*") if path.is_file() and path.name not in HIDDEN_SHOP_FILES)
    listing = [f"- `{path.relative_to(shop_dir).as_posix()}`  {path.stat().st_size} bytes" for path in files]
    return "\n".join(
        [
            f"{labels['shop']}: `{shop}`",
            "",
            f"## {labels['questions']} (`work/inputs/{shop}-questions.jsonl`)",
            "",
            "```jsonl",
            *rows,
            "```",
            "",
            f"## {labels['files']} `data/data/{shop}/`",
            "",
            *listing,
            "",
            f"## {labels['readme']}",
            "",
            readme.read_text(encoding="utf-8").strip(),
        ]
    )


def submission_script(*, shop: str, code: str) -> str:
    template = (PROMPT_DIR / "script_main.py.txt").read_text(encoding="utf-8")
    return render(template, {"shop": shop, "code": code.rstrip()})


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
