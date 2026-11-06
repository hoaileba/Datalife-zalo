from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from .intents import longest_match, period_of
from .question_norm import normalize

LIBRARY_PATH = Path(__file__).resolve().parent / "prompts" / "library.jsonl"
ENTITY_COLUMNS = (("item", "item_name"), ("group", "item_group"), ("customer", "customer_name"), ("ingredient", "active_ingredient"))
DEFAULT_NEIGHBORS = 4


class Example(BaseModel):
    """Một cặp câu hỏi và code helper đã khớp gold trên train."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str
    masked: str
    answer_type: str
    code: str
    intent: str


def entities_of(shop: Any) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {key: {} for key, _ in ENTITY_COLUMNS}
    lines = shop.lines
    if lines is None:
        return found
    for key, column in ENTITY_COLUMNS:
        if column in lines.columns:
            found[key] = {normalize(str(name)): str(name) for name in lines[column].dropna().unique()}
    if "customer_group" in lines.columns:
        found["group"].update({normalize(str(name)): str(name) for name in lines["customer_group"].dropna().unique()})
    return found


def mask_question(question: str, entities: dict[str, dict[str, str]]) -> str:
    text = normalize(question)
    for key, names in entities.items():
        match = longest_match(text, names)
        while match is not None:
            found = next(norm for norm, name in names.items() if name == match)
            text = text.replace(found, f"<{key}>")
            match = longest_match(text, names)
    return re.sub(r"\d+", "#", text)


def _terms(masked: str) -> Counter[str]:
    words = masked.split()
    return Counter(words + [f"{left} {right}" for left, right in zip(words, words[1:])])


class Library:
    """Thư viện question → code, tra láng giềng gần nhất bằng TF-IDF trên câu đã che tên riêng."""

    def __init__(self, examples: tuple[Example, ...]) -> None:
        if not examples:
            raise ValueError("library is empty")
        self.examples = examples
        documents = Counter(term for example in examples for term in _terms(example.masked))
        self._idf = {term: math.log((1 + len(examples)) / (1 + count)) + 1 for term, count in documents.items()}
        self._vectors = tuple(self._vector(example.masked) for example in examples)

    def _vector(self, masked: str) -> dict[str, float]:
        weights = {term: count * self._idf.get(term, 0.0) for term, count in _terms(masked).items()}
        size = math.sqrt(sum(weight * weight for weight in weights.values())) or 1.0
        return {term: weight / size for term, weight in weights.items()}

    def nearest(self, masked: str, *, count: int = DEFAULT_NEIGHBORS) -> tuple[Example, ...]:
        query = self._vector(masked)
        scored = sorted(range(len(self.examples)), key=lambda index: -sum(weight * self._vectors[index].get(term, 0.0) for term, weight in query.items()))
        picked: dict[str, Example] = {}
        for index in scored:
            example = self.examples[index]
            picked.setdefault(example.intent, example)
            if len(picked) == count:
                break
        return tuple(picked.values())


@lru_cache(maxsize=1)
def load_library(path: Path = LIBRARY_PATH) -> Library:
    rows = [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]
    return Library(tuple(Example(**row) for row in rows))


def question_hints(question: str, entities: dict[str, dict[str, str]]) -> str:
    """Tên riêng và kỳ nhận ra trong câu hỏi, viết đúng như trong dữ liệu."""
    text = normalize(question)
    labels = {"item": "mặt hàng", "group": "nhóm", "customer": "khách", "ingredient": "hoạt chất"}
    parts = [f"{labels[key]} {match!r}" for key, names in entities.items() if (match := longest_match(text, names))]
    period = period_of(text)
    if period:
        parts.append(f"kỳ {period}")
    return "; ".join(parts)


def format_examples(examples: tuple[Example, ...]) -> str:
    return "\n".join(f"- {example.question}\n  FINAL {example.answer_type}: {example.code}" for example in examples)
