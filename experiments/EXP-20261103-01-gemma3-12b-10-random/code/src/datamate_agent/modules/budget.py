from __future__ import annotations

import threading

from ..models import BudgetConfig


class TokenBudget:
    """Token đã dùng của cả lần chạy, cộng dồn qua các lần chạy tiếp; an toàn nhiều thread."""

    def __init__(self, config: BudgetConfig, *, already_used: int) -> None:
        if already_used < 0:
            raise ValueError(f"already_used must be >= 0, got {already_used}")
        self._config = config
        self._used = already_used
        self._lock = threading.Lock()

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def ratio(self) -> float:
        return self.used / self._config.max_total_tokens

    def add(self, tokens: int) -> None:
        if tokens < 0:
            raise ValueError(f"tokens must be >= 0, got {tokens}")
        with self._lock:
            self._used += tokens

    def exhausted(self) -> bool:
        return self.used >= self._config.stop_at

    def shop_exhausted(self, shop_tokens: int) -> bool:
        limit = self._config.max_tokens_per_shop
        return limit is not None and shop_tokens >= limit
