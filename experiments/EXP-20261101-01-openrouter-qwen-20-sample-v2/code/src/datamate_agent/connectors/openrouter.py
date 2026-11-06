from __future__ import annotations

import hashlib
import json
import random
import time
from typing import Any, Sequence

from ..models import ChatReply, ConnectorConfig, ModelConfig, RetryConfig, ToolCall, Usage
from ..utils.events import EventLog

RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})


class OpenRouterClient:
    """Client Chat Completions OpenAI-compatible: retry 429/5xx, log mọi lời gọi."""

    def __init__(self, connector: ConnectorConfig, *, model: ModelConfig, retry: RetryConfig, events: EventLog) -> None:
        import openai

        self._openai = openai
        self._client = openai.OpenAI(
            base_url=connector.base_url,
            api_key=connector.api_key.get_secret_value(),
            max_retries=0,
        )
        self._model = model
        self._retry = retry
        self._events = events

    def complete(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]], *, shop: str) -> ChatReply:
        prompt_hash = _prompt_hash(messages, tools)
        for attempt in range(1, self._retry.max_attempts + 1):
            started = time.monotonic()
            try:
                response = self._client.chat.completions.create(**self._request(messages, tools))
            except self._openai.APIStatusError as error:
                if error.status_code not in RETRYABLE_STATUS or attempt == self._retry.max_attempts:
                    self._events.emit("api_error", shop=shop, model=self._model.name, status=error.status_code, attempt=attempt, message=str(error))
                    raise
                self._wait(shop=shop, attempt=attempt, reason=f"status {error.status_code}", retry_after=_retry_after(error))
                continue
            except (self._openai.APIConnectionError, self._openai.APITimeoutError) as error:
                if attempt == self._retry.max_attempts:
                    self._events.emit("api_error", shop=shop, model=self._model.name, status=None, attempt=attempt, message=str(error))
                    raise
                self._wait(shop=shop, attempt=attempt, reason=type(error).__name__, retry_after=None)
                continue
            reply = _parse(response)
            self._events.emit(
                "api_call",
                shop=shop,
                model=self._model.name,
                prompt_hash=prompt_hash,
                prompt_tokens=reply.usage.prompt_tokens,
                completion_tokens=reply.usage.completion_tokens,
                latency_s=round(time.monotonic() - started, 3),
                finish_reason=reply.finish_reason,
                tool_calls=len(reply.tool_calls),
                arguments_parsed=all(_is_json_object(call.arguments) for call in reply.tool_calls),
                attempt=attempt,
                temperature=self._model.temperature,
                seed=self._model.seed,
                reasoning=self._model.reasoning,
            )
            return reply
        raise ValueError(f"retry loop ended without reply for shop {shop}")

    def _request(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self._model.name,
            "messages": list(messages),
            "tools": list(tools),
            "tool_choice": "auto",
            "temperature": self._model.temperature,
            "max_tokens": self._model.max_output_tokens,
            "extra_body": {"provider": {"require_parameters": True}},
        }
        if self._model.seed is not None:
            request["seed"] = self._model.seed
        if self._model.reasoning is not None:
            request["extra_body"] = {**request["extra_body"], "reasoning": {"enabled": self._model.reasoning}}
        return request

    def _wait(self, *, shop: str, attempt: int, reason: str, retry_after: float | None) -> None:
        backoff = min(self._retry.max_delay_s, self._retry.base_delay_s * 2 ** (attempt - 1))
        delay = retry_after if retry_after is not None else backoff * (0.5 + random.random() / 2)
        self._events.emit("api_retry", shop=shop, model=self._model.name, attempt=attempt, reason=reason, delay_s=round(delay, 2))
        time.sleep(delay)


def _parse(response: Any) -> ChatReply:
    if not response.choices:
        raise ValueError("provider returned no choices")
    if response.usage is None:
        raise ValueError("provider returned no usage, token budget cannot be enforced")
    choice = response.choices[0]
    message = choice.message
    calls = tuple(
        ToolCall(id=call.id, name=call.function.name, arguments=call.function.arguments or "")
        for call in (message.tool_calls or ())
    )
    return ChatReply(
        content=message.content,
        tool_calls=calls,
        finish_reason=choice.finish_reason,
        usage=Usage(prompt_tokens=response.usage.prompt_tokens or 0, completion_tokens=response.usage.completion_tokens or 0),
        reasoning=getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None),
    )


def _prompt_hash(messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> str:
    payload = json.dumps({"messages": list(messages), "tools": list(tools)}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _retry_after(error: Any) -> float | None:
    response = getattr(error, "response", None)
    if response is None:
        return None
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _is_json_object(raw: str) -> bool:
    try:
        return isinstance(json.loads(raw or "{}"), dict)
    except json.JSONDecodeError:
        return False
