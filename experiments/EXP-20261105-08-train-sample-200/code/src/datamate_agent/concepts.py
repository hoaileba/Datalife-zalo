from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, ConfigDict

from .column_roles import readme_columns
from .normalize import fold_key

CONCEPTS_FILE = "concepts.json"


class Concept(BaseModel):
    """Một ý nghĩa cột mà helper ngành cần, nhận qua mô tả README hoặc tên cột đã biết."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str | None = None
    headers: tuple[str, ...] = ()
    exact_headers: tuple[str, ...] = ()


CONCEPT_TABLE = (
    Concept(name="delivery_round", description=r"^dot giao", headers=("luot giao", "lan giao")),
    Concept(name="delivery_date", description=r"^ngay giao", headers=("thoi gian giao", "ngay giao hang", "ngay cho")),
    Concept(name="lot_received", description=r"^so luong nhap", headers=("slnhapquydoi",)),
    Concept(name="lot_sold", description=r"^so luong ban lay tu lo", headers=("slquydoi",)),
    Concept(name="lot_returned", description=r"^so luong khach tra lai", headers=("sltraquydoi", "so luong tra")),
    Concept(name="price_date", description=r"^ngay bat dau ap dung gia", headers=("ngay ap dung", "ngayapdung")),
    Concept(name="price_value", description=r"^gia ban ap dung", headers=("gia moi", "giabanle")),
    Concept(name="trade_in_order", headers=("tru vao (stt so ban)",)),
    Concept(name="trade_in_amount", description=r"thu may cu", headers=("gia thu", "thu may cu")),
    Concept(name="machine_id", description=r"^imei", headers=("imei",)),
    Concept(name="warranty_fault", headers=("loi",)),
    Concept(name="warranty_action", headers=("xu ly",)),
    Concept(name="installment_prepaid", headers=("tra truoc",)),
    Concept(name="installment_terms", headers=("so ky",)),
    Concept(name="installment_monthly", headers=("gop/thang",)),
    Concept(name="installment_due_day", headers=("han gop (ngay)",)),
    Concept(name="installment_paid_date", headers=("ngay gop",)),
    Concept(name="installment_paid", headers=("da gop",)),
    Concept(name="debt_paid_date", headers=("ngay tra",)),
    Concept(name="vehicle", description=r"^dong xe va bien so", headers=("xe",)),
    Concept(name="repair_job", description=r"^cac viec da lam", headers=("lam gi",)),
    Concept(name="commission_rate", description=r"phan tram hoa hong", headers=("hoa hong (%)",)),
    Concept(name="item_brand", exact_headers=("hãng",)),
    Concept(name="item_size", description=r"^so cua sua", headers=("so / size",)),
    Concept(name="member_date", description=r"^ngay dang ky", headers=("ngay dang ky",)),
)


def concept_of(column: str, description: str) -> str | None:
    for concept in CONCEPT_TABLE:
        if concept.description is not None and re.search(concept.description, description):
            return concept.name
    key = fold_key(column)
    exact = column.strip().casefold()
    return next((concept.name for concept in CONCEPT_TABLE if key in concept.headers or exact in concept.exact_headers), None)


def table_concepts(table: dict, sections: dict[str, dict[str, str]]) -> dict[str, str]:
    folded = {fold_key(column) for column in table["columns"]}
    section = max(sections.values(), key=lambda known: len(folded & set(known)), default={})
    renamed = {item["column"]: item["role"] for item in table["roles"]}
    found: dict[str, str] = {}
    for column in table["columns"]:
        concept = concept_of(column, section.get(fold_key(column), ""))
        if concept is not None:
            found.setdefault(concept, renamed.get(column, column))
    return found


def write_concepts(readme: str, norm_dir: Path) -> dict[str, dict[str, str]]:
    mapping = json.loads((norm_dir / "mapping.json").read_text(encoding="utf-8"))
    sections = readme_columns(readme)
    concepts = {table["name"]: found for table in mapping["tables"] if (found := table_concepts(table, sections))}
    (norm_dir / CONCEPTS_FILE).write_text(json.dumps(concepts, ensure_ascii=False, indent=1), encoding="utf-8")
    return concepts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ghi concepts.json cho các shop đã chuẩn hoá")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--norm", type=Path, required=True)
    args = parser.parse_args(argv)
    for shop_dir in sorted(path for path in (args.dataset / "data").iterdir() if path.is_dir()):
        concepts = write_concepts((shop_dir / "README.md").read_text(encoding="utf-8"), args.norm / shop_dir.name)
        print(shop_dir.name, sorted({name for found in concepts.values() for name in found}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
