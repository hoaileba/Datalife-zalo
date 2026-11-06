from __future__ import annotations

import json
import re
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, "src")
from datamate.norm import fold_key
from datamate.shop import Shop
from datamate_agent.intents import period_of
from datamate_agent.question_norm import normalize

Q = {json.loads(l)["id"]: json.loads(l) for l in open("train/questions.jsonl", encoding="utf-8")}
G = {json.loads(l)["id"]: json.loads(l) for l in open("train/answers.jsonl", encoding="utf-8")}
PHARMACY = {f"biz_{n}" for n in range(119, 124)}
DELIVERY = {"biz_115", "biz_116", "biz_117", "biz_118"}
tally: dict[str, list[bool]] = {}


def shop_of(q):
    return Shop(f"artifacts/norm/train/{q['business_id']}", as_of=q["as_of_date"], calendar="train/calendar.csv")


def record(group, i, got, skip=False):
    if skip:
        return
    want = G[i].get("answer")
    ok = got == want or (isinstance(got, (int, float)) and isinstance(want, (int, float)) and abs(got - want) < 1e-6)
    tally.setdefault(group, []).append(ok)
    if not ok:
        print("  NO", group, Q[i]["business_id"], i[2:8], Q[i]["question"][:66], "|", str(got)[:44], "| gold", G[i]["type"], str(want)[:44])


def period_for(shop, text):
    code = period_of(normalize(text))
    return eval(code, {"clock": shop.clock}) if code else shop.clock.this_month()


for i, q in Q.items():
    text, shop_id = q["question"].lower(), q["business_id"]
    try:
        if shop_id in DELIVERY and "đợt" in text:
            s = shop_of(q)
            if re.search(r"2 đợt|từ \d đợt|hai đợt", text):
                record("giao hàng", i, s.orders_min_rounds(period_for(s, q["question"]), rounds=2))
            elif re.search(r"mấy đợt|bao nhi\w* đợt|số đợt|bn đợt|soos đợt", text):
                record("giao hàng", i, s.delivery_rounds(period_for(s, q["question"])))
        if shop_id in PHARMACY and re.search(r"lô|hết hạn|hạn dùng", text):
            s = shop_of(q)
            dates = re.findall(r"(\d{2})/(\d{2})/(\d{4})", text)
            start, end = [f"{y}-{m}-{d}" for d, m, y in dates[:2]] if len(dates) >= 2 else (None, None)
            days = re.search(r"(\d+) ngày", text)
            count = int(days.group(1)) if days else None
            if "gần hết hạn" in text or "cận date" in text:
                names = sorted({n for n in s.lines["item_name"].dropna().unique() if fold_key(n) in fold_key(normalize(q["question"]))}, key=len)
                record("lô: hạn gần nhất", i, s.nearest_expiry(names[-1]) if names else "no item")
            elif "tiền vốn" in text:
                record("lô: tiền vốn", i, s.expiring_value(count, start=start, end=end))
            elif "hàng nào" in text or "mặt hàng nào" in text or "kể" in text:
                record("lô: danh sách", i, s.expiring_items(count, start=start, end=end))
            elif re.search(r"mấy lô|bao nhiêu lô|bn lô", text):
                record("lô: số lô", i, s.expiring_lots(count, start=start, end=end))
        if re.search(r"hết hàng|đứt hàng|cháy hàng", text):
            s = shop_of(q)
            dates = re.findall(r"(\d{2})/(\d{2})/(\d{4})", text)
            record("hết hàng", i, s.out_of_stock_count(f"{dates[0][2]}-{dates[0][1]}-{dates[0][0]}" if dates else None))
        if re.search(r"lên giá|tăng giá|đổi giá", text) and "days" not in text and not re.search(r"\d{2}/\d{2}/\d{4}", text):
            s = shop_of(q)
            price = re.search(r"(\d[\d.]*)\s*(?:đ|đồng)", text)
            days = re.search(r"(\d+) ngày", text)
            names = sorted({n for n in s.lines["item_name"].dropna().unique() if fold_key(n) in fold_key(normalize(q["question"]))}, key=len)
            if price and days and names and G[i]["type"] == "percent":
                record("đổi giá theo mức giá", i, s.price_effect(names[-1], price=float(price.group(1).replace(".", "")), days=int(days.group(1))))
    except Exception as error:
        record("lỗi", i, f"EXC {type(error).__name__}: {str(error)[:60]}")
for group, values in tally.items():
    print(f"{group:24s} {sum(values)}/{len(values)}")
