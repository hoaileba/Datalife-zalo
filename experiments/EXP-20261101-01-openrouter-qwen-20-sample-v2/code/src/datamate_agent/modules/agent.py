from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Sequence

from ..connectors.base import ChatClient
from ..models import ChatReply, ShopOutcome, ShopStatus, StepRecord, ToolOutput, ToolResult
from ..utils.events import EventLog
from .budget import TokenBudget
from .runlog import ShopLog
from .tools import ToolBox

NUDGE = "Bạn chưa gọi tool nào. Tiếp tục bằng tool call; khi đã có script, đáp án và notes thì gọi finish(report)."
REPEATED = "ERROR: lời gọi này y hệt lời gọi ngay trước nên không chạy lại; kết quả sẽ không đổi. Hãy sửa script hoặc làm bước khác."
KEEP_RECENT_MESSAGES = 8
COMPACTED = "[đã lược output cũ: {size} ký tự. Gọi lại tool nếu cần]"


class ShopAgent:
    """Một agent phụ trách đúng một shop: vòng tool calling tới khi verify nhận đáp án."""

    def __init__(
        self,
        *,
        shop: str,
        client: ChatClient,
        toolbox: ToolBox,
        budget: TokenBudget,
        system_prompt: str,
        task_prompt: str,
        max_turns: int,
        stuck_after: int,
        context_char_limit: int,
        shop_log: ShopLog,
        events: EventLog,
    ) -> None:
        self._shop = shop
        self._client = client
        self._toolbox = toolbox
        self._budget = budget
        self._system_prompt = system_prompt
        self._task_prompt = task_prompt
        self._max_turns = max_turns
        self._stuck_after = stuck_after
        self._context_char_limit = context_char_limit
        self._shop_log = shop_log
        self._events = events

    def run(self) -> ShopOutcome:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": self._task_prompt},
        ]
        self._shop_log.start(system_prompt=self._system_prompt, task_prompt=self._task_prompt, tools=self._toolbox.specs)
        pending_inputs = list(messages)
        shop_tokens = 0
        previous_call: tuple[str, str] | None = None
        repeats = 0
        last_rejection: tuple[str, ...] | None = None
        same_rejections = 0
        self._events.emit("shop_start", shop=self._shop, budget_used=self._budget.used)
        for turn in range(1, self._max_turns + 1):
            if self._budget.exhausted() or self._budget.shop_exhausted(shop_tokens):
                return self._outcome("budget_stopped", turn - 1, shop_tokens)
            request = compact(messages, self._context_char_limit)
            self._shop_log.request(turn, request)
            reply = self._client.complete(request, self._toolbox.specs, shop=self._shop)
            self._budget.add(reply.usage.total)
            shop_tokens += reply.usage.total
            messages.append(_assistant_message(reply))
            inputs, pending_inputs = pending_inputs, []
            outputs: list[ToolOutput] = []
            finished = False
            if not reply.tool_calls:
                nudge = {"role": "user", "content": NUDGE}
                messages.append(nudge)
                pending_inputs.append(nudge)
            for call in reply.tool_calls:
                signature = (call.name, call.arguments)
                if signature == previous_call:
                    repeats += 1
                    result = ToolResult(content=REPEATED)
                    self._events.emit("tool_repeat", shop=self._shop, tool=call.name, repeats=repeats)
                else:
                    repeats = 0
                    result = self._toolbox.call(call.name, call.arguments)
                previous_call = signature
                rejected = result.content.startswith("NOT ACCEPTED") or result.content == REPEATED
                if call.name == "finish" and rejected and self._toolbox.last_verify is not None:
                    problems = self._toolbox.last_verify.problems
                    same_rejections = same_rejections + 1 if problems == last_rejection else 1
                    last_rejection = problems
                tool_message = {"role": "tool", "tool_call_id": call.id, "content": result.content}
                messages.append(tool_message)
                pending_inputs.append(tool_message)
                outputs.append(ToolOutput(call_id=call.id, name=call.name, arguments=call.arguments, sent_to_model=result.content, full=result.logged, finished=result.finished))
                if result.finished:
                    finished = True
                    break
            self._shop_log.step(
                StepRecord(
                    turn=turn,
                    at=datetime.now().strftime("%H:%M:%S"),
                    inputs=tuple(inputs),
                    request_messages=len(request),
                    compacted=tuple(index for index, (sent, kept) in enumerate(zip(request, messages)) if sent != kept),
                    prompt_tokens=reply.usage.prompt_tokens,
                    completion_tokens=reply.usage.completion_tokens,
                    finish_reason=reply.finish_reason,
                    reasoning=reply.reasoning,
                    content=reply.content,
                    tool_calls=reply.tool_calls,
                    outputs=tuple(outputs),
                )
            )
            if finished:
                return self._outcome("verified", turn, shop_tokens)
            if repeats >= self._stuck_after or same_rejections >= self._stuck_after:
                return self._outcome("stuck", turn, shop_tokens)
        return self._outcome("max_turns", self._max_turns, shop_tokens)

    def _outcome(self, status: ShopStatus, turns: int, tokens: int) -> ShopOutcome:
        outcome = ShopOutcome(
            shop=self._shop,
            status=status,
            turns=turns,
            tokens=tokens,
            verify=self._toolbox.last_verify,
            report=self._toolbox.last_report,
        )
        self._events.emit("shop_end", shop=self._shop, status=status, turns=turns, tokens=tokens, budget_used=self._budget.used)
        return outcome


def compact(messages: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out = [dict(message) for message in messages]
    size = sum(message_size(message) for message in out)
    protected = max(0, len(out) - KEEP_RECENT_MESSAGES)
    for index in range(protected):
        if size <= limit:
            break
        shrunk = _shrink(out[index])
        size -= message_size(out[index]) - message_size(shrunk)
        out[index] = shrunk
    return out


def message_size(message: dict[str, Any]) -> int:
    calls = message.get("tool_calls") or ()
    return len(str(message.get("content") or "")) + sum(len(call["function"]["arguments"]) for call in calls)


def _shrink(message: dict[str, Any]) -> dict[str, Any]:
    if message["role"] == "tool":
        content = str(message.get("content") or "")
        stub = COMPACTED.format(size=len(content))
        return {**message, "content": stub} if len(stub) < len(content) else message
    if message["role"] == "assistant" and message.get("tool_calls"):
        calls = []
        for call in message["tool_calls"]:
            arguments = call["function"]["arguments"]
            stub = json.dumps({"compacted_chars": len(arguments)})
            kept = stub if len(stub) < len(arguments) else arguments
            calls.append({**call, "function": {**call["function"], "arguments": kept}})
        return {**message, "tool_calls": calls}
    return message


def _assistant_message(reply: ChatReply) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": reply.content or ""}
    if reply.tool_calls:
        message["tool_calls"] = [
            {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}}
            for call in reply.tool_calls
        ]
    return message
