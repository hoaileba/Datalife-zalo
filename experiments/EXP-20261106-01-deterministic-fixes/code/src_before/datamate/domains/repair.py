from __future__ import annotations

import re
from typing import Any

import pandas as pd

from ..norm import fold_key
from ..periods import Period

REPAIR_HELPERS = (
    "repair_count", "repair_amount", "repair_vehicles", "top_repair_model", "commission", "commission_table", "warranty_repairs", "warranty_share",
    "average_ticket", "weekday_average", "busiest_staff", "repeat_vehicles",
)
PLATE = re.compile(r"\d{2}[A-Za-z]\d?-\d{3}\.?\d{2}")
STAFF_PREFIX = re.compile(r"^(?:a|anh|chi|c)[\s.]+")
WARRANTY_NOTE = "bao hanh"
WEEKDAYS = {"thu hai": 0, "thu ba": 1, "thu tu": 2, "thu nam": 3, "thu sau": 4, "thu bay": 5, "chu nhat": 6}


def _model_key(name: str) -> str:
    return fold_key(name.replace("α", "alpha")).replace(" ", "")


def _initials(name: str) -> str:
    return "".join(word[0] for word in fold_key(name).split() if word)


def canonical_models(names: list[str]) -> dict[str, str]:
    """Gộp dòng xe chỉ khác hoa thường hoặc ghi tắt về tên đầy đủ nhất, theo tiền tố, hậu tố hoặc chữ đầu."""
    cleaned = {name: fold_key(name.replace("α", "alpha")) for name in names}
    longest = sorted(set(cleaned.values()), key=lambda text: (-len(text), text))
    out: dict[str, str] = {}
    for name, text in cleaned.items():
        compact = text.replace(" ", "")
        same = next((other for other in longest if other.replace(" ", "") == compact), text)
        wider = [other for other in longest if other != same and " " in other and (other.endswith(f" {same}") or _initials(other) == compact or (" " not in same and other.split()[0].startswith(same) and len(same) >= 2 and not other.startswith(f"{same} ")))]
        wider = wider or [other for other in longest if " " not in other and other != same and other.startswith(same) and len(same) >= 2]
        out[name] = wider[0] if len(wider) == 1 else same
    return out


class RepairMixin:
    """Sổ sửa xe một dòng một phiếu, đọc qua khái niệm vehicle, repair_job, commission_rate."""

    def _repairs(self) -> pd.DataFrame:
        book = self._book("vehicle", "repair_job")
        vehicles = book["vehicle"].astype(str)
        models = vehicles.map(lambda cell: PLATE.sub("", cell).strip())
        canon = canonical_models(sorted(set(models)))
        names = self._staff_names()
        days = pd.to_datetime(book["record_date"], errors="coerce").dt.normalize()
        amount = pd.to_numeric(book["amount"], errors="coerce").fillna(0)
        return book.assign(
            day=days,
            money=amount,
            plate=vehicles.map(lambda cell: (lambda found: found.group(0).replace(".", "").upper() if found else None)(PLATE.search(cell))),
            model=models.map(canon),
            mechanic=book["staff"].map(lambda cell: names.get(_short_name(cell), cell)),
            warranty=book["note"].map(lambda cell: not pd.isna(cell) and WARRANTY_NOTE in fold_key(str(cell))),
            job=book["repair_job"].map(lambda cell: fold_key(str(cell))),
        )

    def _staff_names(self) -> dict[str, str]:
        book = self._book("commission_rate")
        return {fold_key(str(name)).split()[-1]: str(name) for name in book["staff"].dropna()}

    def _repairs_in(self, period: Period) -> pd.DataFrame:
        book = self._repairs()
        return book[(book["day"] >= pd.Timestamp(period.start)) & (book["day"] <= pd.Timestamp(period.end))]

    def repair_count(self, period: Period, *, staff: str | None = None, job: str | None = None) -> int:
        """Số lượt xe trong kỳ, tính cả phiếu bảo hành; lọc theo việc thì không tính phiếu bảo hành."""
        rows = self._repairs_in(period)
        if staff is not None:
            rows = rows[rows["mechanic"].map(lambda name: fold_key(staff) in fold_key(str(name)))]
        if job is not None:
            rows = rows[~rows["warranty"] & rows["job"].str.contains(fold_key(job), regex=False)]
        return len(rows)

    def repair_amount(self, period: Period, *, staff: str | None = None) -> int:
        """Tổng tiền các phiếu trong kỳ."""
        rows = self._repairs_in(period)
        if staff is not None:
            rows = rows[rows["mechanic"].map(lambda name: fold_key(staff) in fold_key(str(name)))]
        return int(rows["money"].sum())

    def repair_vehicles(self, period: Period, *, model: str | None = None) -> int:
        """Số biển số khác nhau mang tới trong kỳ, tính cả xe chỉ tới bảo hành."""
        rows = self._repairs_in(period)
        if model is not None:
            wanted = _model_key(model)
            rows = rows[rows["model"].map(lambda name: _model_key(name) == wanted)]
        return int(rows["plate"].nunique())

    def top_repair_model(self, period: Period) -> str:
        """Dòng xe có tổng tiền sửa cao nhất trong kỳ."""
        totals = self._repairs_in(period).groupby("model")["money"].sum()
        return pd.DataFrame({"value": totals, "tie": totals.index}).sort_values(["value", "tie"], ascending=[False, True]).index[0]

    def _commissions(self, period: Period) -> dict[str, int]:
        rates = self._book("commission_rate")
        percent = dict(zip(rates["staff"].astype(str), pd.to_numeric(rates["commission_rate"], errors="coerce")))
        totals = self._repairs_in(period).groupby("mechanic")["money"].sum()
        return {name: int(amount * percent[name] / 100 + 0.5) for name, amount in totals.items() if name in percent}

    def commission(self, period: Period, *, staff: str) -> int:
        """Tiền hoa hồng của một thợ trong kỳ."""
        return next(amount for name, amount in self._commissions(period).items() if fold_key(staff) in fold_key(name))

    def commission_table(self, period: Period) -> dict[str, Any]:
        """Bảng hoa hồng từng thợ, tiền giảm dần."""
        ranked = sorted(self._commissions(period).items(), key=lambda pair: (-pair[1], pair[0]))
        return {"columns": ["tho", "hoa_hong"], "rows": [[name, amount] for name, amount in ranked]}

    def warranty_repairs(self, period: Period) -> int:
        """Số phiếu bảo hành có ngày trong kỳ."""
        return int(self._repairs_in(period)["warranty"].sum())

    def warranty_share(self, period: Period) -> float:
        """Tỉ lệ bảo hành: phiếu bảo hành chia phiếu có thu tiền trong cùng kỳ."""
        rows = self._repairs_in(period)
        return round(100 * rows["warranty"].sum() / (~rows["warranty"]).sum(), 2)

    def average_ticket(self, period: Period) -> int:
        """Tiền trung bình một phiếu có thu tiền."""
        rows = self._repairs_in(period)
        return int(rows["money"].sum() / (rows["money"] > 0).sum() + 0.5)

    def weekday_average(self, period: Period, weekday: str) -> float:
        """Số lượt xe trung bình một ngày của một thứ trong tuần, chỉ tính các ngày có phiếu."""
        rows = self._repairs_in(period)
        rows = rows[rows["day"].dt.weekday == WEEKDAYS[fold_key(weekday)]]
        return round(len(rows) / rows["day"].nunique(), 2)

    def busiest_staff(self, period: Period) -> str:
        """Thợ có nhiều ngày làm việc nhất trong kỳ, kể cả phiếu bảo hành."""
        days = self._repairs_in(period).groupby("mechanic")["day"].nunique()
        return pd.DataFrame({"value": days, "tie": days.index}).sort_values(["value", "tie"], ascending=[False, True]).index[0]

    def repeat_vehicles(self, period: Period, *, min_visits: int = 2) -> int:
        """Số xe theo biển số có từ min_visits phiếu có thu tiền trong kỳ."""
        rows = self._repairs_in(period)
        return int((rows[~rows["warranty"]]["plate"].value_counts() >= min_visits).sum())


def _short_name(cell: Any) -> str:
    text = STAFF_PREFIX.sub("", fold_key(str(cell))).strip()
    return text.split()[-1] if text else ""
