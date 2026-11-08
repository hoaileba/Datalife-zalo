from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Sequence

from pydantic import BaseModel, ConfigDict

from .intents import period_of
from .question_norm import normalize

REWRITE_SYSTEM = """Bạn chuẩn hoá câu hỏi của chủ cửa hàng về dữ liệu bán hàng. Viết lại thành một câu tiếng Việt có dấu, đủ chữ, đúng chính tả.

Luật:
1. Giữ nguyên nghĩa và mọi điều kiện của câu. Không thêm, không bớt điều kiện. Không trả lời câu hỏi.
2. Mọi chữ số giữ nguyên đúng như câu gốc: "8/26" giữ là "8/26", "3tr7" giữ là "3tr7", "th6/2025" viết "tháng 6/2025".
3. Tên riêng (tên hàng, tên khách, tên nhân viên, mã như NV002, KH0015) chép nguyên chữ như câu gốc, kể cả khi câu gốc viết không dấu.
4. Mở viết tắt, từ địa phương, tiếng lóng, tiếng Anh: dthu → doanh thu, bnhiu/bn/nhiu → bao nhiêu, th → tháng, đc → được, hnay → hôm nay, hqua → hôm qua, mô → nào, chi → gì, rứa → vậy, răng → sao, ni → này, tiệm → cửa hàng, o đờ/order → đơn, bill → hoá đơn, xi ô đi → COD, ncc → nhà cung cấp, nv → nhân viên, check → kiểm tra, total → tổng. Bỏ từ đệm cuối câu như z, ha, nha.
5. Câu hỏi về điều dữ liệu có thể không ghi (ngon, thân thiện, khách nữ, khách ở đường nào, lý do) vẫn giữ đúng chữ đó, không đổi thành câu hỏi khác.
6. Chỉ in đúng một dòng: câu đã viết lại.

Ví dụ:
Câu gốc: dthu nhoms hàng khai vị chiếm bnhiu phần trăm tổng doanh thu tháng 5 năm 2026
Viết lại: Doanh thu nhóm hàng khai vị chiếm bao nhiêu phần trăm tổng doanh thu tháng 5 năm 2026?
Câu gốc: nhan vien Bui Dung Lan thang 1/2026 ban duoc tong cong bao nhieu tien ha
Viết lại: Nhân viên Bui Dung Lan tháng 1/2026 bán được tổng cộng bao nhiêu tiền?
Câu gốc: Th3/26 món mô bán chạy nhất rứa?
Viết lại: Tháng 3/26 món nào bán chạy nhất vậy?
Câu gốc: cho hỏi trong tháng 12/2025, khách nữ chiếm bao nhiu % doanh thu
Viết lại: Trong tháng 12/2025, khách nữ chiếm bao nhiêu % doanh thu?"""
DIGITS = re.compile(r"\d+")
UNIT_WORDS = ("ly", "dia", "cai", "chai", "hop", "goi", "vien", "lon", "thung", "bich", "chiec", "tuyp", "cuon", "kg")
KEPT_PHRASES = UNIT_WORDS + ("khach nu", "khach nam", "duong", "ngon", "than thien", "nhiet tinh", "trung thuc", "uy tin", "kho tinh", "chat luong", "ly do", "vi sao", "dong khach", "huy vi", "tra vi")
MAX_GROWTH = 3

Complete = Callable[[Sequence[dict[str, Any]]], str]


class Rewrite(BaseModel):
    """Câu hỏi viết chuẩn của một câu gốc; `problem` khác rỗng thì câu viết lại bị loại và agent dùng câu gốc."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    original: str
    rewritten: str | None
    problem: str | None = None
    model: str


def _phrases(text: str) -> set[str]:
    folded = normalize(text)
    return {phrase for phrase in KEPT_PHRASES if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", folded)}


def check_rewrite(original: str, rewritten: str, *, names: Sequence[str], as_of: date | None = None) -> str | None:
    """Luật bất biến kiểm bằng code: số, kỳ hỏi, tên riêng đã nối, đơn vị và các cụm quyết định câu không trả lời được phải còn nguyên."""
    text = rewritten.strip()
    if not text:
        return "empty rewrite"
    if "\n" in text:
        return "rewrite has several lines"
    if len(text) > MAX_GROWTH * len(original) + 40:
        return "rewrite too long"
    if Counter(DIGITS.findall(original)) != Counter(DIGITS.findall(text)):
        return f"numbers changed: {DIGITS.findall(original)} -> {DIGITS.findall(text)}"
    folded = normalize(text)
    if period_of(normalize(original), as_of=as_of) != period_of(folded, as_of=as_of):
        return f"period changed: {period_of(normalize(original), as_of=as_of)} -> {period_of(folded, as_of=as_of)}"
    lost = [name for name in names if normalize(name) not in folded]
    if lost:
        return f"names lost: {lost}"
    dropped = sorted(_phrases(original) - _phrases(text))
    if dropped:
        return f"phrases dropped: {dropped}"
    return None


def rewrite(question: dict[str, Any], *, names: Sequence[str], complete: Complete, model: str) -> Rewrite:
    original = str(question["question"])
    reply = complete([{"role": "system", "content": REWRITE_SYSTEM}, {"role": "user", "content": f"Câu gốc: {original}\nViết lại:"}])
    text = reply.strip().removeprefix("Viết lại:").strip().strip('"').strip()
    problem = check_rewrite(original, text, names=names, as_of=date.fromisoformat(str(question["as_of_date"])))
    return Rewrite(id=str(question["id"]), original=original, rewritten=text, problem=problem, model=model)


def load_rewrites(path: Path) -> dict[str, Rewrite]:
    return {row.id: row for row in (Rewrite.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())}


def main(argv: Sequence[str] | None = None) -> int:
    import httpx
    import openai

    from datamate.shop import Shop

    from .agent import NORM_ROOT, openrouter_client
    from .fewshot import entities_of, linked_names

    parser = argparse.ArgumentParser(description="Viết lại câu hỏi bằng LLM, kiểm luật bất biến, ghi cache jsonl theo id")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--seed", type=int, default=20261103)
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    questions = [json.loads(line) for line in args.questions.read_text(encoding="utf-8").splitlines() if line.strip()]
    done = load_rewrites(args.out) if args.out.exists() else {}
    todo = [row for row in questions if str(row["id"]) not in done]
    complete = openrouter_client(model=args.model, seed=args.seed)
    entities: dict[str, dict[str, dict[str, str]]] = {}
    for row in todo:
        shop = str(row["business_id"])
        if shop not in entities:
            entities[shop] = entities_of(Shop(NORM_ROOT / args.dataset.name / shop, as_of=str(row["as_of_date"]), calendar=str(args.dataset / "calendar.csv")))

    def one(row: dict[str, Any]) -> Rewrite:
        names = linked_names(str(row["question"]), entities[str(row["business_id"])])
        try:
            return rewrite(row, names=names, complete=complete, model=args.model)
        except (openai.OpenAIError, httpx.HTTPError, ValueError) as error:
            return Rewrite(id=str(row["id"]), original=str(row["question"]), rewritten=None, problem=f"api error: {type(error).__name__}: {str(error)[:120]}", model=args.model)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.parallel) as pool, args.out.open("a", encoding="utf-8") as sink:
        for result in pool.map(one, todo):
            sink.write(result.model_dump_json() + "\n")
            sink.flush()
            print(f"{result.id} {'OK ' if result.problem is None else 'BỎ'} {result.original[:60]!r} -> {result.rewritten!r} {result.problem or ''}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
