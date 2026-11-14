from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
from pydantic import BaseModel, ConfigDict

from datamate.norm import fold_key, parse_datetime, parse_number
from datamate_agent.normalize import SOURCE_COLUMNS, SUBTOTAL, discover, group_heads, load_sources

from .dm import norm

NOTES = (
    "Tables are read from the source files with their ORIGINAL column headers. Only format fixes were applied: header detection; "
    "blank, repeated-header, one-cell note and one-label total rows removed (counts in dropped_rows); partitions of one table "
    "(monthly sheets, files with the same header) concatenated, with \"__source\" naming the origin sheet/file. Numbers, quantities "
    "and dates are parsed from content; when the source held text, \"<col>__raw\" keeps the original (listed only where some cells "
    "did not parse). Quantities written with a unit (\"2 gói\") keep the unit in \"<col>__unit\". Line tables where only the first "
    "line of an order carries the order cells (id, date, status, customer) have those cells filled down to the following lines of "
    "the order (noted on the columns). NOT applied: duplicate removal, status normalization, entity merging, unit conversion: apply "
    "the rulebook and README in code."
)
RULEBOOK_POINTER = "The standard rules are in the cookbook of the system prompt (section 4). The rules of this set that differ from the standard or are new are listed in catalog.rulebook_changes, word for word: they win."
ALL_VALUES_LIMIT = 30
EXAMPLES = 5
PARSE_SHARE = 0.95
FILL_SHARE = 0.99
LOOKUP_LIMIT = 12
LOOKUP_DISTINCT_LIMIT = 5000
LOOKUP_MIN_CHARS = 4
SHEETS_SPELLED_OUT = 3
DATE_WORDS = ("ngay", "date", "thoi gian", "time", "han ", "han su dung", "luc", "gio", "hsd")
ORDER_KEYS = frozenset({"ma don", "ma hoa don", "so hoa don", "so hd", "hd", "ma hd", "order id", "order", "so don", "ma don hang", "so phieu", "ma phieu", "ma bill"})
UNIT_QUANTITY = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*([^\d\s.,+-][^\d]*?)\s*$")
DATE_TEXT = re.compile(r"\d{1,4}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{1,4}")
LEADING_ZERO = re.compile(r"^0\d{5,}$")
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class TableMeta(BaseModel):
    """Nguồn và các sửa định dạng của một bảng trong catalog."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    source_files: tuple[str, ...]
    dropped_rows: dict[str, int] = {}
    abouts: dict[str, str] = {}


def slug(text: str) -> str:
    folded = fold_key(CAMEL.sub("_", text))
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", folded)).strip("_") or "table"


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or (isinstance(value, str) and not value.strip()) or value is pd.NaT


def _drop_rows(frame: pd.DataFrame, columns: Sequence[str]) -> tuple[pd.DataFrame, dict[str, int]]:
    cells = frame[list(columns)]
    filled = ~cells.map(_blank)
    count = filled.sum(axis=1)
    header_keys = [fold_key(column) for column in columns]
    repeated = cells.apply(lambda row: sum(fold_key(str(value)) == key for value, key in zip(row, header_keys) if not _blank(value)), axis=1) * 2 >= count.clip(lower=1)
    texts = cells.map(lambda value: isinstance(value, str) and parse_number(value) is None)
    total = (texts & filled & cells.map(lambda value: isinstance(value, str) and SUBTOTAL.match(fold_key(value)) is not None)).any(axis=1) & ((texts & filled).sum(axis=1) == 1)
    note = (count == 1) & (texts & filled).any(axis=1) & (len(columns) >= 3)
    reasons = {"blank": count == 0, "header": (count > 0) & repeated, "total": (count > 0) & ~repeated & total, "note": (count > 0) & ~repeated & ~total & note}
    dropped = {key: int(mask.sum()) for key, mask in reasons.items() if int(mask.sum())}
    keep = ~(reasons["blank"] | reasons["header"] | reasons["total"] | reasons["note"])
    return frame[keep].reset_index(drop=True), dropped


def _parse_column(name: str, series: pd.Series) -> tuple[dict[str, pd.Series], str]:
    present = series[~series.map(_blank)]
    if present.empty:
        return {name: series}, "empty"
    if pd.api.types.is_bool_dtype(series):
        return {name: series}, "bool"
    if pd.api.types.is_datetime64_any_dtype(series):
        return {name: series}, "date"
    if pd.api.types.is_numeric_dtype(series):
        if any(word in fold_key(name) for word in DATE_WORDS) and present.between(30000, 60000).all():
            return {name: pd.to_datetime(series.map(lambda value: parse_datetime(value)), errors="coerce")}, "date; parsed from Excel serial"
        return {name: _tidy_number(pd.to_numeric(series, errors="coerce"))}, "number"
    texts = present.map(lambda value: value if isinstance(value, str) else str(value))
    if texts.map(lambda text: LEADING_ZERO.match(text.strip()) is not None).mean() > 0.5:
        return {name: series}, "text"
    if any(word in fold_key(name) for word in DATE_WORDS) or texts.map(lambda text: DATE_TEXT.search(text) is not None).mean() >= PARSE_SHARE or present.map(lambda value: hasattr(value, "year")).mean() >= PARSE_SHARE:
        moments = present.map(lambda value: parse_datetime(value))
        if moments.notna().mean() >= PARSE_SHARE:
            return _with_raw(name, series, pd.to_datetime(series.map(lambda value: None if _blank(value) else parse_datetime(value)), errors="coerce"), moments.notna().all(), "date; parsed from text")
    numbers = present.map(lambda value: parse_number(value))
    if numbers.notna().mean() >= PARSE_SHARE:
        parsed = _tidy_number(pd.to_numeric(series.map(lambda value: None if _blank(value) else parse_number(value)), errors="coerce"))
        return _with_raw(name, series, parsed, numbers.notna().all(), "number; parsed from text")
    units = texts.map(lambda text: UNIT_QUANTITY.match(text))
    if (numbers.notna() | units.map(bool)).mean() >= PARSE_SHARE and units.map(bool).any():
        amount = series.map(lambda value: None if _blank(value) else parse_number(value) if parse_number(value) is not None else (float(UNIT_QUANTITY.match(str(value)).group(1).replace(",", ".")) if UNIT_QUANTITY.match(str(value)) else None))
        unit = series.map(lambda value: UNIT_QUANTITY.match(str(value)).group(2).strip() if not _blank(value) and UNIT_QUANTITY.match(str(value)) else None)
        parsed, about = _with_raw(name, series, _tidy_number(pd.to_numeric(amount, errors="coerce")), amount[~series.map(_blank)].notna().all(), "quantity; parsed from text")
        return {**parsed, f"{name}__unit": unit}, about
    return {name: series}, "text"


def _with_raw(name: str, original: pd.Series, parsed: pd.Series, complete: bool, about: str) -> tuple[dict[str, pd.Series], str]:
    return ({name: parsed} if complete else {name: parsed, f"{name}__raw": original}), about


def _tidy_number(series: pd.Series) -> pd.Series:
    present = series.dropna()
    if not present.empty and (present % 1 == 0).all() and series.notna().all():
        return series.astype("int64")
    return series.astype("float64")


def _fill_down(frame: pd.DataFrame, columns: Sequence[str]) -> tuple[pd.DataFrame, tuple[str, ...]]:
    ids = [column for column in columns if fold_key(column) in ORDER_KEYS]
    if not ids:
        return frame, ()
    blank_id = frame[ids[0]].map(_blank)
    if not blank_id.any() or blank_id.all():
        return frame, ()
    order_cells = tuple(column for column in columns if (frame[column].map(_blank) == blank_id).mean() >= FILL_SHARE)
    groups = frame["__source"]
    filled = frame.copy()
    for column in order_cells:
        filled[column] = frame[column].where(~frame[column].map(_blank)).groupby(groups).ffill()
    return filled, order_cells


def load_shop(shop_dir: Path) -> tuple[dict[str, pd.DataFrame], dict[str, TableMeta]]:
    """Các bảng của một shop với tên cột gốc, chỉ sửa định dạng; mỗi bảng kèm nguồn và các dòng đã bỏ."""
    frames: dict[str, pd.DataFrame] = {}
    metas: dict[str, TableMeta] = {}
    groups = group_heads(discover(shop_dir, sample_rows=5))
    per_file = Counter(group.sources[0].file for group in groups)
    for group in groups:
        first = group.sources[0]
        stem = Path(first.file).stem
        base = slug(first.sheet) if first.file.endswith((".sqlite", ".sqlite3", ".db")) else slug(stem) if per_file[first.file] == 1 else f"{slug(stem)}_{slug(first.sheet or 'sheet')}"
        name = base
        while name in frames:
            name = f"{name}_2"
        raw = load_sources(shop_dir, group.sources)
        raw["__source"] = [f"{file}:{sheet}" if sheet else file for file, sheet in zip(raw["source_file"], raw["source_sheet"])]
        columns = [column for column in raw.columns if column not in SOURCE_COLUMNS and column != "__source"]
        kept, dropped = _drop_rows(raw.drop(columns=list(SOURCE_COLUMNS)), columns)
        kept, filled_cells = _fill_down(kept, columns)
        parsed: dict[str, pd.Series] = {}
        abouts: dict[str, str] = {}
        for column in columns:
            produced, about = _parse_column(column, kept[column])
            parsed.update(produced)
            abouts[column] = about + ("; filled down from the first line of the order" if column in filled_cells else "")
            abouts.update({extra: (f"unit written in \"{column}\"" if extra.endswith("__unit") else f"original text of \"{column}\"") for extra in produced if extra != column})
        sources = sorted({f"{source.file}:{source.sheet}" if source.sheet else source.file for source in group.sources})
        if len(group.sources) > SHEETS_SPELLED_OUT and len({source.file for source in group.sources}) == 1:
            sources = [f"{first.file} ({len(group.sources)} sheets)"]
        parsed["__source"] = kept["__source"]
        abouts["__source"] = "origin sheet/file of the row"
        frames[name] = pd.DataFrame(parsed)
        metas[name] = TableMeta(name=name, source_files=tuple(sources), dropped_rows=dropped, abouts=abouts)
    return frames, metas


def load_calendar(path: Path) -> pd.DataFrame:
    calendar = pd.read_csv(path)
    calendar["date"] = pd.to_datetime(calendar["date"])
    if "lunar_leap" in calendar.columns:
        calendar["lunar_leap"] = calendar["lunar_leap"].map(lambda value: str(value).strip().lower() in {"1", "true", "yes"})
    return calendar


def _jsonable(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d") if value == value.normalize() else value.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def profile_column(name: str, series: pd.Series, about: str) -> dict[str, Any]:
    present = series.dropna()
    info: dict[str, Any] = {"name": name, "type": str(series.dtype), "about": about, "distinct": int(present.nunique())}
    if len(series) - len(present):
        info["blank"] = int(len(series) - len(present))
    if not present.empty and (pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series) or pd.api.types.is_datetime64_any_dtype(series)):
        info["range"] = f"{_jsonable(present.min())} .. {_jsonable(present.max())}"
    counts = present.value_counts()
    if len(counts) <= ALL_VALUES_LIMIT:
        info["all_values"] = [[_jsonable(value), int(count)] for value, count in counts.items()]
    else:
        info["examples"] = [_jsonable(value) for value in counts.index[:EXAMPLES]]
    return info


def schemas(frames: dict[str, pd.DataFrame], metas: dict[str, TableMeta], calendar: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    for name, frame in {**frames, "calendar": calendar}.items():
        meta = metas.get(name, TableMeta(name="calendar", source_files=("calendar.csv",)))
        empty = [column for column in frame.columns if frame[column].map(_blank).all()]
        entry: dict[str, Any] = {"table": name, "rows": int(len(frame)), "source_files": list(meta.source_files)}
        if meta.dropped_rows:
            entry["dropped_rows"] = dict(meta.dropped_rows)
        duplicates = int(frame.duplicated().sum())
        if duplicates:
            entry["exact_duplicate_rows"] = duplicates
        abouts = dict(meta.abouts)
        if name == "calendar":
            abouts = {column: ("date" if column == "date" else "bool" if column == "lunar_leap" else "number; 1=Monday .. 7=Sunday" if column == "weekday" else "number" if pd.api.types.is_numeric_dtype(frame[column]) else "text") for column in frame.columns}
        entry["columns"] = [profile_column(column, frame[column].where(~frame[column].map(_blank)), abouts.get(column, "text")) for column in frame.columns if column not in empty]
        if empty:
            entry["empty_columns"] = empty
        out.append(entry)
    return out


def data_lookup(question: str, frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """Giá trị chữ trong dữ liệu xuất hiện nguyên cụm trong câu hỏi (so sau khi bỏ dấu, chữ thường)."""
    asked = f" {re.sub(r'[^a-z0-9%]+', ' ', norm(question))} "
    hits = []
    for table, frame in frames.items():
        for column in frame.columns:
            if column == "__source" or column.endswith(("__raw", "__unit")) or not pd.api.types.is_object_dtype(frame[column]):
                continue
            counts = frame[column].dropna().map(str).value_counts()
            if len(counts) > LOOKUP_DISTINCT_LIMIT:
                continue
            for value, rows in counts.items():
                key = re.sub(r"[^a-z0-9%]+", " ", norm(value)).strip()
                if len(key) >= LOOKUP_MIN_CHARS and not key.replace(" ", "").isdigit() and f" {key} " in asked:
                    hits.append({"table": table, "column": column, "value": value, "rows": int(rows), "match": "mentioned in question"})
    hits.sort(key=lambda hit: -len(hit["value"]))
    return hits[:LOOKUP_LIMIT]


def _rule_rows(rulebook: str) -> list[tuple[str, str, str]]:
    section = ""
    rows = []
    for line in rulebook.splitlines():
        if line.startswith("#"):
            section = line.lstrip("#").strip()
        elif line.startswith("|") and not line.startswith("|---") and not line.startswith("| Luật"):
            rows.append((section, line.split("|")[1].strip(), line.strip()))
    return rows


def rulebook_changes(split_rulebook: str, standard_rulebook: str, cookbook_titles: frozenset[str]) -> list[str]:
    """Dòng luật của split khác nguyên văn luật chuẩn, hoặc chưa có mục trong cookbook."""
    standard = {row for _, _, row in _rule_rows(standard_rulebook)}
    return [f"{section}: {row}" for section, title, row in _rule_rows(split_rulebook) if row not in standard or title not in cookbook_titles]


def build_catalog(*, shop_dir: Path, frames: dict[str, pd.DataFrame], metas: dict[str, TableMeta], calendar: pd.DataFrame, changes: Sequence[str]) -> dict[str, Any]:
    readme = shop_dir / "README.md"
    return {
        "notes": NOTES,
        "schemas": schemas(frames, metas, calendar),
        "documents": [{"name": "README.md", "text": readme.read_text(encoding="utf-8") if readme.exists() else ""}, {"name": "rulebook.md", "text": RULEBOOK_POINTER}],
        "rulebook_changes": list(changes),
    }


def cookbook_titles(system_prompt: str) -> frozenset[str]:
    return frozenset(re.findall(r"\[([^\]]+)\]", system_prompt))


def shop_questions(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["business_id"])].append(row)
    return grouped
