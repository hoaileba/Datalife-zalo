from __future__ import annotations

import collections
import json
import re
import sys

S, OUT = sys.argv[1], sys.argv[2]
ROWS = json.load(open(f"{S}/rows2.json"))
SAME = set(json.load(open(f"{S}/same_entity.json")))
TOPPING = ("b2bbe9", "dec759", "c64c6d", "cfcb5f", "54bbf0")
RULES = (
    ("D7 Ngày phải trả", r"ngày phải trả"),
    ("D1 Trả góp", r"góp|tra gop|tien gop|ky gop|da gop|chua gop"),
    ("D2 Bảo hành", r"bảo hành|bao hanh"),
    ("D3 Thu máy cũ, khách phải trả", r"thu (lại )?máy cũ|thu may cu|tiền thu máy|tien thu may|máy cũ thu|may cu thu|phải trả|phai tra|phãi trả|trừ bớt|tru bot|trừ tiền bớt"),
    ("D4 Hoa hồng thợ", r"hoa hồng|huê hồng|hoa hong"),
    ("D5 Lô, hạn dùng, hết hàng", r"\blô\b|\blo\b|hsd|hạn dùng|hết hạn|cận date|hết hàng|đứt hàng|het hang|chay hang|cháy hàng"),
    ("D6 Đợt giao", r"đợt|\bdot\b|chở|xe đã giao"),
    ("D8 Phí ship, voucher, điểm", r"phí ship|phi ship|voucher|vâu chơ|dung diem|dùng điểm"),
    ("D9 Xe, phiếu, dịch vụ", r"\bxe\b|lượt xe|nượt xe|luot xe|phiếu"),
    ("D10 Bỉm, sữa theo hãng và size", r"bỉm|\bbim\b|sữa bột|sua bot"),
    ("D11 Máy theo dòng, bỏ phụ kiện", r"phụ kiện|dien thoai|điện thoại|dòng máy|dong may|\bmáy\b|chiếc xiaomi|may samsung"),
)
GROUP = r"thân thiết|than thiet|nhóm sỉ|nhom si|khách sỉ"
FILTERS = r"tiền mặt|tien mat|ví điện tử|vi dien tu|chuyển khoản|chuyen khoan|xi ô đi|tại quầy|tai quay|qua điện thoại|dien thoai|zalo|sàn thương|nhân viên|\bnv\b"


def bucket(row: dict) -> str:
    question = row["q"].lower()
    short = row["id"][2:8]
    if row["id"] in SAME:
        return "A Cùng đối tượng, scorer chấm sai"
    if row["rt"] == "unanswerable":
        return "B Đáng lẽ unanswerable"
    if short in TOPPING:
        return "C1 Dòng ghép topping dev_002"
    if re.search(GROUP, question) and not row["oracle_ok"] and row["shop"] in ("dev_003", "dev_010", "dev_008"):
        return "C2 Nhóm khách: họ Tống, sai cột"
    if short in ("4c8fda", "ee2df6"):
        return "C2 Nhóm khách: họ Tống, sai cột"
    if re.search(r"nợ|\bno\b", question) and not re.search("góp", question) and row["shop"] in ("dev_008", "dev_014"):
        return "C3 Công nợ dev_008, dev_014"
    if re.search(r"nhập.*(trừ|tru|bán)|nhap.*(tru|ban)|chênh lệch nhập", question):
        return "C4 Nhập trừ bán chưa quy đơn vị"
    for name, pattern in RULES:
        if re.search(pattern, question) and not (name.startswith("D11") and row["shop"] not in ("dev_011", "dev_014")):
            return name
    if re.search(r"lên giá|tăng giá|đổi giá|len gia|tang gia|doi gia", question):
        return "E1 Đổi giá: thiếu ngày hoặc đơn vị"
    if row["rt"] == "list" and isinstance(row["ra"], list) and all(isinstance(x, (int, float)) for x in row["ra"]):
        return "E2 Hỏi nhiều số, trả một số"
    if re.search(FILTERS, question) and not row["oracle_ok"]:
        return "C5 Alias kênh, thanh toán, nhân viên"
    if row["first_fn"] == "revenue" and row["top_fn"] != "revenue":
        return "M1 Bỏ ví dụ, gọi revenue"
    if row["oracle_ok"]:
        return "M2 Helper đúng, sai tham số hoặc format"
    if re.search(r"bình quân|binh quan|bìn quân|trung bình|trung binh", question) and row["first_fn"] == "revenue":
        return "M3 Hỏi trung bình, gọi revenue"
    if re.search(r"trung thành|sộp|đắt khách|ưa chuộng|chăm chỉ|bán giỏi|đổi ý|trung thực|chính của|uy tín", question):
        return "F Từ định nghĩa trong rulebook"
    return "M4 Còn lại: tham số, kỳ, chọn hàm"


counts: dict[str, list] = collections.defaultdict(list)
for row in ROWS:
    if row["status"] != "ok":
        row["bucket"] = bucket(row)
        counts[row["bucket"]].append(row)
result = []
for name, rows in sorted(counts.items(), key=lambda pair: pair[0]):
    wrong = sum(r["status"] == "wrong" for r in rows)
    blank = len(rows) - wrong
    result.append({"bucket": name, "n": len(rows), "wrong": wrong, "blank": blank, "max_gain": 2 * wrong + blank, "shops": collections.Counter(r["shop"][-3:] for r in rows).most_common(4)})
    print(f"{name:42s} n={len(rows):3d} sai={wrong:3d} trống={blank:2d} tối_đa=+{2 * wrong + blank:3d} {result[-1]['shops']}")
print(sum(r["n"] for r in result), sum(r["max_gain"] for r in result))
json.dump({"summary": result, "ids": {k: [r["id"] for r in v] for k, v in counts.items()}}, open(OUT, "w"), ensure_ascii=False, indent=1)
for r in counts["M4 Còn lại: tham số, kỳ, chọn hàm"]:
    print("  ", r["id"][2:8], r["shop"][-3:], r["q"][:62], "|", r["first"][:55].replace("\n", " "))
