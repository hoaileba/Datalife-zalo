from __future__ import annotations

import argparse
import os
import shutil
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Sequence

import openai
import pandas as pd
from pydantic import BaseModel, ConfigDict

from .column_roles import ReadmeMapper
from .concepts import write_concepts
from .llm import BACKENDS, openai_client
from .normalize import ColumnMapper, normalize_shop
from .normalize_models import ShopMapping

MAPPING_SEED = 20261104
MIN_PARSE_RATIO = 0.9
SAMPLE_ROWS = 5
MAX_WORKERS = 6


class ToolCall(BaseModel):
    """Một lời gọi tool khi map cột bằng LLM."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    arguments: str


class Reply(BaseModel):
    """Câu trả lời của LLM map cột."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str | None
    tool_calls: tuple[ToolCall, ...]


class MapperClient:
    """Client có tool calling, chỉ dùng khi map cột bằng LLM thay vì ReadmeMapper."""

    def __init__(self, *, backend: str, model: str) -> None:
        self._model = model
        self._client = openai_client(backend=backend, timeout=300, max_retries=2)

    def complete(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]], *, shop: str) -> Reply:
        try:
            response = self._client.chat.completions.create(model=self._model, messages=list(messages), tools=list(tools), tool_choice="required", temperature=0, seed=MAPPING_SEED)
        except openai.OpenAIError as error:
            raise ValueError(f"{shop}: {type(error).__name__}: {str(error)[:300]}") from None
        message = response.choices[0].message
        calls = tuple(ToolCall(id=call.id, name=call.function.name, arguments=call.function.arguments or "") for call in (message.tool_calls or ()))
        return Reply(content=message.content, tool_calls=calls)


README_CONVERSION = re.compile(r"\*\*Hàng theo \S+\*\*: (.+?) bán theo (\S+), 1 \S+ = (\d+) (\S+?)[;.\s]")


def write_readme_conversions(readme: str, target: Path) -> None:
    """Quy đổi chỉ ghi trong README, dạng `Hàng theo bó: A, B bán theo bó, 1 bó = 10 cây`, thành một bảng catalog."""
    rows = [(item.strip(), f"{unit}={factor} {base}") for names, unit, factor, base in README_CONVERSION.findall(readme) for item in names.split(",")]
    if rows:
        pd.DataFrame(rows, columns=["item_name", "Quy đổi"]).to_csv(target / "catalog_readme_conversions.csv", index=False, encoding="utf-8")


def prepare_shop(shop: str, dataset: Path, out: Path, mappings: Path | None, model: str, backend: str | None) -> tuple[str, tuple[str, ...]]:
    shop_dir = dataset / "data" / shop
    target = out / shop
    cached = ShopMapping.model_validate_json((mappings / shop / "mapping.json").read_text(encoding="utf-8")) if mappings else None
    readme = (shop_dir / "README.md").read_text(encoding="utf-8")
    mapper = None if cached else ReadmeMapper(readme) if model == "readme" else ColumnMapper(MapperClient(backend=backend or "", model=model), shop=shop, readme=readme)
    if target.exists():
        shutil.rmtree(target)
    reports = normalize_shop(shop=shop, shop_dir=shop_dir, out_dir=target, mapper=mapper, cached=cached, model=model, min_ratio=MIN_PARSE_RATIO, sample_rows=SAMPLE_ROWS, strict=False)
    write_readme_conversions(readme, target)
    write_concepts(readme, target)
    return shop, tuple(f"{report.mapping.name} {report.stats.rows_kept if report.stats else report.mapping.error}" for report in reports)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Làm sạch dữ liệu shop thành bảng chuẩn; không có --mappings thì model map cột")
    parser.add_argument("--dataset", type=Path, default=Path("public_test"))
    parser.add_argument("--mappings", type=Path, default=None)
    parser.add_argument("--model", default="readme", help="readme là tra cứu tất định, còn lại là tên model để map cột")
    parser.add_argument("--backend", choices=sorted(BACKENDS), default=os.environ.get("LLM_BACKEND"), help="chỉ cần khi --model không phải readme")
    parser.add_argument("--out", type=Path, default=Path("artifacts/norm/public_test"))
    parser.add_argument("--shops", nargs="*", default=None)
    args = parser.parse_args(argv)
    shops = args.shops or sorted(path.name for path in (args.dataset / "data").iterdir() if path.is_dir())
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(prepare_shop, shop, args.dataset, args.out, args.mappings, args.model, args.backend) for shop in shops]
        for future in futures:
            print(*future.result(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
