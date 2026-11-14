from __future__ import annotations

import os

import openai

BACKENDS = {"vllm": "VLLM", "openrouter": "OPENROUTER"}


def _prefix(backend: str) -> str:
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend: {backend}, allowed {sorted(BACKENDS)}")
    return BACKENDS[backend]


def openai_client(*, backend: str, timeout: float, max_retries: int) -> openai.OpenAI:
    """Client OpenAI-compatible của đúng một backend, đọc <PREFIX>_BASE_URL và <PREFIX>_API_KEY."""
    prefix = _prefix(backend)
    missing = [name for name in (f"{prefix}_BASE_URL", f"{prefix}_API_KEY") if not os.environ.get(name)]
    if missing:
        raise ValueError(f"backend {backend} is not configured: missing {missing}")
    return openai.OpenAI(base_url=os.environ[f"{prefix}_BASE_URL"], api_key=os.environ[f"{prefix}_API_KEY"], timeout=timeout, max_retries=max_retries)


def resolve_model(*, backend: str, model: str | None) -> str:
    """Model truyền vào, hoặc <PREFIX>_MODEL của backend."""
    chosen = model or os.environ.get(f"{_prefix(backend)}_MODEL")
    if not chosen:
        raise ValueError(f"model is not set: pass --model or {_prefix(backend)}_MODEL")
    return chosen
