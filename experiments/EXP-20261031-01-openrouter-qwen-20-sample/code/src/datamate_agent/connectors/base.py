from __future__ import annotations

from typing import Any, Protocol, Sequence

from ..models import ChatReply


class ChatClient(Protocol):
    """Thứ duy nhất shop agent cần từ một model: một lượt chat có tool."""

    def complete(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]], *, shop: str) -> ChatReply: ...
