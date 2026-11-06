from __future__ import annotations

import sys
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, "/Users/lebahoai/Workspace/zalo/2026/experiments/EXP-20261029-01-public-test-submission/code")
from datamate import parse_datetime, parse_money, read_table, sheet_names, squeeze

DATA = "/Users/lebahoai/Workspace/zalo/2026/public_test/data/dev_004/"
VALID = {"hoàn thành", "đã hoàn thành", "đã xong", "đang ship", "đang vận chuyển", "đang giao hàng"}

rows = []
for s in sheet_names(DATA + "SoBanHang.xlsx"):
    raw = pd.read_excel(DATA + "SoBanHang.xlsx", sheet_name=s, header=None, skiprows=2, dtype=object)
    raw.columns = ["kh", "gio", "tg", "ma", "sl", "dvt", "hang", "tt", "gia", "amt", "tong"]
    raw = raw[raw["hang"].notna()].drop_duplicates()
    rows.append(raw)
d = pd.concat(rows, ignore_index=True)
d["ma"] = d["ma"].ffill()
d["neg"] = d["sl"].astype(str).str.strip().str.startswith("-")
ret_orders = set(d.loc[d["neg"], "ma"])
heads = d[d["tt"].notna() & ~d["neg"]].drop_duplicates("ma")
heads = heads[heads["tt"].map(lambda v: squeeze(v).casefold() in VALID) & ~heads["ma"].isin(ret_orders)]
heads["day"] = heads["gio"].map(lambda v: v.date())
heads["tong_v"] = heads["tong"].map(parse_money)

def in_range(frame, a, b):
    return frame[(frame["day"] >= a) & (frame["day"] <= b)]

for y, m, end in [(2025, 1, 31), (2025, 9, 30), (2026, 4, 30), (2025, 11, 30), (2025, 12, 31)]:
    f = in_range(heads, date(y, m, 1), date(y, m, end))
    print("revenue", y, m, int(f["tong_v"].sum()), "avg", round(f["tong_v"].sum() / len(f)), "n", len(f))
f = in_range(heads, date(2025, 6, 1), date(2025, 6, 30)); print("avg 6/2025", round(f["tong_v"].sum() / len(f)))
print("ytd orders 2025-10-05", len(in_range(heads, date(2025, 1, 1), date(2025, 10, 5))))
print("ytd revenue 2025-10-28", int(in_range(heads, date(2025, 1, 1), date(2025, 10, 28))["tong_v"].sum()))

valid_set = set(heads["ma"])
pvc = d[d["ma"].isin(valid_set) & d["hang"].astype(str).str.contains("D50") & ~d["neg"]]
pvc = pvc.merge(heads[["ma", "day"]], on="ma")
pvc = pvc[(pvc["day"] >= date(2026, 5, 1)) & (pvc["day"] <= date(2026, 5, 31))]
qty = sum(float(str(s).split()[0]) * (10 if squeeze(u) == "bó" else 1) for s, u in zip(pvc["sl"], pvc["dvt"]))
print("PVC D50 5/2026 cay", qty, sorted(set(pvc["hang"].map(squeeze))))

g = pd.read_excel(DATA + "SoGiaoHang.xlsx", dtype=object)
g["day"] = g["Thời gian giao"].map(lambda v: parse_datetime(v).date())
for a, b in [(date(2025, 7, 1), date(2025, 7, 31)), (date(2025, 11, 1), date(2025, 11, 30)), (date(2026, 6, 1), date(2026, 6, 10))]:
    gg = g[(g["day"] >= a) & (g["day"] <= b)]
    print("rounds", a, len(gg.groupby(["Số đơn", "Lượt giao"])), "via (order,day)", len(gg.groupby(["Số đơn", "day"])))

h = pd.read_excel(DATA + "SoHanNo.xlsx", dtype=object)
h["due"] = h["Ngày phải trả"].map(lambda v: parse_datetime(v).date())
h["placed"] = [due - timedelta(days=int(k)) for due, k in zip(h["due"], h["Kỳ hạn"])]
for asof in [date(2025, 12, 10), date(2025, 3, 2), date(2025, 4, 15)]:
    hh = h[h["placed"] <= asof]
    print("due after", asof, int((hh["due"] > asof).sum()))
for asof, a, b in [(date(2026, 3, 2), date(2026, 4, 1), date(2026, 4, 30)), (date(2025, 10, 2), date(2025, 11, 1), date(2025, 11, 30)), (date(2026, 1, 5), date(2026, 2, 1), date(2026, 2, 28))]:
    hh = h[h["placed"] <= asof]
    print("due in", a, int(((hh["due"] >= a) & (hh["due"] <= b)).sum()))

p = pd.read_excel(DATA + "SoNhapHang.xlsx", dtype=object)
p["day"] = p["Ngày nhập"].map(lambda v: parse_datetime(v).date())
p1 = p[(p["day"] >= date(2025, 1, 1)) & (p["day"] <= date(2025, 1, 31))]
print("purchase 1/2025 via sl*gia", int(sum(float(s) * parse_money(g_) for s, g_ in zip(p1["SL nhập"], p1["Giá nhập"]))))
