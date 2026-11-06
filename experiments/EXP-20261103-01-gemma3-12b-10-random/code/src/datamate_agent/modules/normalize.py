from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from datamate.norm import fold_key, parse_datetime, parse_money, parse_number, squeeze
from datamate.tabio import read_head, read_sqlite, read_table, sheet_names, sqlite_tables
from pydantic import Field

from ..connectors.base import ChatClient
from ..models.config import FrozenModel
from ..models.normalize import (
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

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "normalize.md"
TABLE_SUFFIXES = {".xlsx": "excel", ".xlsm": "excel", ".csv": "csv", ".sqlite": "sqlite", ".sqlite3": "sqlite", ".db": "sqlite"}
HIDDEN_FILES = frozenset({"README.md", "questions.jsonl"})
WALK_IN_KEYS = frozenset({"khach le", "le", "kl"})
SUBTOTAL = re.compile(r"^(tong|cong|total|subtotal|ghi chu)\b")
SOURCE_COLUMNS = ("source_file", "source_sheet", "source_row")
HEAD_ROWS = 15
STATUS_LIMIT = 60
CELL_LIMIT = 40
UNKNOWN_STATUS = "unknown"

ROLES: dict[str, Role] = {
    "order_id": Role(dtype="id", level="order", meaning="mã đơn, số hoá đơn, STT đơn"),
    "order_date": Role(dtype="date", level="order", meaning="ngày hoặc ngày giờ lập đơn bán"),
    "status": Role(dtype="text", level="order", meaning="trạng thái đơn"),
    "customer_name": Role(dtype="text", level="order", meaning="tên khách"),
    "customer_code": Role(dtype="id", level="order", meaning="mã khách"),
    "customer_phone": Role(dtype="text", level="order", meaning="số điện thoại khách"),
    "staff": Role(dtype="text", level="order", meaning="nhân viên bán hoặc lập phiếu, mã hoặc tên"),
    "payment_method": Role(dtype="text", level="order", meaning="hình thức thanh toán"),
    "channel": Role(dtype="text", level="order", meaning="nguồn hoặc kênh bán"),
    "order_discount": Role(dtype="money", level="order", meaning="giảm giá cả đơn"),
    "shipping_fee": Role(dtype="money", level="order", meaning="phí giao hàng"),
    "order_total": Role(dtype="money", level="order", meaning="tổng khách phải trả cho cả đơn"),
    "paid_amount": Role(dtype="money", level="order", meaning="số khách đã trả"),
    "debt_amount": Role(dtype="money", level="order", meaning="số khách còn nợ"),
    "note": Role(dtype="text", level="order", meaning="ghi chú"),
    "line_no": Role(dtype="number", level="line", meaning="số thứ tự dòng hàng trong đơn"),
    "item_code": Role(dtype="id", level="line", meaning="mã hàng"),
    "item_name": Role(dtype="text", level="line", meaning="tên hàng"),
    "item_group": Role(dtype="text", level="line", meaning="nhóm hoặc loại hàng"),
    "unit": Role(dtype="text", level="line", meaning="đơn vị tính"),
    "quantity": Role(dtype="number", level="line", meaning="số lượng"),
    "unit_price": Role(dtype="money", level="line", meaning="đơn giá bán"),
    "line_discount": Role(dtype="money", level="line", meaning="giảm giá của riêng dòng hàng"),
    "line_amount": Role(dtype="money", level="line", meaning="thành tiền của một dòng hàng"),
    "unit_cost": Role(dtype="money", level="line", meaning="giá vốn một đơn vị"),
    "document_id": Role(dtype="id", level="record", meaning="số phiếu thu, phiếu nhập, phiếu chi"),
    "record_date": Role(dtype="date", level="record", meaning="ngày của phiếu ở bảng không phải đơn bán"),
    "amount": Role(dtype="money", level="record", meaning="số tiền của phiếu"),
    "supplier": Role(dtype="text", level="record", meaning="nhà cung cấp"),
}


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

    def __init__(self, client: ChatClient, *, shop: str, readme: str) -> None:
        self._client = client
        self._shop = shop
        self._readme = readme
        roles = "\n".join(f"- `{name}` ({role.dtype}): {role.meaning}" for name, role in ROLES.items())
        self._system = PROMPT_PATH.read_text(encoding="utf-8").replace("{{roles}}", roles)

    def propose(self, group: HeaderGroup) -> MappingProposal:
        tool = _mapping_tool(group.columns)
        user = "\n".join(
            [
                "README của shop:",
                "",
                self._readme.strip(),
                "",
                f"Bảng: {_describe_sources(group.sources)}",
                "",
                f"Header và {len(group.sample)} dòng mẫu:",
                "",
                _markdown_rows(group.columns, group.sample),
            ]
        )
        arguments = self._call(system=self._system, user=user, tool=tool)
        return MappingProposal.model_validate(arguments)

    def statuses(self, values: Sequence[tuple[str, int]]) -> dict[str, OrderStatus | None]:
        names = [value for value, _ in values]
        tool = _status_tool(names)
        system = (
            "Bạn map giá trị cột trạng thái đơn của một cửa hàng sang 4 trạng thái của rulebook: `hoàn thành`, `huỷ`, "
            "`trả hàng` (kể cả trả một phần), `đang giao`. Giá trị không chắc nghĩa thì `unknown`. Chỉ trả lời bằng "
            "một lời gọi tool `set_status_map`, đủ mọi giá trị."
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
            problem = _type_problem(frame[item.column], ROLES[item.role].dtype, min_ratio)
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
    if "status" in roles:
        norm = kept[roles["status"]].map(lambda v: None if _blank(v) else mapping.status_map.get(squeeze(v)))
        clean["status_norm"] = norm.values
        status_counts = {str(key): int(value) for key, value in Counter(None if _blank(v) else squeeze(v) for v in kept[roles["status"]]).most_common()}
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
        clean_path = out_dir / f"{mapping.name}.csv"
        clean.to_csv(clean_path, index=False, encoding="utf-8")
        dropped_path = out_dir / f"{mapping.name}.dropped.csv"
        dropped_path.unlink(missing_ok=True)
        if len(dropped):
            dropped.to_csv(dropped_path, index=False, encoding="utf-8")
        reports.append(TableReport(mapping=mapping, stats=stats, clean_file=clean_path.name, dropped_file=dropped_path.name if len(dropped) else None))
    shop_mapping = ShopMapping(shop=shop, model=model, tables=tuple(report.mapping for report in reports))
    (out_dir / "mapping.json").write_text(shop_mapping.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "PROFILE.md").write_text(render_profile(shop=shop, reports=reports), encoding="utf-8")
    return tuple(reports)


def render_profile(*, shop: str, reports: Sequence[TableReport]) -> str:
    lines = [f"# PROFILE {shop}", "", f"Bảng sạch nằm ở `work/clean/{shop}/`. Cột chuẩn mang tên vai trò; cột không map giữ tên gốc; `source_file`, `source_sheet`, `source_row` trỏ về dòng gốc.", ""]
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
    proposal = mapper.propose(group)
    data = [c for c in frame.columns if c not in SOURCE_COLUMNS]
    checked = frame[~_repeated_header_mask(frame, data)]
    roles, rejected = check_roles(checked, proposal.columns, min_ratio=min_ratio)
    status_map: dict[str, OrderStatus | None] = {}
    status_column = next((item.column for item in roles if item.role == "status"), None)
    if status_column is not None:
        values = distinct_values(checked, status_column, limit=STATUS_LIMIT)
        status_map = mapper.statuses(values) if values else {}
    name = _unique_name(proposal.kind, group.sources, used_names)
    mapping = TableMapping(name=name, kind=proposal.kind, columns=group.columns, sources=group.sources, roles=roles, rejected=rejected, status_map=status_map)
    return mapping, frame


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


def _typed(frame: pd.DataFrame, roles: dict[str, str]) -> tuple[pd.DataFrame, dict[str, int], dict[str, tuple[str, str]]]:
    import pandas as pd

    out = pd.DataFrame(index=frame.index)
    unreadable: dict[str, int] = {}
    ranges: dict[str, tuple[str, str]] = {}
    for name, role in ROLES.items():
        if name not in roles:
            continue
        column = frame[roles[name]]
        blank = column.map(_blank)
        if role.dtype == "date":
            parsed = column.map(lambda v: None if _blank(v) else parse_datetime(v))
            moments = [m for m in parsed if m is not None]
            timed = any(m.hour or m.minute or m.second for m in moments)
            pattern = "%Y-%m-%d %H:%M:%S" if timed else "%Y-%m-%d"
            out[name] = parsed.map(lambda m: None if m is None else m.strftime(pattern))
            if moments:
                ranges[name] = (min(moments).strftime(pattern), max(moments).strftime(pattern))
        elif role.dtype == "money":
            parsed = column.map(lambda v: None if _blank(v) else parse_money(v))
            out[name] = pd.array(parsed.tolist(), dtype="Int64")
        elif role.dtype == "number":
            parsed = column.map(lambda v: None if _blank(v) else parse_number(v))
            out[name] = pd.array(parsed.tolist(), dtype="Float64")
        else:
            parsed = column.map(lambda v: None if _blank(v) else _text(v, identifier=role.dtype == "id"))
            out[name] = parsed
        bad = int((~blank & parsed.isna()).sum())
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


def _type_problem(series: pd.Series, dtype: str, min_ratio: float) -> str | None:
    values = [v for v in series.tolist() if not _blank(v)]
    if not values:
        return "all cells empty"
    if dtype in ("id", "text"):
        return None
    parse = {"date": parse_datetime, "money": parse_money, "number": parse_number}[dtype]
    bad = [v for v in values if parse(v) is None]
    ratio = 1 - len(bad) / len(values)
    if ratio < min_ratio:
        return f"only {ratio:.0%} of {len(values):,} cells read as {dtype}, e.g. {[squeeze(v) for v in bad[:3]]}"
    return None


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
    stem = _slug(Path(first.file).stem)
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
