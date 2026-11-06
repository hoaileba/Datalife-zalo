from __future__ import annotations

import argparse
import shutil
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Sequence

import openai

from .agent import Reply, openrouter_client
from .column_roles import ReadmeMapper
from .normalize import ColumnMapper, normalize_shop
from .normalize_models import ShopMapping

MAPPING_SEED = 20261104
MIN_PARSE_RATIO = 0.9
SAMPLE_ROWS = 5
MAX_WORKERS = 6


class MapperClient:
    """Cầu nối từ client của agent sang giao diện ColumnMapper cần."""

    def __init__(self, *, model: str) -> None:
        self._complete = openrouter_client(model=model, seed=MAPPING_SEED)

    def complete(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]], *, shop: str) -> Reply:
        try:
            return self._complete(messages, tools)
        except openai.OpenAIError as error:
            raise ValueError(f"{shop}: {type(error).__name__}: {str(error)[:300]}") from None


def prepare_shop(shop: str, dataset: Path, out: Path, mappings: Path | None, model: str) -> tuple[str, tuple[str, ...]]:
    shop_dir = dataset / "data" / shop
    target = out / shop
    cached = ShopMapping.model_validate_json((mappings / shop / "mapping.json").read_text(encoding="utf-8")) if mappings else None
    readme = (shop_dir / "README.md").read_text(encoding="utf-8")
    mapper = None if cached else ReadmeMapper(readme) if model == "readme" else ColumnMapper(MapperClient(model=model), shop=shop, readme=readme)
    if target.exists():
        shutil.rmtree(target)
    reports = normalize_shop(shop=shop, shop_dir=shop_dir, out_dir=target, mapper=mapper, cached=cached, model=model, min_ratio=MIN_PARSE_RATIO, sample_rows=SAMPLE_ROWS, strict=False)
    return shop, tuple(f"{report.mapping.name} {report.stats.rows_kept if report.stats else report.mapping.error}" for report in reports)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Làm sạch dữ liệu shop thành bảng chuẩn; không có --mappings thì model map cột")
    parser.add_argument("--dataset", type=Path, default=Path("public_test"))
    parser.add_argument("--mappings", type=Path, default=None)
    parser.add_argument("--model", default="readme", help="readme là tra cứu tất định, còn lại là tên model để map cột")
    parser.add_argument("--out", type=Path, default=Path("artifacts/norm/public_test"))
    parser.add_argument("--shops", nargs="*", default=None)
    args = parser.parse_args(argv)
    shops = args.shops or sorted(path.name for path in (args.dataset / "data").iterdir() if path.is_dir())
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(prepare_shop, shop, args.dataset, args.out, args.mappings, args.model) for shop in shops]
        for future in futures:
            print(*future.result(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
