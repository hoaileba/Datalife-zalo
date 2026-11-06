from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code" / "src"))

from datamate import Clock, fmt, in_period, load

CLEAN = ROOT.parents[1] / "artifacts" / "normalize-public" / "clean"
EXCLUDED = ["huỷ", "trả hàng"]


def sales_of(shop: str, *, clock: Clock, table: str):
    frame = load(CLEAN / shop / f"{table}.csv")
    return clock.visible_rows(frame, "order_date")


def revenue(frame, period) -> int:
    ok = ~frame["status_norm"].isin(EXCLUDED) if "status_norm" in frame else True
    rows = frame[ok & in_period(frame["order_date"], period)]
    return fmt.money(int(rows["line_amount"].sum()))


def change(now: int, before: int) -> float:
    return fmt.percent((now - before) / before * 100)


def main() -> int:
    claude = {j["id"]: j for j in map(json.loads, (ROOT / "inputs" / "claude_reference.jsonl").open(encoding="utf-8"))}
    out = {}
    clock = Clock("2025-12-19")
    frame = sales_of("dev_003", clock=clock, table="sales_banhang_tonghop_2025")
    out["q_78a7454fde5d"] = change(revenue(frame, clock.this_month()), revenue(frame, clock.last_month_same_days()))
    clock = Clock("2026-06-10")
    frame = sales_of("dev_004", clock=clock, table="sales_sobanhang")
    out["q_3dd4582ecb10"] = change(revenue(frame, clock.month(2, 2026)), revenue(frame, clock.month(1, 2026)))
    rows = frame[in_period(frame["order_date"], clock.month(5, 2025))]
    out["q_f274c9241995"] = fmt.percent(rows[rows["status_norm"] == "huỷ"]["order_id"].nunique() / rows["order_id"].nunique() * 100)
    clock = Clock("2026-03-23")
    frame = sales_of("dev_014", clock=clock, table="sales_sobanhang")
    out["q_2f8852d2a6bc"] = revenue(frame, clock.year_to_date())
    clock = Clock("2026-08-21")
    frame = sales_of("dev_003", clock=clock, table="sales_banhang_tonghop_2025")
    out["q_1c0ec38b3d82"] = revenue(frame, clock.tet(2026))
    clock = Clock("2026-07-08")
    frame = sales_of("dev_001", clock=clock, table="sales_so_chi_tiet_ban_hang_sheet1")
    months = {m: revenue(frame, clock.month(m, 2026)) for m in (3, 4, 5)}
    out["q_e966e0e6802e"] = fmt.month_answer((2026, max(months, key=months.get)))
    clock = Clock("2026-07-31")
    frame = sales_of("dev_011", clock=clock, table="sales_sobanhang_so_ban_hang")
    rows = frame[~frame["status_norm"].isin(EXCLUDED) & in_period(frame["order_date"], clock.month(7, 2026))] if "status_norm" in frame else frame[in_period(frame["order_date"], clock.month(7, 2026))]
    out["q_a85371a13fe2"] = str(rows.groupby("item_name")["quantity"].sum().idxmax())
    clock = Clock("2025-05-10")
    for qid, mine in out.items():
        want = claude[qid].get("answer")
        print(f"{qid}  control={mine!r:<28} claude={want!r:<20} {'KHỚP' if mine == want else 'LỆCH'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
