from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

    from .periods import Period

COLUMN_TYPES: dict[str, str] = {
    "order_id": "id",
    "order_date": "date",
    "status": "text",
    "customer_name": "text",
    "customer_code": "id",
    "customer_phone": "text",
    "staff": "text",
    "payment_method": "text",
    "channel": "text",
    "order_discount": "money",
    "shipping_fee": "money",
    "order_total": "money",
    "paid_amount": "money",
    "debt_amount": "money",
    "note": "text",
    "line_no": "number",
    "item_code": "id",
    "item_name": "text",
    "item_name_raw": "text",
    "item_group": "text",
    "unit": "text",
    "quantity": "number",
    "base_quantity": "number",
    "unit_price": "money",
    "line_discount": "money",
    "line_amount": "money",
    "unit_cost": "money",
    "document_id": "id",
    "record_date": "date",
    "amount": "money",
    "supplier": "text",
    "status_norm": "text",
    "is_walk_in": "bool",
    "source_row": "int",
}


def load(path: Path | str) -> pd.DataFrame:
    """Đọc một bảng sạch của tầng chuẩn hoá: cột ngày là datetime64, tiền là Int64, số là Float64."""
    import pandas as pd

    target = Path(path)
    if target.suffix != ".csv" or not target.exists():
        raise ValueError(f"no clean table at {target}, see PROFILE.md for the table names")
    frame = pd.read_csv(target, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8")
    for column in frame.columns:
        kind = COLUMN_TYPES.get(column)
        if kind == "date":
            frame[column] = pd.to_datetime(frame[column], format="ISO8601")
        elif kind in ("money", "int"):
            frame[column] = pd.to_numeric(frame[column]).astype("Int64")
        elif kind == "number":
            frame[column] = pd.to_numeric(frame[column]).astype("Float64")
        elif kind == "bool":
            frame[column] = frame[column].map({"True": True, "False": False}).astype("boolean")
    return frame


def in_period(moments: pd.Series, period: Period) -> pd.Series:
    """Mặt nạ các dòng có ngày nằm trong kỳ, cả hai đầu; dùng cho cột ngày của bảng sạch."""
    import pandas as pd

    days = pd.to_datetime(moments).dt.normalize()
    return (days >= pd.Timestamp(period.start)) & (days <= pd.Timestamp(period.end))


def on_day(moments: pd.Series, day: date) -> pd.Series:
    """Mặt nạ các dòng có ngày đúng bằng một ngày."""
    import pandas as pd

    return pd.to_datetime(moments).dt.normalize() == pd.Timestamp(day)
