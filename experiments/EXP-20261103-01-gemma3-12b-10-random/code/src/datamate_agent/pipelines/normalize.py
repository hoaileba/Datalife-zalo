from __future__ import annotations

import argparse
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Sequence

from ..connectors import ChatClient, OpenRouterClient
from ..models import ConnectorConfig, RunConfig, load_run_config, run_env
from ..models.normalize import ShopMapping
from ..modules.normalize import ColumnMapper, TableReport, normalize_shop
from ..modules.paths import WorkLayout
from ..utils.events import EventLog, configure_console


class NormalizePipeline:
    """Ghép khám phá, map cột và làm sạch cho từng shop; ghi `clean/<shop>/` trong output_dir."""

    def __init__(self, config: RunConfig, *, client: ChatClient | None, events: EventLog, env: str, remap: bool) -> None:
        if config.normalize is None:
            raise ValueError("config has no normalize section")
        self._config = config
        self._settings = config.normalize
        self._client = client
        self._events = events
        self._env = env
        self._remap = remap
        self._layout = WorkLayout(config.output_dir)

    def shops(self) -> tuple[str, ...]:
        if self._config.shops:
            return self._config.shops
        return tuple(sorted(p.name for p in (self._config.dataset_root / "data").iterdir() if p.is_dir()))

    def run(self) -> dict[str, tuple[TableReport, ...] | str]:
        shops = self.shops()
        self._events.emit("normalize_start", shops=list(shops), model=self._settings.model.name, remap=self._remap)
        with ThreadPoolExecutor(max_workers=self._settings.parallel_shops) as pool:
            results = dict(zip(shops, pool.map(self._run_shop, shops)))
        self._events.emit("normalize_end", shops=len(shops), failed=[shop for shop, result in results.items() if isinstance(result, str)])
        return results

    def _run_shop(self, shop: str) -> tuple[TableReport, ...] | str:
        shop_dir = self._config.dataset_root / "data" / shop
        out_dir = self._layout.clean(shop)
        cache_path = out_dir / "mapping.json"
        cached = None if self._remap or not cache_path.exists() else ShopMapping.model_validate_json(cache_path.read_text(encoding="utf-8"))
        mapper = None
        if self._client is not None:
            readme = shop_dir / "README.md"
            mapper = ColumnMapper(self._client, shop=shop, readme=readme.read_text(encoding="utf-8") if readme.exists() else "")
        self._events.emit("normalize_shop_start", shop=shop, cached=cached is not None)
        try:
            reports = normalize_shop(
                shop=shop,
                shop_dir=shop_dir,
                out_dir=out_dir,
                mapper=mapper,
                cached=cached,
                model=self._settings.model.name,
                min_ratio=self._settings.min_parse_ratio,
                sample_rows=self._settings.sample_rows,
                strict=self._env == "dev",
            )
        except Exception as error:
            if self._env == "dev":
                raise
            trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            self._events.emit("normalize_shop_error", shop=shop, error=repr(error), traceback=trace)
            return trace
        for report in reports:
            stats = report.stats
            self._events.emit(
                "normalize_table",
                shop=shop,
                table=report.mapping.name,
                kind=report.mapping.kind,
                sources=len(report.mapping.sources),
                roles=len(report.mapping.roles),
                rejected=len(report.mapping.rejected),
                error=report.mapping.error,
                rows_read=None if stats is None else stats.rows_read,
                rows_kept=None if stats is None else stats.rows_kept,
                dropped=None if stats is None else stats.dropped,
            )
        return reports


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chuẩn hoá dữ liệu shop thành bảng sạch tên cột chuẩn, trước khi chạy agent")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--shops", nargs="*", default=None, help="chỉ chạy các shop này, ghi đè `shops` trong config")
    parser.add_argument("--remap", action="store_true", help="bỏ mapping.json đã có, hỏi LLM lại")
    parser.add_argument("--offline", action="store_true", help="không gọi LLM, chỉ dùng mapping.json đã có")
    args = parser.parse_args(argv)
    config = load_run_config(args.config)
    if args.shops:
        config = config.model_copy(update={"shops": tuple(args.shops)})
    if config.normalize is None:
        raise ValueError("config has no normalize section")
    layout = WorkLayout(config.output_dir)
    log_dir = layout.root / "logs" / "normalize"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    configure_console(files=(log_dir / f"{stamp}.log",), detail_files=(log_dir / f"{stamp}.api.log",))
    events = EventLog(log_dir / f"{stamp}.events.jsonl")
    client = None if args.offline else OpenRouterClient(ConnectorConfig.from_env(), model=config.normalize.model, retry=config.retry, events=events)
    results = NormalizePipeline(config, client=client, events=events, env=run_env(), remap=args.remap).run()
    failed = [shop for shop, result in results.items() if isinstance(result, str)]
    broken = [f"{shop}/{r.mapping.name}" for shop, result in results.items() if not isinstance(result, str) for r in result if r.mapping.error]
    print(f"clean data: {layout.root / 'clean'} · shops {len(results)} · failed shops {failed or 'none'} · tables not cleaned {broken or 'none'}")
    return 0 if not failed and not broken else 2


if __name__ == "__main__":
    raise SystemExit(main())
