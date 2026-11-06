from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

class FrozenModel(BaseModel):
    """Gốc của mọi data model tầng chuẩn hoá: frozen, cấm field lạ."""

    model_config = ConfigDict(frozen=True, extra="forbid")


RoleLevel = Literal["order", "line", "record"]
TableKind = Literal["sales", "receipts", "purchases", "inventory", "catalog", "customers", "staff", "expenses", "repairs", "other"]
OrderStatus = Literal["hoàn thành", "huỷ", "trả hàng", "đang giao"]
DropReason = Literal["repeated_header", "subtotal", "empty", "duplicate_in_order"]

TABLE_KINDS: tuple[TableKind, ...] = ("sales", "receipts", "purchases", "inventory", "catalog", "customers", "staff", "expenses", "repairs", "other")
ORDER_STATUSES: tuple[OrderStatus, ...] = ("hoàn thành", "huỷ", "trả hàng", "đang giao")


class Role(FrozenModel):
    """Một cột của mô hình chuẩn: cấp (đơn / dòng hàng / phiếu) và nghĩa; kiểu giá trị nằm ở datamate.clean.COLUMN_TYPES."""

    level: RoleLevel
    meaning: str


class TableSource(FrozenModel):
    """Một bảng gốc: file trong thư mục shop, sheet hoặc bảng sqlite, dòng header."""

    file: str
    sheet: str = ""
    header_row: int = Field(default=0, ge=0)


class ColumnRole(FrozenModel):
    """Cột gốc được gán một vai trò chuẩn."""

    column: str
    role: str


class RejectedRole(FrozenModel):
    """Vai trò LLM đề xuất nhưng trượt kiểm deterministic."""

    column: str
    role: str
    reason: str


class TableMapping(FrozenModel):
    """Mapping của một nhóm bảng cùng header: loại bảng, vai trò từng cột, map giá trị trạng thái."""

    name: str
    kind: TableKind
    columns: tuple[str, ...]
    sources: tuple[TableSource, ...]
    roles: tuple[ColumnRole, ...] = ()
    rejected: tuple[RejectedRole, ...] = ()
    status_map: dict[str, OrderStatus | None] = Field(default_factory=dict)
    status_note_column: str | None = None
    error: str | None = None

    def column_of(self, role: str) -> str | None:
        return next((item.column for item in self.roles if item.role == role), None)


class ShopMapping(FrozenModel):
    """Toàn bộ mapping của một shop; ghi ra mapping.json để chạy lại không cần LLM."""

    shop: str
    model: str
    tables: tuple[TableMapping, ...]
