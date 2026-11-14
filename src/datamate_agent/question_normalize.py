from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from datamate.norm import fold_key

from .question_norm import normalize
from .question_rewrite import Complete, Rewrite, check_rewrite

NORMALIZE_SYSTEM = """Bạn chuẩn hoá cách viết câu hỏi tiếng Việt bằng các thay thế cục bộ. Không viết lại toàn bộ câu, không trả lời câu hỏi.

Trả đúng một JSON object với bốn trường:
{"edits": [{"source": "đoạn nguyên văn cần đổi", "replacement": "cách viết chuẩn"}], "shape": "number", "count": null, "needs": []}

Luật edits:
1. Chỉ mở viết tắt, sửa chính tả/telex hoặc cách viết địa phương. Sao chép source đúng nguyên văn, có cùng hoa thường. Mỗi source phải xuất hiện đúng một lần trong câu gốc; nếu lặp hoặc không chắc thì không sửa nó.
2. Đổi từng từ/cụm ngắn độc lập; không để edits chồng nhau. Chỉ sửa những chỗ cần thiết. Không xoá từ, không thêm mệnh đề, không suy diễn.
3. Giữ nguyên mọi chữ số, mã, tên riêng, ngày tháng và tên mặt hàng/khách/nhân viên. Không sửa một phần của các tên được bảo vệ. Không mở rộng cụm chứa chữ số.
4. Giữ nguyên số đo, phép tính, bộ lọc, phủ định và điều kiện. Nhập trừ bán vẫn là phép trừ; không biến thành nhập từ đâu. Số đơn khác doanh thu. Số lượng phần/ly/đĩa không phải phần trăm.
5. Các cách viết chắc chắn: bnhiu/bn/nhiu → bao nhiêu; đh/dh → đơn hàng; dthu/dt → doanh thu; hnay → hôm nay; hqua → hôm qua; th → tháng; đc/dc → được; ncc → nhà cung cấp; nv → nhân viên; mik → mình; trog → trong. Không sửa các cụm này khi chúng nằm trong tên riêng.
6. Giữ từ đệm nếu không cần sửa. Nếu câu đã rõ thì edits là [].

Ba trường phân tích tách khỏi edits, hiểu từ câu gốc:
- shape: một trong number, percent, string, list, date, month, boolean, table. Hỏi số tiền/số đơn/số lượng là number. Chỉ tỉ lệ/phần trăm là percent. Hỏi mấy người là number; hỏi tên những người là list.
- count: số phần tử chỉ khi câu hỏi thật sự yêu cầu một danh sách có số lượng xác định, còn lại null.
- needs: các điều kiện câu hỏi cần ngoài thời gian; không tự bổ sung điều kiện.

Ví dụ câu gốc: Hnay tổng bnhiu đh z?
{"edits": [{"source": "Hnay", "replacement": "Hôm nay"}, {"source": "bnhiu", "replacement": "bao nhiêu"}, {"source": "đh", "replacement": "đơn hàng"}], "shape": "number", "count": null, "needs": []}

Ví dụ câu gốc: Trong tháng 4/2026, Bánh mì A bán bao nhiêu cái?
Tên bảo vệ: Bánh mì A
{"edits": [], "shape": "number", "count": null, "needs": ["mặt hàng Bánh mì A"]}

Ví dụ câu gốc: Trừ hàng trả lại, tháng 5/2026 thu được bnhiu tiền?
{"edits": [{"source": "bnhiu", "replacement": "bao nhiêu"}], "shape": "number", "count": null, "needs": ["trừ hàng trả lại"]}
"""
TOKEN = re.compile(r"\w+", re.UNICODE)
IDENTIFIER = re.compile(r"\b[A-Za-z][A-Za-z_-]*\d+[A-Za-z0-9_-]*\b")
SEMANTICS = {
    "orders": re.compile(r"\bdon\b|\bhoa don\b|\bbill\b"),
    "revenue": re.compile(r"\bdoanh thu\b|\brevenue\b"),
    "quantity": re.compile(r"\bso luong\b"),
    "subtract": re.compile(r"\btru\b"),
    "negative": re.compile(r"\bkhong\b|\bchua\b"),
    "strict_above": re.compile(r"\btren\b|\bhon\b|\bqua\b"),
    "strict_below": re.compile(r"\bduoi\b"),
    "at_least": re.compile(r"\bit nhat\b|\btro len\b"),
}


class Edit(BaseModel):
    """Một thay thế cục bộ có nguồn nguyên văn duy nhất."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1)
    replacement: str = Field(min_length=1)


class NormalizationProposal(BaseModel):
    """Các thay thế cách viết và metadata phân tích giữ giao diện agent hiện tại."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    edits: tuple[Edit, ...] = ()
    shape: Literal["number", "percent", "string", "list", "date", "month", "boolean", "table"]
    count: int | None = Field(default=None, ge=1)
    needs: tuple[str, ...] = ()


def semantic_markers(text: str) -> tuple[str, ...]:
    folded = normalize(text)
    found = sorted((match.start(), match.end(), name) for name, pattern in SEMANTICS.items() for match in pattern.finditer(folded))
    return tuple(name for _, _, name in found)


def protected_spans(original: str, names: Sequence[str]) -> tuple[tuple[int, int], ...]:
    tokens = tuple(TOKEN.finditer(original))
    words = tuple(fold_key(token.group()) for token in tokens)
    spans = {(match.start(), match.end()) for match in IDENTIFIER.finditer(original)}
    for name in names:
        wanted = tuple(fold_key(token.group()) for token in TOKEN.finditer(name))
        if not wanted:
            continue
        for index in range(len(words) - len(wanted) + 1):
            if words[index : index + len(wanted)] == wanted:
                spans.add((tokens[index].start(), tokens[index + len(wanted) - 1].end()))
    return tuple(sorted(spans))


def apply_edits(original: str, edits: Sequence[Edit], *, names: Sequence[str], as_of: date | None = None) -> str:
    protected = protected_spans(original, names)
    located: list[tuple[int, int, Edit]] = []
    for edit in edits:
        if edit.source != edit.source.strip() or edit.replacement != edit.replacement.strip() or "\n" in edit.source or "\n" in edit.replacement:
            raise ValueError("edit must be one trimmed fragment")
        matches = tuple(re.finditer(re.escape(edit.source), original))
        if len(matches) != 1:
            raise ValueError("edit source must occur exactly once")
        start, end = matches[0].span()
        if (start and original[start - 1].isalnum() and edit.source[0].isalnum()) or (end < len(original) and original[end].isalnum() and edit.source[-1].isalnum()):
            raise ValueError("edit cuts a word")
        if any(start < right and end > left for left, right in protected):
            raise ValueError("edit overlaps a protected name or identifier")
        if re.search(r"\d", edit.source) or re.search(r"\d", edit.replacement):
            raise ValueError("edit changes a numeric fragment")
        before, after = semantic_markers(edit.source), semantic_markers(edit.replacement)
        if before and before != after:
            raise ValueError("edit changes an explicit semantic marker")
        located.append((start, end, edit))
    ordered = sorted(located, key=lambda item: item[0])
    if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
        raise ValueError("edits overlap")
    text = original
    for start, end, edit in reversed(ordered):
        text = text[:start] + edit.replacement + text[end:]
    if semantic_markers(original) != semantic_markers(text):
        raise ValueError("normalization changes explicit semantic markers")
    problem = check_rewrite(original, text, names=names, as_of=as_of)
    if problem is not None:
        raise ValueError(problem)
    return text


def parse_proposal(reply: str) -> NormalizationProposal:
    text = reply.strip()
    if text.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, flags=re.S)
        if match is None:
            raise ValueError("malformed normalization fence")
        text = match.group(1)
    return NormalizationProposal.model_validate(json.loads(text))


def normalize_question(question: dict[str, Any], *, names: Sequence[str], complete: Complete, model: str) -> Rewrite:
    original = str(question["question"])
    user = f"Câu gốc: {original}\nTên bảo vệ: {json.dumps(tuple(names), ensure_ascii=False)}"
    reply = complete([{"role": "system", "content": NORMALIZE_SYSTEM}, {"role": "user", "content": user}])
    try:
        proposal = parse_proposal(reply)
        text = apply_edits(original, proposal.edits, names=names, as_of=date.fromisoformat(str(question["as_of_date"])))
    except (ValueError, TypeError) as error:
        return Rewrite(id=str(question["id"]), original=original, rewritten=original, problem=f"normalization rejected: {error}", model=model)
    return Rewrite(id=str(question["id"]), original=original, rewritten=text, shape=proposal.shape, count=proposal.count, needs=proposal.needs, model=model)
