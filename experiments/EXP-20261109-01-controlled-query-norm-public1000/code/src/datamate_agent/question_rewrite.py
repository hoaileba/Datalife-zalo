from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Sequence

from pydantic import BaseModel, ConfigDict

from .intents import period_of
from .question_norm import normalize
from datamate.norm import name_key

REWRITE_SYSTEM = """Bạn đọc câu hỏi của chủ cửa hàng về dữ liệu bán hàng của chính cửa hàng đó. Viết lại câu cho chuẩn và cho biết câu hỏi cần gì. Không trả lời câu hỏi.

Trả lời đúng 4 dòng:
Viết lại: <câu tiếng Việt có dấu, đủ chữ, đúng chính tả>
Dạng đáp án: <một trong: số, phần trăm, tên, danh sách, ngày, tháng, đúng sai, bảng>
Số phần tử: <số phần tử câu hỏi cần nếu đáp án là danh sách, không thì ->
Cần thông tin: <các điều kiện câu hỏi lọc hoặc so theo, trừ thời gian, cách nhau bằng dấu ;, không có thì ->

Luật viết lại:
1. Giữ nguyên nghĩa và mọi điều kiện. Không thêm, không bớt điều kiện.
2. Mọi chữ số giữ nguyên như câu gốc. Cụm ngày tháng viết tắt chép nguyên hoặc chỉ thêm chữ "tháng": "5/25" viết "tháng 5/25", "T7/2025" viết "tháng 7/2025", "th6/2025" viết "tháng 6/2025". Không tự thêm chữ ngày, tuần, thứ, năm, quý mà câu gốc không có.
3. Tên riêng (tên hàng, tên khách, tên nhân viên, mã như NV002, KH0015) chép nguyên chữ như câu gốc, kể cả khi câu gốc viết không dấu.
4. Mở viết tắt, từ địa phương, tiếng lóng, tiếng Anh: dthu → doanh thu, bnhiu/bn/nhiu → bao nhiêu, th → tháng, đc → được, hnay → hôm nay, hqua → hôm qua, mô → nào, chi → gì, rứa → vậy, răng → sao, ni → này, tiệm → cửa hàng, ncc → nhà cung cấp, nv → nhân viên, check → kiểm tra, total → tổng. Bỏ từ đệm cuối câu như z, ha, nha.
5. Câu hỏi về điều dữ liệu bán hàng có thể không ghi (cảm nhận, tính cách, đặc điểm cá nhân, nơi ở, lý do) vẫn giữ đúng chữ đó.

Dạng đáp án: hỏi "bao nhiêu" một con số là số; hỏi tỉ lệ, "mấy %" là phần trăm; hỏi "ai", "X nào" một đối tượng là tên; hỏi nhiều đối tượng hay nhiều số ("top 3", "5 khách", "lần lượt") là danh sách; hỏi "ngày nào" là ngày; hỏi "tháng nào" là tháng; hỏi "có ... không", "đúng không" là đúng sai.

Ví dụ:
Câu gốc: dthu nhoms hàng khai vị chiếm bnhiu phần trăm tổng doanh thu tháng 5 năm 2026
Viết lại: Doanh thu nhóm hàng khai vị chiếm bao nhiêu phần trăm tổng doanh thu tháng 5 năm 2026?
Dạng đáp án: phần trăm
Số phần tử: -
Cần thông tin: nhóm hàng khai vị

Câu gốc: nhan vien Bui Dung Lan thang 1/2026 ban duoc tong cong bao nhieu tien ha
Viết lại: Nhân viên Bui Dung Lan tháng 1/2026 bán được tổng cộng bao nhiêu tiền?
Dạng đáp án: số
Số phần tử: -
Cần thông tin: nhân viên Bui Dung Lan

Câu gốc: Th3/26 3 món mô bán chạy nhất rứa?
Viết lại: Tháng 3/26 3 món nào bán chạy nhất vậy?
Dạng đáp án: danh sách
Số phần tử: 3
Cần thông tin: -

Câu gốc: cho hỏi trong tháng 12/2025, khách nữ chiếm bao nhiu % doanh thu
Viết lại: Trong tháng 12/2025, khách nữ chiếm bao nhiêu % doanh thu?
Dạng đáp án: phần trăm
Số phần tử: -
Cần thông tin: giới tính khách là nữ"""
DIGITS = re.compile(r"\d+")
WORDS = re.compile(r"[a-z]+")
UNIT_WORDS = frozenset({"ly", "dia", "cai", "chai", "hop", "goi", "vien", "lon", "thung", "bich", "chiec", "tuyp", "cuon", "kg"})
TIME_WORDS = {"ngày": "ngay", "tuần": "tuan", "thứ": "thu", "tháng": "thang", "năm": "nam", "quý": "quy"}
MONTH_SHORT = re.compile(r"(?<![\d/])(t|th|thg)?\s*\d{1,2}\s*[/-]\s*\d{2,4}(?![\d/])")
QUARTER_SHORT = re.compile(r"(?<![a-z])q\s*[1-4](?!\d)")
SHAPES = {"so": "number", "phan tram": "percent", "ten": "string", "danh sach": "list", "ngay": "date", "thang": "month", "dung sai": "boolean", "bang": "table"}
MAX_GROWTH = 3

Complete = Callable[[Sequence[dict[str, Any]]], str]


class Rewrite(BaseModel):
    """Câu hỏi viết chuẩn và phân tích của LLM; `problem` khác rỗng thì câu viết lại bị loại, agent dùng câu gốc và bỏ phân tích."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    original: str
    rewritten: str | None
    shape: str | None = None
    count: int | None = None
    needs: tuple[str, ...] = ()
    problem: str | None = None
    model: str


def _words(text: str) -> set[str]:
    return set(WORDS.findall(normalize(text)))


def check_rewrite(original: str, rewritten: str, *, names: Sequence[str], as_of: date | None = None) -> str | None:
    """Luật bất biến kiểm bằng code: số, kỳ hỏi, từ chỉ thời gian, tên riêng đã nối và đơn vị phải còn nguyên."""
    text = rewritten.strip()
    if not text:
        return "empty rewrite"
    if "\n" in text:
        return "rewrite has several lines"
    if len(text) > MAX_GROWTH * len(original) + 40:
        return "rewrite too long"
    if Counter(map(int, DIGITS.findall(original))) != Counter(map(int, DIGITS.findall(text))):
        return f"numbers changed: {DIGITS.findall(original)} -> {DIGITS.findall(text)}"
    folded = normalize(text)
    if period_of(normalize(original), as_of=as_of) != period_of(folded, as_of=as_of):
        return f"period changed: {period_of(normalize(original), as_of=as_of)} -> {period_of(folded, as_of=as_of)}"
    before = _words(original)
    allowed = ({"thang"} if MONTH_SHORT.search(normalize(original)) else set()) | ({"quy"} if QUARTER_SHORT.search(normalize(original)) else set())
    written = set(re.findall(r"\w+", name_key(text)))
    added = sorted(folded_word for word, folded_word in TIME_WORDS.items() if word in written and folded_word not in before and folded_word not in allowed)
    if added:
        return f"time words added: {added}"
    lost_units = sorted((UNIT_WORDS & before) - _words(text))
    if lost_units:
        return f"units dropped: {lost_units}"
    lost = [name for name in names if normalize(name) not in folded]
    if lost:
        return f"names lost: {lost}"
    return None


def parse_reply(reply: str) -> tuple[str, str | None, int | None, tuple[str, ...]]:
    """Bốn dòng của LLM thành câu viết lại, dạng đáp án, số phần tử và thông tin cần; dòng thiếu hay lạ thì để trống."""
    fields: dict[str, str] = {}
    for line in reply.strip().splitlines():
        label, _, value = line.partition(":")
        fields[normalize(label)] = value.strip().strip('"').strip()
    shape = SHAPES.get(normalize(fields.get("dang dap an", "")).strip())
    count_text = fields.get("so phan tu", "")
    count = int(count_text) if count_text.isdigit() else None
    needs_text = fields.get("can thong tin", "")
    needs = tuple(part.strip() for part in needs_text.split(";") if part.strip() and part.strip() != "-")
    return fields.get("viet lai", ""), shape, count, needs


def rewrite(question: dict[str, Any], *, names: Sequence[str], complete: Complete, model: str) -> Rewrite:
    original = str(question["question"])
    reply = complete([{"role": "system", "content": REWRITE_SYSTEM}, {"role": "user", "content": f"Câu gốc: {original}"}])
    text, shape, count, needs = parse_reply(reply)
    problem = check_rewrite(original, text, names=names, as_of=date.fromisoformat(str(question["as_of_date"])))
    if problem is None and shape is None:
        problem = "no answer shape"
    return Rewrite(id=str(question["id"]), original=original, rewritten=text, shape=shape, count=count, needs=needs, problem=problem, model=model)


def load_rewrites(path: Path) -> dict[str, Rewrite]:
    return {row.id: row for row in (Rewrite.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())}


def main(argv: Sequence[str] | None = None) -> int:
    import httpx
    import openai

    from datamate.shop import Shop

    from .agent import NORM_ROOT, llm_client
    from .llm import BACKENDS, resolve_model
    from .fewshot import entities_of, linked_names

    parser = argparse.ArgumentParser(description="Viết lại câu hỏi bằng LLM, kiểm luật bất biến, ghi cache jsonl theo id")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--backend", choices=sorted(BACKENDS), default=os.environ.get("LLM_BACKEND"), required=os.environ.get("LLM_BACKEND") is None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--seed", type=int, default=20261103)
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--mode", choices=("rewrite", "normalize"), default="rewrite")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    questions = [json.loads(line) for line in args.questions.read_text(encoding="utf-8").splitlines() if line.strip()]
    done = load_rewrites(args.out) if args.out.exists() else {}
    todo = [row for row in questions if str(row["id"]) not in done]
    args.model = resolve_model(backend=args.backend, model=args.model)
    complete = llm_client(backend=args.backend, model=args.model, seed=args.seed)
    entities: dict[str, dict[str, dict[str, str]]] = {}
    for row in todo:
        shop = str(row["business_id"])
        if shop not in entities:
            entities[shop] = entities_of(Shop(NORM_ROOT / args.dataset.name / shop, as_of=str(row["as_of_date"]), calendar=str(args.dataset / "calendar.csv")))

    def one(row: dict[str, Any]) -> Rewrite:
        names = linked_names(str(row["question"]), entities[str(row["business_id"])])
        try:
            if args.mode == "normalize":
                from .question_normalize import normalize_question

                return normalize_question(row, names=names, complete=complete, model=args.model)
            return rewrite(row, names=names, complete=complete, model=args.model)
        except (openai.OpenAIError, httpx.HTTPError, ValueError) as error:
            return Rewrite(id=str(row["id"]), original=str(row["question"]), rewritten=None, problem=f"api error: {type(error).__name__}: {str(error)[:120]}", model=args.model)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.parallel) as pool, args.out.open("a", encoding="utf-8") as sink:
        for result in pool.map(one, todo):
            sink.write(result.model_dump_json() + "\n")
            sink.flush()
            print(f"{result.id} {'OK ' if result.problem is None else 'BỎ'} {result.original[:60]!r} -> {result.rewritten!r} [{result.shape} {result.count} {list(result.needs)}] {result.problem or ''}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
