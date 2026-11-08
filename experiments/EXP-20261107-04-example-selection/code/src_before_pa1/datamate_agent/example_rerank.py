from __future__ import annotations

import re
from typing import Any, Callable, Sequence

from .fewshot import Example

RERANK_SYSTEM = """Bạn chọn ví dụ mẫu cho một câu hỏi về dữ liệu bán hàng. Mỗi ví dụ là một câu hỏi đã giải đúng kèm dòng code tính đáp án.

Chọn ví dụ có **cùng phép tính** với câu hỏi: cùng hàm, cùng số đo (tiền, số lượng, số đơn, số ngày, số khách, số mặt hàng, lãi), cùng cách xếp hạng và cùng dạng đáp án (một số, một tên, danh sách mấy phần tử, đúng sai). Kỳ thời gian và tên riêng khác nhau không quan trọng.

Chỉ trả lời đúng một con số: số thứ tự của ví dụ phù hợp nhất."""
CHOICE = re.compile(r"\d+")

Complete = Callable[[Sequence[dict[str, Any]]], str]


def rerank(question: str, candidates: Sequence[Example], *, complete: Complete, rewritten: str | None = None) -> tuple[Example, ...]:
    """Ứng viên xếp lại: ví dụ LLM chọn lên đầu, còn lại giữ thứ tự cũ; LLM trả lời lạ thì giữ nguyên."""
    if len(candidates) < 2:
        return tuple(candidates)
    listed = "\n".join(f"{index}. {example.question}\n   code: {example.code}" for index, example in enumerate(candidates, start=1))
    asked = f"Câu hỏi: {question}" + (f"\nViết chuẩn: {rewritten}" if rewritten else "")
    reply = complete([{"role": "system", "content": RERANK_SYSTEM}, {"role": "user", "content": f"{asked}\n\nCác ví dụ:\n{listed}\n\nSố thứ tự ví dụ phù hợp nhất:"}])
    found = CHOICE.search(reply)
    pick = int(found.group(0)) - 1 if found else -1
    if not 0 <= pick < len(candidates):
        return tuple(candidates)
    return (candidates[pick], *(example for index, example in enumerate(candidates) if index != pick))
