from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from datamate.norm import fold_key
from datamate.shop import FILTER_SYNONYMS

from .intents import baseline_of, longest_match, period_of
from .question_norm import normalize

LIBRARY_PATH = Path(__file__).resolve().parent / "prompts" / "library.jsonl"
CURATED_PATH = LIBRARY_PATH.with_name("library_curated.jsonl")
ENTITY_COLUMNS = (("item", "item_name"), ("group", "item_group"), ("customer", "customer_name"), ("ingredient", "active_ingredient"))
UNMASKED = frozenset({"payment"})
PAYMENT_SHORT_KEYS = frozenset({"ck", "tm"})
SHORT_ENTITY = 5
ENTITY_CUE = r"(?:nhom|mon|loai|hang|mat hang|san pham)"
DEFAULT_NEIGHBORS = 4
VALUES_LIMIT = 30


class Example(BaseModel):
    """Một cặp câu hỏi và code helper đã khớp gold trên train."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str
    masked: str
    answer_type: str
    code: str
    intent: str
    requires: str | None = None
    shops: tuple[str, ...] = ()


LINKED_LABELS = {"item": "mặt hàng", "group": "nhóm", "customer": "khách", "ingredient": "hoạt chất"}
LINKED_KEYS = frozenset(LINKED_LABELS)


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
    if "payment_method" in lines.columns:
        found["payment"] = {}
        for value in lines["payment_method"].dropna().unique():
            folded = fold_key(str(value))
            group = next((names for names in FILTER_SYNONYMS["payment"] if folded in names), (folded,))
            found["payment"].update({normalize(name): str(value) for name in (*group, folded)})
    return found


def _accent_agrees(question: str, key: str, name: str) -> bool:
    """Tên khớp sau khi bỏ dấu chỉ được nhận khi dấu trong câu không mâu thuẫn: `trả` không phải `trà`, `rứa` không phải `rửa`."""
    raw = unicodedata.normalize("NFC", question).casefold()
    if unicodedata.normalize("NFC", name).casefold() in raw:
        return True
    words = re.findall(r"\w+", raw)
    size = len(key.split())
    spans = [" ".join(words[start : start + size]) for start in range(len(words) - size + 1)]
    written = [span for span in spans if fold_key(span) == key]
    if not written:
        return True
    if any(span != fold_key(span) for span in written):
        return False
    return len(key) >= SHORT_ENTITY or " " in key or re.search(rf"{ENTITY_CUE} {re.escape(key)}(?![a-z0-9])", normalize(question)) is not None


def linked_match(question: str, text: str, names: dict[str, str]) -> str | None:
    """Tên dài nhất khớp trong câu mà dấu không mâu thuẫn."""
    left = dict(names)
    while (match := longest_match(text, left)) is not None:
        keys = [key for key, name in left.items() if name == match]
        if any(_accent_agrees(question, key, match) for key in keys if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", text)):
            return match
        for key in keys:
            del left[key]
    return None


def payments_in(text: str, names: dict[str, str]) -> tuple[str, ...]:
    """Hình thức thanh toán nêu trong câu, giá trị như trong dữ liệu, theo thứ tự câu hỏi nêu."""
    found: list[tuple[int, int, str]] = []
    for key, value in names.items():
        if len(key) < 3 and key not in PAYMENT_SHORT_KEYS:
            continue
        found.extend((hit.start(), -len(key), value) for hit in re.finditer(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", text))
    ordered: list[str] = []
    covered = -1
    for start, negative, value in sorted(found):
        if start < covered:
            continue
        covered = start - negative
        if value not in ordered:
            ordered.append(value)
    return tuple(ordered)


def mask_question(question: str, entities: dict[str, dict[str, str]]) -> str:
    text = normalize(question)
    for key, names in entities.items():
        if key in UNMASKED:
            continue
        match = linked_match(question, text, names)
        while match is not None:
            found = next(norm for norm, name in names.items() if name == match and re.search(rf"(?<![a-z0-9]){re.escape(norm)}(?![a-z0-9])", text))
            text = text.replace(found, f"<{key}>")
            match = linked_match(question, text, names)
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

    def scored(self, masked: str, *, count: int = DEFAULT_NEIGHBORS, domains: tuple[str, ...] | None = None, exclude: str | None = None, shop: str | None = None) -> tuple[tuple[float, Example], ...]:
        """Ví dụ gần nhất kèm điểm cosine, mỗi loại câu một ví dụ, chỉ lấy câu của shop khác."""
        query = self._vector(masked)
        scores = [sum(weight * vector.get(term, 0.0) for term, weight in query.items()) for vector in self._vectors]
        picked: dict[str, tuple[float, Example]] = {}
        for index in sorted(range(len(self.examples)), key=lambda index: -scores[index]):
            example = self.examples[index]
            if exclude is not None and example.question == exclude:
                continue
            if shop is not None and shop in example.shops:
                continue
            if example.requires is not None and domains is not None and example.requires not in domains:
                continue
            picked.setdefault(example.intent, (scores[index], example))
            if len(picked) == count:
                break
        return tuple(picked.values())

    def nearest(self, masked: str, *, count: int = DEFAULT_NEIGHBORS, domains: tuple[str, ...] | None = None, exclude: str | None = None) -> tuple[Example, ...]:
        return tuple(example for _, example in self.scored(masked, count=count, domains=domains, exclude=exclude))


def load_library(path: Path = LIBRARY_PATH) -> Library:
    sources = (path, CURATED_PATH) if CURATED_PATH.exists() else (path,)
    rows = [json.loads(raw) for source in sources for raw in source.read_text(encoding="utf-8").splitlines() if raw.strip()]
    return Library(tuple(Example(**row) for row in rows))


def linked_names(question: str, entities: dict[str, dict[str, str]]) -> tuple[str, ...]:
    """Tên mặt hàng, nhóm, khách, hoạt chất mà câu hỏi nhắc tới, viết như trong dữ liệu."""
    text = normalize(question)
    return tuple(match for key, names in entities.items() if key in LINKED_KEYS and (match := linked_match(question, text, names)))


def question_hints(question: str, entities: dict[str, dict[str, str]], *, as_of: date | None = None) -> str:
    """Tên riêng, hình thức thanh toán, kỳ và kỳ đem ra so nhận ra trong câu hỏi, viết đúng như trong dữ liệu."""
    text = normalize(question)
    labels = LINKED_LABELS
    parts = [f"{labels[key]} {match!r}" for key, names in entities.items() if key in labels and (match := linked_match(question, text, names))]
    payments = payments_in(text, entities.get("payment", {}))
    if payments:
        parts.append(f"thanh toán payment= theo thứ tự câu hỏi nêu: {', '.join(repr(value) for value in payments)}")
    period = period_of(text, as_of=as_of)
    if period:
        parts.append(f"kỳ {period}")
    baseline = baseline_of(text)
    if baseline:
        parts.append(f"kỳ đem ra so {baseline}")
    return "; ".join(parts)


def shop_values(shop: Any) -> str:
    """Nhóm hàng và đơn vị cơ bản thật của shop, để nối cách gọi trong câu hỏi với giá trị trong dữ liệu."""
    lines = shop.lines
    if lines is None:
        return ""
    parts = []
    for label, column in (("Nhóm hàng của shop", "item_group"), ("Đơn vị cơ bản của shop", "base_unit")):
        if column in lines.columns:
            values = sorted({str(value) for value in lines[column].dropna().unique()})[:VALUES_LIMIT]
            if values:
                parts.append(f"\n{label}: {values}")
    return "".join(parts)


def format_examples(examples: tuple[Example, ...]) -> str:
    return "\n".join(f"- {example.question}\n  FINAL {example.answer_type}: {example.code}" for example in examples)
