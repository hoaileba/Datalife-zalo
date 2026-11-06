from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .config import FrozenModel

ShopStatus = Literal["verified", "budget_stopped", "max_turns", "stuck", "error"]


class Usage(FrozenModel):
    """Token một lần gọi model, đúng như provider báo."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ToolCall(FrozenModel):
    """Một lời gọi tool model yêu cầu; `arguments` là JSON thô chưa parse."""

    id: str
    name: str
    arguments: str


class ChatReply(FrozenModel):
    """Phần trả lời của model ở một lượt; `reasoning` là phần thinking provider trả kèm, không gửi lại model."""

    content: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str | None
    usage: Usage
    reasoning: str | None = None


class ExecResult(FrozenModel):
    """Kết quả chạy một script Python trong executor."""

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float


class ToolResult(FrozenModel):
    """Kết quả một tool call: `content` là bản model nhận (đã cắt), `full` là bản chưa cắt để ghi log."""

    content: str
    full: str | None = None
    finished: bool = False

    @property
    def logged(self) -> str:
        return self.content if self.full is None else self.full


class ToolOutput(FrozenModel):
    """Một tool call đã chạy trong một bước: tham số, kết quả model nhận, kết quả đầy đủ."""

    call_id: str
    name: str
    arguments: str
    sent_to_model: str
    full: str
    finished: bool


class StepRecord(FrozenModel):
    """Một bước của agent: input mới gửi lên model → process của model → output của tool."""

    turn: int
    at: str | None = None
    inputs: tuple[dict[str, Any], ...]
    request_messages: int
    compacted: tuple[int, ...]
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str | None
    reasoning: str | None
    content: str | None
    tool_calls: tuple[ToolCall, ...]
    outputs: tuple[ToolOutput, ...]


class VerifyResult(FrozenModel):
    """Kết luận của cổng nhận đáp án cho một shop."""

    ok: bool
    problems: tuple[str, ...]
    total: int
    answered: int
    abstain: int
    unanswerable: int


class ShopOutcome(FrozenModel):
    """Kết cục của một shop agent trong một lần chạy."""

    shop: str
    status: ShopStatus
    turns: int
    tokens: int
    verify: VerifyResult | None = None
    error: str | None = None


class RunState(FrozenModel):
    """Trạng thái bền của lần chạy, để chạy lại cùng lệnh là chạy tiếp."""

    run_id: str
    tokens_used: int = 0
    shops: dict[str, ShopOutcome] = Field(default_factory=dict)

    def is_verified(self, shop: str) -> bool:
        outcome = self.shops.get(shop)
        return outcome is not None and outcome.status == "verified"
