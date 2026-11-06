from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

BASE_URL_ENV = "OPENROUTER_BASE_URL"
API_KEY_ENV = "OPENROUTER_API_KEY"
RUN_ENV = "DATAMATE_ENV"
PATH_FIELDS = ("dataset_root", "output_dir")


class FrozenModel(BaseModel):
    """Gốc chung của mọi config: validated, frozen, cấm field lạ."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ConnectorConfig(FrozenModel):
    """Địa chỉ và khoá của API OpenAI-compatible, chỉ đọc từ biến môi trường."""

    base_url: str = Field(min_length=1)
    api_key: SecretStr

    @classmethod
    def from_env(cls) -> ConnectorConfig:
        base_url = os.environ.get(BASE_URL_ENV, "").strip()
        api_key = os.environ.get(API_KEY_ENV, "").strip()
        if not base_url:
            raise ValueError(f"missing environment variable: {BASE_URL_ENV}")
        if not api_key:
            raise ValueError(f"missing environment variable: {API_KEY_ENV}")
        return cls(base_url=base_url, api_key=SecretStr(api_key))


class ModelConfig(FrozenModel):
    """Model gọi qua OpenRouter và tham số sinh của nó."""

    name: str = Field(min_length=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    seed: int | None = None
    max_output_tokens: int = Field(default=4096, gt=0)


class ExecutorConfig(FrozenModel):
    """Cách chạy code Python do model sinh ra; `kind` bắt buộc chọn tường minh."""

    kind: Literal["docker", "local"]
    timeout_s: int = Field(default=300, gt=0)
    docker_image: str | None = None
    docker_memory: str = "4g"
    docker_cpus: float = Field(default=2.0, gt=0.0)

    @model_validator(mode="after")
    def _docker_needs_image(self) -> ExecutorConfig:
        if self.kind == "docker" and not self.docker_image:
            raise ValueError("executor kind docker needs docker_image")
        return self


class BudgetConfig(FrozenModel):
    """Ngân sách token của cả lần chạy; dừng nhận batch mới khi chạm `stop_ratio`."""

    max_total_tokens: int = Field(gt=0)
    stop_ratio: float = Field(default=0.8, gt=0.0, le=1.0)
    max_tokens_per_shop: int | None = Field(default=None, gt=0)

    @property
    def stop_at(self) -> int:
        return int(self.max_total_tokens * self.stop_ratio)


class RetryConfig(FrozenModel):
    """Chính sách thử lại khi API trả 429, 5xx hoặc mất kết nối."""

    max_attempts: int = Field(default=6, gt=0)
    base_delay_s: float = Field(default=2.0, gt=0.0)
    max_delay_s: float = Field(default=60.0, gt=0.0)


class RunConfig(FrozenModel):
    """Một lần chạy shop agent trên một bộ dữ liệu."""

    run_id: str = Field(min_length=1)
    dataset_root: Path
    questions_file: str = "questions.jsonl"
    truth_file: str | None = None
    output_dir: Path
    shops: tuple[str, ...] = ()
    model: ModelConfig
    executor: ExecutorConfig
    budget: BudgetConfig
    retry: RetryConfig = RetryConfig()
    batch_size: int = Field(default=3, gt=0)
    max_turns: int = Field(default=80, gt=0)
    allow_abstain: bool
    context_char_limit: int = Field(default=240_000, gt=10_000)
    tool_output_char_limit: int = Field(default=12_000, gt=500)

    @property
    def questions_path(self) -> Path:
        return self.dataset_root / self.questions_file

    @property
    def truth_path(self) -> Path | None:
        return None if self.truth_file is None else self.dataset_root / self.truth_file

    @property
    def rulebook_path(self) -> Path:
        return self.dataset_root / "rulebook.md"

    @property
    def calendar_path(self) -> Path:
        return self.dataset_root / "calendar.csv"


def run_env() -> Literal["dev", "prod"]:
    value = os.environ.get(RUN_ENV, "dev").strip()
    if value not in ("dev", "prod"):
        raise ValueError(f"{RUN_ENV} must be dev or prod, got {value!r}")
    return "dev" if value == "dev" else "prod"


def load_run_config(path: Path | str) -> RunConfig:
    source = Path(path).resolve()
    raw: Any = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"config must be a mapping: {source}")
    data = dict(raw)
    for key in PATH_FIELDS:
        if key in data:
            value = Path(str(data[key])).expanduser()
            data[key] = value if value.is_absolute() else (source.parent / value).resolve()
    if "shops" in data and data["shops"] is not None:
        data["shops"] = tuple(data["shops"])
    return RunConfig.model_validate(data)
