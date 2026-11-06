from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from datamate.clean import COLUMN_TYPES
from datamate.norm import fold_key, parse_datetime, parse_money, parse_number, squeeze
from datamate.tabio import read_head, read_sqlite, read_table, sheet_names, sqlite_tables
from pydantic import Field

from .normalize_models import (
    FrozenModel,
    ORDER_STATUSES,
    TABLE_KINDS,
    ColumnRole,
    OrderStatus,
    RejectedRole,
    Role,
    ShopMapping,
    TableKind,
    TableMapping,
    TableSource,
)

if TYPE_CHECKING:
    import pandas as pd

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "normalize.md"
TABLE_SUFFIXES = {".xlsx": "excel", ".xlsm": "excel", ".csv": "csv", ".sqlite": "sqlite", ".sqlite3": "sqlite", ".db": "sqlite"}
HIDDEN_FILES = frozenset({"README.md", "questions.jsonl"})
WALK_IN_KEYS = frozenset({"khach le", "le", "kl"})
SUBTOTAL = re.compile(r"^(tong|cong|total|subtotal|ghi chu)\b")
SOURCE_COLUMNS = ("source_file", "source_sheet", "source_row")
HEAD_ROWS = 15
STATUS_LIMIT = 60
CELL_LIMIT = 40
UNKNOWN_STATUS = "unknown"
DEFAULT_NOTE_STATUS: OrderStatus = "hoàn thành"
NOTE_COLUMN_KEYS = frozenset({"ghi chu", "note", "notes"})
WORDY_ROLES = frozenset({"note", "status", "customer_name", "item_name", "item_group", "unit", "supplier"})
ALIAS_MIN_SHARE = 0.2
NUMERIC_TEXT = re.compile(r"^[\d\s.,+-]+$")
YEAR_IN_NAME = re.compile(r"(20\d{2})")
DAY_MONTH = re.compile(r"^(\d{1,2})[/-](\d{1,2})$")
NOT_REVENUE: tuple[OrderStatus, ...] = ("huỷ", "trả hàng")
LINE_AMOUNT_TOLERANCE = 0.01
LINE_AMOUNT_MIN_SHARE = 0.5
ORDER_DERIVED_FIELDS = ("status_norm", "is_walk_in")
REPEATED_IN_ORDER_SHARE = 0.8

ROLES: dict[str, Role] = {
    "order_id": Role(level="order", meaning="mã đơn, số hoá đơn, STT đơn"),
    "order_date": Role(level="order", meaning="ngày hoặc ngày giờ lập đơn bán"),
    "order_time": Role(level="order", meaning="thời điểm đặt đơn có giờ, khi sổ có cột riêng ngoài cột ngày"),
    "customer_group": Role(level="order", meaning="nhóm khách"),
    "status": Role(level="order", meaning="trạng thái đơn"),
    "customer_name": Role(level="order", meaning="tên khách"),
    "customer_code": Role(level="order", meaning="mã khách"),
    "customer_phone": Role(level="order", meaning="số điện thoại khách"),
    "staff": Role(level="order", meaning="nhân viên bán hoặc lập phiếu, mã hoặc tên"),
    "payment_method": Role(level="order", meaning="hình thức thanh toán"),
    "channel": Role(level="order", meaning="nguồn hoặc kênh bán"),
    "order_discount": Role(level="order", meaning="giảm giá cả đơn"),
    "shipping_fee": Role(level="order", meaning="phí giao hàng"),
    "order_total": Role(level="order", meaning="tổng khách phải trả cho cả đơn"),
    "paid_amount": Role(level="order", meaning="số khách đã trả"),
    "debt_amount": Role(level="order", meaning="số khách còn nợ"),
    "note": Role(level="order", meaning="ghi chú"),
    "line_no": Role(level="line", meaning="số thứ tự dòng hàng trong đơn"),
    "item_code": Role(level="line", meaning="mã hàng"),
    "item_name": Role(level="line", meaning="tên hàng"),
    "item_group": Role(level="line", meaning="nhóm hoặc loại hàng"),
    "unit": Role(level="line", meaning="đơn vị tính"),
    "quantity": Role(level="line", meaning="số lượng theo đơn vị ghi trên dòng"),
    "base_quantity": Role(level="line", meaning="số lượng đã quy về đơn vị cơ bản"),
    "unit_price": Role(level="line", meaning="đơn giá bán"),
    "line_discount": Role(level="line", meaning="giảm giá của riêng dòng hàng"),
    "line_amount": Role(level="line", meaning="thành tiền của một dòng hàng"),
    "unit_cost": Role(level="line", meaning="giá vốn một đơn vị"),
    "document_id": Role(level="record", meaning="số phiếu thu, phiếu nhập, phiếu chi"),
    "base_unit": Role(level="record", meaning="đơn vị cơ bản của mặt hàng"),
    "big_unit": Role(level="record", meaning="đơn vị lớn của mặt hàng"),
    "unit_factor": Role(level="record", meaning="số đơn vị nhỏ trong một đơn vị lớn"),
    "stock": Role(level="record", meaning="tồn kho"),
    "lot_id": Role(level="line", meaning="số lô"),
    "item_alias": Role(level="line", meaning="cách ghi tắt tên hàng"),
    "expiry_date": Role(level="line", meaning="hạn sử dụng"),
    "active_ingredient": Role(level="record", meaning="hoạt chất"),
    "is_prescription": Role(level="record", meaning="thuốc kê đơn"),
    "due_date": Role(level="order", meaning="hạn thanh toán"),
    "record_date": Role(level="record", meaning="ngày của phiếu ở bảng không phải đơn bán"),
    "amount": Role(level="record", meaning="số tiền của phiếu"),
    "supplier": Role(level="record", meaning="nhà cung cấp"),
}


if set(ROLES) - set(COLUMN_TYPES):
    raise ValueError(f"roles without a column type in datamate.clean: {sorted(set(ROLES) - set(COLUMN_TYPES))}")


class TableHead(FrozenModel):
    """Phần đầu của một bảng gốc: đủ để LLM map cột mà không đọc cả file."""

    source: TableSource
    columns: tuple[str, ...]
    sample: tuple[tuple[str, ...], ...]


class HeaderGroup(FrozenModel):
    """Các bảng gốc cùng một header trong một shop; map một lần, gộp thành một bảng sạch."""

    columns: tuple[str, ...]
    sources: tuple[TableSource, ...]
    sample: tuple[tuple[str, ...], ...]


class MappingProposal(FrozenModel):
    """Đề xuất của LLM qua tool set_mapping, chưa qua kiểm."""

    kind: TableKind
    columns: tuple[ColumnRole, ...] = ()


class TableStats(FrozenModel):
    """Số đếm của một lần làm sạch: đọc bao nhiêu, loại bao nhiêu vì lý do gì, ô nào không đọc được."""

    rows_read: int
    rows_kept: int
    dropped: dict[str, int] = Field(default_factory=dict)
    filled_cells: int = 0
    unreadable: dict[str, int] = Field(default_factory=dict)
    date_ranges: dict[str, tuple[str, str]] = Field(default_factory=dict)
    status_counts: dict[str, int] = Field(default_factory=dict)
    walk_in_rows: int | None = None
    walk_in_spellings: dict[str, int] = Field(default_factory=dict)
    alias_source: str | None = None
    alias_rows: int = 0
    merged_spellings: int = 0
    orders_from: str | None = None


class TableReport(FrozenModel):
    """Một bảng sạch đã ghi ra đĩa cùng mapping và số đếm của nó."""

    mapping: TableMapping
    stats: TableStats | None
    clean_file: str | None
    dropped_file: str | None


def discover(shop_dir: Path, *, sample_rows: int) -> tuple[TableHead, ...]:
    heads: list[TableHead] = []
    for path in sorted(p for p in shop_dir.rglob("*") if p.is_file() and p.name not in HIDDEN_FILES):
        fmt_kind = TABLE_SUFFIXES.get(path.suffix.lower())
        if fmt_kind is None:
            continue
        relative = path.relative_to(shop_dir).as_posix()
        if fmt_kind == "sqlite":
            for table in sqlite_tables(path):
                frame = read_sqlite(path, table)
                heads.append(_head(TableSource(file=relative, sheet=table), tuple(map(str, frame.columns)), frame, sample_rows))
            continue
        sheets: Sequence[str] = ("",) if fmt_kind == "csv" else sheet_names(path)
        for sheet in sheets:
            header_row, columns, body = read_head(path, sheet=sheet or 0, rows=HEAD_ROWS + sample_rows)
            if columns:
                heads.append(_head(TableSource(file=relative, sheet=sheet, header_row=header_row), columns, body, sample_rows))
    return tuple(heads)


def group_heads(heads: Sequence[TableHead]) -> tuple[HeaderGroup, ...]:
    order: list[tuple[str, ...]] = []
    sources: dict[tuple[str, ...], list[TableSource]] = {}
    samples: dict[tuple[str, ...], tuple[tuple[str, ...], ...]] = {}
    for head in heads:
        if head.columns not in sources:
            order.append(head.columns)
            sources[head.columns] = []
            samples[head.columns] = head.sample
        sources[head.columns].append(head.source)
    return tuple(HeaderGroup(columns=columns, sources=tuple(sources[columns]), sample=samples[columns]) for columns in order)


class ColumnMapper:
    """Hỏi LLM loại bảng, vai trò cột và nghĩa giá trị trạng thái; mọi câu trả lời còn qua kiểm deterministic."""

    def __init__(self, client: Any, *, shop: str, readme: str) -> None:
        self._client = client
        self._shop = shop
        self._readme = readme
        roles = "\n".join(f"- `{name}` ({COLUMN_TYPES[name]}): {role.meaning}" for name, role in ROLES.items())
        self._system = PROMPT_PATH.read_text(encoding="utf-8").replace("{{roles}}", roles)

    def propose(self, group: HeaderGroup, *, feedback: str | None = None) -> MappingProposal:
        tool = _mapping_tool(group.columns)
        lines = [
            f"Bảng: {_describe_sources(group.sources)}",
            "",
            f"Header và {len(group.sample)} dòng mẫu:",
            "",
            _markdown_rows(group.columns, group.sample),
            "",
            "Chỉ dùng tên cột có trong header ở trên.",
            "",
            "README của shop, mô tả nghĩa từng cột (tin mô tả này hơn tên cột):",
            "",
            self._readme,
        ]
        if feedback is not None:
            lines += ["", "Lần map trước bị code kiểm từ chối:", feedback, "Map lại toàn bộ bảng."]
        arguments = self._call(system=self._system, user="\n".join(lines), tool=tool)
        kind = arguments.get("kind") if arguments.get("kind") in TABLE_KINDS else "other"
        return MappingProposal.model_validate({**arguments, "kind": kind})

    def statuses(self, values: Sequence[tuple[str, int]]) -> dict[str, OrderStatus | None]:
        names = [value for value, _ in values]
        tool = _status_tool(names)
        system = (
            "Bạn map giá trị cột trạng thái đơn của một cửa hàng sang 4 trạng thái của rulebook: `hoàn thành`, `huỷ`, "
            "`trả hàng` (kể cả trả một phần), `đang giao`. `Đã giao` là `hoàn thành`. `Không giao được`, giao thất bại là "
            "`huỷ`: khách chưa nhận hàng. `Đang xử lý`, `Chưa giao` là `đang giao`. Giá trị không nói gì về trạng thái đơn, như ghi chú "
            "thường, thì `unknown`. Chỉ trả lời bằng một lời gọi tool `set_status_map`, đủ mọi giá trị."
        )
        user = "Giá trị (số dòng):\n" + "\n".join(f"- {value!r} ({count})" for value, count in values)
        arguments = self._call(system=system, user=user, tool=tool)
        out: dict[str, OrderStatus | None] = {}
        for entry in arguments.get("values", ()):
            status = entry.get("status")
            out[str(entry.get("value"))] = status if status in ORDER_STATUSES else None
        missing = [name for name in names if name not in out]
        if missing:
            raise ValueError(f"status map misses values: {missing[:5]}")
        return out

    def _call(self, *, system: str, user: str, tool: dict[str, Any]) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        name = tool["function"]["name"]
        for _ in range(2):
            reply = self._client.complete(messages, (tool,), shop=self._shop)
            call = next((c for c in reply.tool_calls if c.name == name), None)
            if call is not None:
                parsed = json.loads(call.arguments or "{}")
                if not isinstance(parsed, dict):
                    raise ValueError(f"{name} arguments must be an object")
                return parsed
            messages += [{"role": "assistant", "content": reply.content or ""}, {"role": "user", "content": f"Trả lời bằng đúng một lời gọi tool `{name}`."}]
        raise ValueError(f"model did not call {name}")


def check_roles(frame: pd.DataFrame, proposed: Sequence[ColumnRole], *, min_ratio: float) -> tuple[tuple[ColumnRole, ...], tuple[RejectedRole, ...]]:
    accepted: list[ColumnRole] = []
    rejected: list[RejectedRole] = []
    used_roles: dict[str, str] = {}
    used_columns: set[str] = set()
    for item in proposed:
        problem = None
        if item.role not in ROLES:
            problem = "unknown role"
        elif item.column not in frame.columns:
            problem = "column not in table"
        elif item.role in used_roles:
            problem = f"role already given to {used_roles[item.role]!r}"
        elif item.column in used_columns:
            problem = "column already has a role"
        else:
            problem = _type_problem(frame[item.column], item.role, min_ratio, _year_hints(frame)) or _level_problem(frame, item, proposed)
        if problem is None:
            accepted.append(item)
            used_roles[item.role] = item.column
            used_columns.add(item.column)
        else:
            rejected.append(RejectedRole(column=item.column, role=item.role, reason=problem))
    return tuple(accepted), tuple(rejected)


def load_sources(shop_dir: Path, sources: Sequence[TableSource]) -> pd.DataFrame:
    import pandas as pd

    frames = []
    for source in sources:
        path = shop_dir / source.file
        if TABLE_SUFFIXES.get(path.suffix.lower()) == "sqlite":
            frame = read_sqlite(path, source.sheet).astype(object)
            frame = frame.assign(source_row=range(1, len(frame) + 1))
        else:
            frame = read_table(path, sheet=source.sheet or 0, header_row=source.header_row, row_numbers=True)
        frames.append(frame.assign(source_file=source.file, source_sheet=source.sheet))
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    data = [c for c in out.columns if c not in SOURCE_COLUMNS]
    return out[data + list(SOURCE_COLUMNS)]


def distinct_values(frame: pd.DataFrame, column: str, *, limit: int) -> tuple[tuple[str, int], ...]:
    counts = Counter(squeeze(value) for value in frame[column] if not _blank(value))
    return tuple(counts.most_common(limit))


def clean_table(frame: pd.DataFrame, mapping: TableMapping) -> tuple[pd.DataFrame, pd.DataFrame, TableStats]:
    import pandas as pd

    roles = {item.role: item.column for item in mapping.roles}
    data = [c for c in frame.columns if c not in SOURCE_COLUMNS]
    reasons = pd.Series([None] * len(frame), index=frame.index, dtype=object)
    reasons[_repeated_header_mask(frame, data)] = "repeated_header"
    reasons[reasons.isna() & _subtotal_mask(frame, roles, data)] = "subtotal"
    mapped = [roles[name] for name in ROLES if name in roles]
    if mapped:
        reasons[reasons.isna() & frame[mapped].apply(lambda column: column.map(_blank)).all(axis=1)] = "empty"
    kept = frame[reasons.isna()]
    dropped = [frame[reasons.notna()].assign(drop_reason=reasons[reasons.notna()])]
    filled = 0
    if mapping.kind == "sales" and "order_id" in roles:
        kept, filled = _fill_orders(kept, roles)
        duplicate = kept.duplicated(subset=data, keep="first")
        dropped.append(kept[duplicate].assign(drop_reason="duplicate_in_order"))
        kept = kept[~duplicate]
    dropped_frame = pd.concat(dropped).sort_index()
    clean, unreadable, ranges = _typed(kept, roles)
    status_counts: dict[str, int] = {}
    if mapping.kind == "sales" and "status" in roles:
        norm = kept[roles["status"]].map(lambda v: None if _blank(v) else mapping.status_map.get(squeeze(v)))
        clean["status_norm"] = norm.values
        status_counts = {str(key): int(value) for key, value in Counter(None if _blank(v) else squeeze(v) for v in kept[roles["status"]]).most_common()}
    elif mapping.status_note_column is not None:
        clean["status_norm"] = _status_from_note(kept, mapping, order_column=roles.get("order_id")).values
        status_counts = {squeeze(v): int(n) for v, n in Counter(v for v in kept[mapping.status_note_column] if not _blank(v) and mapping.status_map.get(squeeze(v))).most_common()}
    walk_in_rows = None
    spellings: dict[str, int] = {}
    name_column = roles.get("customer_name") or roles.get("customer_code")
    if name_column is not None:
        walk_in = kept[name_column].map(lambda v: _blank(v) or fold_key(v) in WALK_IN_KEYS)
        clean["is_walk_in"] = walk_in.values
        walk_in_rows = int(walk_in.sum())
        spellings = {("(trống)" if _blank(v) else squeeze(v)): int(n) for v, n in Counter(kept[name_column][walk_in].map(lambda v: None if _blank(v) else v)).most_common()}
    stats = TableStats(
        rows_read=len(frame),
        rows_kept=len(clean),
        dropped={str(k): int(v) for k, v in Counter(dropped_frame["drop_reason"]).most_common()} if len(dropped_frame) else {},
        filled_cells=filled,
        unreadable=unreadable,
        date_ranges=ranges,
        status_counts=status_counts,
        walk_in_rows=walk_in_rows,
        walk_in_spellings=spellings,
    )
    return clean, dropped_frame, stats


def normalize_shop(
    *,
    shop: str,
    shop_dir: Path,
    out_dir: Path,
    mapper: ColumnMapper | None,
    cached: ShopMapping | None,
    model: str,
    min_ratio: float,
    sample_rows: int,
    strict: bool,
) -> tuple[TableReport, ...]:
    if mapper is None and cached is None:
        raise ValueError(f"no mapper and no cached mapping for {shop}")
    out_dir.mkdir(parents=True, exist_ok=True)
    previous = {table.columns: table for table in cached.tables} if cached is not None else {}
    reports: list[TableReport] = []
    cleaned: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    used_names: set[str] = set()
    for group in group_heads(discover(shop_dir, sample_rows=sample_rows)):
        known = previous.get(group.columns)
        try:
            mapping, frame = _map_group(group, shop_dir=shop_dir, mapper=mapper, known=known, used_names=used_names, min_ratio=min_ratio)
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            if strict:
                raise
            name = _unique_name("other", group.sources, used_names)
            reports.append(TableReport(mapping=TableMapping(name=name, kind="other", columns=group.columns, sources=group.sources, error=f"{type(error).__name__}: {error}"), stats=None, clean_file=None, dropped_file=None))
            continue
        clean, dropped, stats = clean_table(frame, mapping)
        cleaned[mapping.name] = (clean, dropped)
        reports.append(TableReport(mapping=mapping, stats=stats, clean_file=f"{mapping.name}.csv", dropped_file=f"{mapping.name}.dropped.csv" if len(dropped) else None))
    reports = expand_aliases(reports, cleaned)
    reports = merge_item_spellings(reports, cleaned)
    reports = join_order_fields(reports, cleaned)
    add_derived_columns(cleaned)
    for name, (clean, dropped) in cleaned.items():
        clean.to_csv(out_dir / f"{name}.csv", index=False, encoding="utf-8")
        dropped_path = out_dir / f"{name}.dropped.csv"
        dropped_path.unlink(missing_ok=True)
        if len(dropped):
            dropped.to_csv(dropped_path, index=False, encoding="utf-8")
    shop_mapping = ShopMapping(shop=shop, model=model, tables=tuple(report.mapping for report in reports))
    (out_dir / "mapping.json").write_text(shop_mapping.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "PROFILE.md").write_text(render_profile(shop=shop, reports=reports), encoding="utf-8")
    return tuple(reports)


def expand_aliases(reports: Sequence[TableReport], cleaned: dict[str, tuple[pd.DataFrame, pd.DataFrame]]) -> list[TableReport]:
    """Sổ ghi tên hàng tắt: danh mục có mã tắt và tên đầy đủ thì đổi `item_name` sang tên đầy đủ, giữ tên ghi ở `item_name_raw`."""
    catalogs: list[tuple[str, dict[str, tuple[str, str | None]]]] = []
    for report in reports:
        if report.mapping.kind != "catalog" or report.stats is None:
            continue
        frame = cleaned[report.mapping.name][0]
        if {"item_code", "item_name"} <= set(frame.columns):
            groups = frame["item_group"] if "item_group" in frame.columns else [None] * len(frame)
            aliases = {fold_key(code): (str(name), group) for code, name, group in zip(frame["item_code"], frame["item_name"], groups) if not _blank(code) and not _blank(name)}
            catalogs.append((report.mapping.name, aliases))
    out: list[TableReport] = []
    for report in reports:
        out.append(report)
        if report.mapping.kind != "sales" or report.stats is None:
            continue
        clean, dropped = cleaned[report.mapping.name]
        if "item_name" not in clean.columns or "item_code" in clean.columns or not len(clean):
            continue
        keys = clean["item_name"].map(lambda v: None if _blank(v) else fold_key(v))
        for catalog, aliases in catalogs:
            hits = keys.map(lambda key: key in aliases)
            if hits.mean() < ALIAS_MIN_SHARE:
                continue
            expanded = clean.assign(item_name_raw=clean["item_name"], item_name=[aliases[key][0] if hit else name for key, hit, name in zip(keys, hits, clean["item_name"])])
            if "item_group" not in expanded.columns:
                expanded["item_group"] = [aliases[key][1] if hit else None for key, hit in zip(keys, hits)]
            cleaned[report.mapping.name] = (expanded, dropped)
            stats = report.stats.model_copy(update={"alias_source": catalog, "alias_rows": int(hits.sum())})
            out[-1] = report.model_copy(update={"stats": stats})
            break
    return out


def merge_item_spellings(reports: Sequence[TableReport], cleaned: dict[str, tuple[pd.DataFrame, pd.DataFrame]]) -> list[TableReport]:
    """Một mặt hàng nhiều cách viết về một tên: ưu tiên cách viết của danh mục, không có thì cách viết nhiều dòng nhất."""
    catalog: dict[str, str] = {}
    counts: dict[str, Counter[str]] = {}
    for report in reports:
        frame = cleaned[report.mapping.name][0] if report.mapping.name in cleaned else None
        if frame is None or "item_name" not in frame.columns:
            continue
        for value in frame["item_name"]:
            if _blank(value):
                continue
            key = fold_key(value)
            counts.setdefault(key, Counter())[str(value)] += 1
            if report.mapping.kind == "catalog":
                catalog.setdefault(key, str(value))
    chosen = {key: catalog.get(key, spelled.most_common(1)[0][0]) for key, spelled in counts.items()}
    out: list[TableReport] = []
    for report in reports:
        out.append(report)
        if report.mapping.name not in cleaned or report.stats is None:
            continue
        frame, dropped = cleaned[report.mapping.name]
        if "item_name" not in frame.columns:
            continue
        names = [value if _blank(value) else chosen[fold_key(value)] for value in frame["item_name"]]
        changed = sum(1 for old, new in zip(frame["item_name"], names) if not _blank(old) and old != new)
        if not changed:
            continue
        raw = frame["item_name_raw"] if "item_name_raw" in frame.columns else frame["item_name"]
        cleaned[report.mapping.name] = (frame.assign(item_name_raw=raw, item_name=names), dropped)
        out[-1] = report.model_copy(update={"stats": report.stats.model_copy(update={"merged_spellings": changed})})
    return out


def join_order_fields(reports: Sequence[TableReport], cleaned: dict[str, tuple[pd.DataFrame, pd.DataFrame]]) -> list[TableReport]:
    """Bảng dòng hàng không ghi trạng thái, ngày đơn: lấy từ bảng đơn cùng shop theo order_id."""
    donors = [r.mapping.name for r in reports if r.mapping.kind == "sales" and r.mapping.name in cleaned and {"order_id", "status_norm"} <= set(cleaned[r.mapping.name][0].columns)]
    out: list[TableReport] = []
    for report in reports:
        out.append(report)
        name = report.mapping.name
        if report.mapping.kind != "sales" or name not in cleaned or report.stats is None or name in donors or not donors:
            continue
        frame, dropped = cleaned[name]
        if "order_id" not in frame.columns:
            continue
        donor = cleaned[donors[0]][0].drop_duplicates("order_id").set_index("order_id")
        keys = frame["order_id"].astype(str)
        donor.index = donor.index.astype(str)
        if keys.isin(donor.index).mean() < ALIAS_MIN_SHARE:
            continue
        fields = [name for name, role in ROLES.items() if role.level == "order" and name != "order_id"] + list(ORDER_DERIVED_FIELDS)
        added = {field: keys.map(donor[field]).values for field in fields if field in donor.columns and field not in frame.columns}
        cleaned[name] = (frame.assign(**added), dropped)
        out[-1] = report.model_copy(update={"stats": report.stats.model_copy(update={"orders_from": donors[0]})})
    return out


def add_derived_columns(cleaned: dict[str, tuple[pd.DataFrame, pd.DataFrame]]) -> None:
    import pandas as pd

    for name, (frame, dropped) in list(cleaned.items()):
        extra: dict[str, Any] = {}
        date_column = "order_date" if "order_date" in frame.columns else "record_date" if "record_date" in frame.columns else None
        if date_column is not None:
            moments = pd.to_datetime(frame[date_column], format="ISO8601")
            extra["year"] = moments.dt.year.astype("Int64").values
            extra["month"] = moments.dt.month.astype("Int64").values
            timed = pd.to_datetime(frame["order_time"], format="ISO8601") if "order_time" in frame.columns else moments
            if timed.dt.hour.gt(0).any():
                extra["hour"] = timed.dt.hour.astype("Int64").values
        if "status_norm" in frame.columns:
            extra["is_revenue"] = (~frame["status_norm"].isin(NOT_REVENUE)).values
        cleaned[name] = (frame.assign(**extra), dropped)


def render_profile(*, shop: str, reports: Sequence[TableReport]) -> str:
    lines = [f"# PROFILE {shop}", "", f"Bảng sạch nằm ở `work/clean/{shop}/`. Cột chuẩn mang tên vai trò; cột không map giữ tên gốc; `source_file`, `source_sheet`, `source_row` trỏ về dòng gốc. Có sẵn `year`, `month` từ cột ngày, và `is_revenue` = True nếu đơn không huỷ, không trả.", ""]
    for report in reports:
        mapping = report.mapping
        lines.append(f"## `{mapping.name}` · {mapping.kind}")
        lines.append("")
        lines.append(f"- Nguồn: {_describe_sources(mapping.sources)}")
        if mapping.error is not None:
            lines += [f"- **Không làm sạch được**: {mapping.error}", ""]
            continue
        stats = report.stats
        if stats is not None:
            dropped = ", ".join(f"{reason} {count:,}" for reason, count in stats.dropped.items()) or "không"
            lines.append(f"- File: `{report.clean_file}` {stats.rows_kept:,} dòng · đọc {stats.rows_read:,} · loại: {dropped}" + (f" → `{report.dropped_file}`" if report.dropped_file else ""))
            if stats.filled_cells:
                lines.append(f"- Đã điền {stats.filled_cells:,} ô trống của dòng tiếp nối từ dòng đầu đơn")
        lines.append("- Cột chuẩn ← cột gốc:")
        for item in sorted(mapping.roles, key=lambda r: list(ROLES).index(r.role)):
            extra = ""
            if stats is not None and item.role in stats.date_ranges:
                start, end = stats.date_ranges[item.role]
                extra = f" ({start} → {end})"
            if stats is not None and stats.unreadable.get(item.role):
                extra += f" · {stats.unreadable[item.role]:,} ô không đọc được, để trống"
            lines.append(f"  - `{item.role}` ← `{item.column}`{extra}")
        unmapped = [c for c in mapping.columns if c not in {item.column for item in mapping.roles}]
        if unmapped:
            lines.append("- Giữ tên gốc: " + ", ".join(f"`{c}`" for c in unmapped))
        for item in mapping.rejected:
            lines.append(f"- Bỏ đề xuất `{item.role}` ← `{item.column}`: {item.reason}")
        if stats is not None and stats.orders_from is not None:
            lines.append(f"- `status_norm`, `order_date`, `is_revenue`, `year`, `month` lấy từ `{stats.orders_from}` theo `order_id`")
        if stats is not None and stats.merged_spellings:
            lines.append(f"- `item_name`: {stats.merged_spellings:,} dòng đã gộp về một cách viết; tên ghi trong sổ ở `item_name_raw`")
        if stats is not None and stats.alias_source is not None:
            lines.append(f"- `item_name`: {stats.alias_rows:,} dòng đã đổi tên tắt sang tên đầy đủ theo `{stats.alias_source}`; tên ghi trong sổ ở `item_name_raw`")
        if mapping.status_note_column is not None:
            lines.append(f"- `status_norm` suy từ cột `{mapping.status_note_column}` vì sổ không có cột trạng thái; ghi chú không nhắc trạng thái là `{DEFAULT_NOTE_STATUS}`")
        if stats is not None and stats.status_counts:
            parts = [f"`{value}` → {mapping.status_map.get(value) or 'không rõ'} ({count:,})" for value, count in stats.status_counts.items()]
            lines.append("- `status_norm`: " + "; ".join(parts))
        if stats is not None and stats.walk_in_rows is not None:
            spell = ", ".join(f"`{k}` {v:,}" for k, v in list(stats.walk_in_spellings.items())[:6])
            lines.append(f"- `is_walk_in`: {stats.walk_in_rows:,} dòng khách lẻ ({spell or 'không có'})")
        lines.append("")
    return "\n".join(lines)


def _map_group(
    group: HeaderGroup,
    *,
    shop_dir: Path,
    mapper: ColumnMapper | None,
    known: TableMapping | None,
    used_names: set[str],
    min_ratio: float,
) -> tuple[TableMapping, pd.DataFrame]:
    frame = load_sources(shop_dir, group.sources)
    if known is not None and known.error is None:
        used_names.add(known.name)
        return known.model_copy(update={"sources": group.sources}), frame
    if mapper is None:
        raise ValueError(f"no cached mapping for header {list(group.columns)[:6]} and no mapper")
    data = [c for c in frame.columns if c not in SOURCE_COLUMNS]
    checked = frame[~_repeated_header_mask(frame, data)]
    proposal = mapper.propose(group)
    roles, rejected = check_roles(checked, proposal.columns, min_ratio=min_ratio)
    feedback = _feedback(proposal.kind, roles, rejected)
    if feedback is not None:
        retry = mapper.propose(group, feedback=feedback)
        retry_roles, retry_rejected = check_roles(checked, retry.columns, min_ratio=min_ratio)
        if len(retry_roles) >= len(roles):
            proposal, roles, rejected = retry, retry_roles, retry_rejected
    roles = _promote_line_amount(checked, roles)
    status_map: dict[str, OrderStatus | None] = {}
    note_column = None
    if proposal.kind == "sales":
        status_column = next((item.column for item in roles if item.role == "status"), None)
        note_column = None if status_column is not None else _note_column(roles, data)
        source_column = status_column or note_column
        values = distinct_values(checked, source_column, limit=STATUS_LIMIT) if source_column is not None else ()
        status_map = mapper.statuses(values) if values else {}
    name = _unique_name(proposal.kind, group.sources, used_names)
    mapping = TableMapping(name=name, kind=proposal.kind, columns=group.columns, sources=group.sources, roles=roles, rejected=rejected, status_map=status_map, status_note_column=note_column)
    return mapping, frame


def _promote_line_amount(frame: pd.DataFrame, roles: tuple[ColumnRole, ...]) -> tuple[ColumnRole, ...]:
    """Cột `order_total` xấp xỉ số lượng × đơn giá trên đa số dòng thật ra là thành tiền của dòng."""
    by_role = {item.role: item.column for item in roles}
    if "line_amount" in by_role or not {"order_total", "quantity", "unit_price"} <= set(by_role):
        return roles
    matches = total = 0
    for amount, quantity, price in zip(frame[by_role["order_total"]], frame[by_role["quantity"]], frame[by_role["unit_price"]]):
        money, count, unit = parse_money(amount), parse_number(quantity), parse_money(price)
        if money is None or count is None or unit is None:
            continue
        total += 1
        matches += abs(money - count * unit) <= LINE_AMOUNT_TOLERANCE * max(abs(money), 1)
    if not total or matches / total < LINE_AMOUNT_MIN_SHARE:
        return roles
    return tuple(ColumnRole(column=item.column, role="line_amount") if item.role == "order_total" else item for item in roles)


def _note_column(roles: Sequence[ColumnRole], data: Sequence[str]) -> str | None:
    mapped = next((item.column for item in roles if item.role == "note"), None)
    return mapped or next((column for column in data if fold_key(column) in NOTE_COLUMN_KEYS), None)


def _feedback(kind: TableKind, roles: Sequence[ColumnRole], rejected: Sequence[RejectedRole]) -> str | None:
    lines = [f"- `{item.role}` ← `{item.column}`: {item.reason}" for item in rejected]
    given = {item.role for item in roles}
    if kind == "sales" and not given & {"order_id", "order_date", "line_amount", "order_total"}:
        lines.append("- kind `sales` nhưng không cột nào là mã đơn, ngày đơn hay tiền đơn: xem lại kind")
    return "\n".join(lines) if lines else None


def _fill_orders(frame: pd.DataFrame, roles: dict[str, str]) -> tuple[pd.DataFrame, int]:
    order_column = roles["order_id"]
    fill = [order_column] + [roles[name] for name, role in ROLES.items() if role.level == "order" and name in roles and name != "order_id"]
    out = frame.copy()
    blank_before = out[fill].apply(lambda column: column.map(_blank))
    group_id = out[order_column].ffill()
    for column in fill:
        out[column] = out.groupby(group_id, sort=False)[column].ffill() if column != order_column else group_id
    blank_after = out[fill].apply(lambda column: column.map(_blank))
    return out, int((blank_before & ~blank_after).to_numpy().sum())


def _year_hints(frame: pd.DataFrame) -> list[int | None]:
    if "source_file" not in frame.columns or "source_sheet" not in frame.columns:
        return [None] * len(frame)
    found: dict[tuple[Any, Any], int | None] = {}
    out: list[int | None] = []
    for pair in zip(frame["source_file"], frame["source_sheet"]):
        if pair not in found:
            match = YEAR_IN_NAME.search(f"{pair[1]} {pair[0]}")
            found[pair] = int(match.group(1)) if match else None
        out.append(found[pair])
    return out


def _moment(value: Any, year: int | None) -> datetime | None:
    moment = parse_datetime(value)
    if moment is not None or year is None or not isinstance(value, str):
        return moment
    match = DAY_MONTH.match(value.strip())
    if match is None:
        return None
    try:
        return datetime(year, int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def _status_from_note(frame: pd.DataFrame, mapping: TableMapping, *, order_column: str | None) -> pd.Series:
    """Rulebook §8: sổ không có cột trạng thái thì đọc Ghi chú; ghi chú không nhắc trạng thái là đơn hoàn thành."""
    named = frame[mapping.status_note_column].map(lambda v: None if _blank(v) else mapping.status_map.get(squeeze(v)))
    if order_column is not None:
        named = named.groupby(frame[order_column].values, sort=False).transform(lambda s: s.dropna().iloc[0] if s.notna().any() else None)
    return named.map(lambda v: DEFAULT_NOTE_STATUS if v is None or v != v else v)


def _typed(frame: pd.DataFrame, roles: dict[str, str]) -> tuple[pd.DataFrame, dict[str, int], dict[str, tuple[str, str]]]:
    import pandas as pd

    out = pd.DataFrame(index=frame.index)
    unreadable: dict[str, int] = {}
    ranges: dict[str, tuple[str, str]] = {}
    for name in ROLES:
        if name not in roles:
            continue
        dtype = COLUMN_TYPES[name]
        values = frame[roles[name]].tolist()
        if dtype == "date":
            moments = [None if _blank(v) else _moment(v, year) for v, year in zip(values, _year_hints(frame))]
            known = [m for m in moments if m is not None]
            timed = any(m.hour or m.minute or m.second for m in known)
            pattern = "%Y-%m-%d %H:%M:%S" if timed else "%Y-%m-%d"
            parsed: list[Any] = [None if m is None else m.strftime(pattern) for m in moments]
            out[name] = pd.Series(parsed, index=frame.index, dtype=object)
            if known:
                ranges[name] = (min(known).strftime(pattern), max(known).strftime(pattern))
        elif dtype == "money":
            parsed = [None if _blank(v) else parse_money(v) for v in values]
            out[name] = pd.array(parsed, dtype="Int64")
        elif dtype == "number":
            parsed = [None if _blank(v) else parse_number(v) for v in values]
            out[name] = pd.array(parsed, dtype="Float64")
        else:
            parsed = [None if _blank(v) else _text(v, identifier=dtype == "id") for v in values]
            out[name] = pd.Series(parsed, index=frame.index, dtype=object)
        bad = sum(1 for raw, value in zip(values, parsed) if value is None and not _blank(raw))
        if bad:
            unreadable[name] = bad
    mapped_columns = set(roles.values())
    for column in frame.columns:
        if column in mapped_columns or column in SOURCE_COLUMNS:
            continue
        target = column if column not in ROLES and column not in ("status_norm", "is_walk_in") else f"{column} (gốc)"
        out[target] = frame[column].values
    for column in SOURCE_COLUMNS:
        out[column] = frame[column].values
    return out.reset_index(drop=True), unreadable, ranges


def _repeated_header_mask(frame: pd.DataFrame, data: Sequence[str]) -> pd.Series:
    names = {str(c).strip().casefold() for c in data}

    def is_header(row: pd.Series) -> bool:
        cells = [squeeze(v).casefold() for v in row.tolist() if not _blank(v)]
        return len(cells) >= 2 and all(cell in names for cell in cells)

    return frame[list(data)].apply(is_header, axis=1).astype(bool) if len(frame) else frame.index.to_series().astype(bool)


def _subtotal_mask(frame: pd.DataFrame, roles: dict[str, str], data: Sequence[str]) -> pd.Series:
    checked = [c for c in data if c != roles.get("note")]
    key_column = roles.get("order_id") or roles.get("document_id")
    date_column = roles.get("order_date") or roles.get("record_date")
    item_column = roles.get("item_name")
    quantity_column = roles.get("quantity")

    def is_subtotal(row: pd.Series) -> bool:
        marked = {c for c in checked if isinstance(row[c], str) and SUBTOTAL.match(fold_key(row[c]))}
        if not marked:
            return False
        if key_column is not None and key_column not in marked and not _blank(row[key_column]):
            return False
        if key_column is None and date_column is not None and date_column not in marked and parse_datetime(row[date_column]) is not None:
            return False
        if marked == {item_column} and quantity_column is not None and not _blank(row[quantity_column]):
            return False
        return True

    return frame.apply(is_subtotal, axis=1).astype(bool) if len(frame) else frame.index.to_series().astype(bool)


def _type_problem(series: pd.Series, role: str, min_ratio: float, hints: Sequence[int | None]) -> str | None:
    dtype = COLUMN_TYPES[role]
    values = [v for v in series.tolist() if not _blank(v)]
    if not values:
        return "all cells empty"
    if role in WORDY_ROLES:
        numeric = sum(1 for v in values if NUMERIC_TEXT.match(str(v)))
        if numeric / len(values) >= min_ratio:
            return f"{numeric:,} of {len(values):,} cells are only digits, e.g. {[squeeze(v) for v in values[:2]]}; role {role} holds words"
    if dtype in ("id", "text"):
        return None
    if dtype == "date":
        bad = [v for v, year in zip(series.tolist(), hints) if not _blank(v) and _moment(v, year) is None]
    else:
        parse = {"money": parse_money, "number": parse_number}[dtype]
        bad = [v for v in values if parse(v) is None]
    ratio = 1 - len(bad) / len(values)
    if ratio < min_ratio:
        return f"only {ratio:.0%} of {len(values):,} cells read as {dtype}, e.g. {[squeeze(v) for v in bad[:3]]}"
    return None


def _level_problem(frame: pd.DataFrame, item: ColumnRole, proposed: Sequence[ColumnRole]) -> str | None:
    """Thành tiền của một dòng phải đổi theo dòng: cột lặp nguyên trong đơn nhiều dòng là tiền cấp đơn."""
    order_column = next((other.column for other in proposed if other.role == "order_id"), None)
    if item.role != "line_amount" or order_column is None or order_column not in frame.columns:
        return None
    groups = frame.groupby(frame[order_column].ffill(), sort=False)[item.column]
    sizes = groups.size()
    multi = sizes[sizes > 1].index
    if not len(multi):
        return None
    repeated = groups.nunique(dropna=True).loc[multi].le(1).mean()
    return f"{repeated:.0%} of multi-line orders repeat one value, this column is an order amount" if repeated >= REPEATED_IN_ORDER_SHARE else None


def _head(source: TableSource, columns: tuple[str, ...], body: pd.DataFrame, sample_rows: int) -> TableHead:
    rows = []
    for _, row in body.iterrows():
        cells = tuple(_cell(row[c]) for c in columns)
        if any(cells):
            rows.append(cells)
        if len(rows) == sample_rows:
            break
    return TableHead(source=source, columns=columns, sample=tuple(rows))


def _mapping_tool(columns: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "set_mapping",
            "description": "Loại bảng và vai trò chuẩn của các cột chắc chắn map được.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(TABLE_KINDS)},
                    "columns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"column": {"type": "string", "enum": list(columns)}, "role": {"type": "string", "enum": list(ROLES)}},
                            "required": ["column", "role"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["kind", "columns"],
                "additionalProperties": False,
            },
        },
    }


def _status_tool(values: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "set_status_map",
            "description": "Nghĩa theo rulebook của từng giá trị trạng thái.",
            "parameters": {
                "type": "object",
                "properties": {
                    "values": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"value": {"type": "string", "enum": list(values)}, "status": {"type": "string", "enum": [*ORDER_STATUSES, UNKNOWN_STATUS]}},
                            "required": ["value", "status"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["values"],
                "additionalProperties": False,
            },
        },
    }


def _unique_name(kind: str, sources: Sequence[TableSource], used: set[str]) -> str:
    first = sources[0]
    stem = _slug(Path(first.file).stem) if len(sources) == 1 else ""
    sheet = _slug(first.sheet) if first.sheet and len(sources) == 1 and _slug(first.sheet) != stem else ""
    base = "_".join(part for part in (kind, stem, sheet) if part)
    name, index = base, 2
    while name in used:
        name, index = f"{base}_{index}", index + 1
    used.add(name)
    return name


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", fold_key(text)).strip("_")


def _describe_sources(sources: Sequence[TableSource]) -> str:
    def one(source: TableSource) -> str:
        where = f"`{source.file}`" + (f" sheet `{source.sheet}`" if source.sheet else "")
        return where + (f" (header dòng {source.header_row + 1})" if source.header_row else "")

    if len(sources) <= 3:
        return "; ".join(one(s) for s in sources)
    return "; ".join(one(s) for s in sources[:2]) + f"; … {len(sources) - 2} bảng khác cùng header"


def _markdown_rows(columns: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    def line(cells: Sequence[str]) -> str:
        return "| " + " | ".join(cell.replace("|", "/") for cell in cells) + " |"

    return "\n".join([line(columns), line(["---"] * len(columns)), *(line(row) for row in rows)])


def _cell(value: Any) -> str:
    return "" if _blank(value) else squeeze(value)[:CELL_LIMIT]


def _text(value: Any, *, identifier: bool) -> str:
    if identifier and isinstance(value, float) and value.is_integer():
        return str(int(value))
    return squeeze(value)


def _blank(value: Any) -> bool:
    import pandas as pd

    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False
