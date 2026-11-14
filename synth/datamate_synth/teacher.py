from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import openai

from .runner import MARKER

SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
MAX_CALLS = 4
CODE_TIMEOUT_S = 120
STDOUT_LIMIT = 3000
REQUEST_TIMEOUT_S = 300
API_TRIES = 4
API_WAIT_S = 10
VALUE_TYPES = ("number", "percent", "string", "date", "boolean", "list", "table")
SYNTH_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = SYNTH_ROOT.parent / "src"

Complete = Callable[[list[dict[str, Any]], dict[str, Any]], dict[str, Any]]


def action_schema(*, diagnosis: bool) -> dict[str, Any]:
    """JSON schema của một lượt, đúng protocol trong system prompt; từ lượt 2 bắt buộc diagnosis ngay sau action."""
    extra = {"diagnosis": {"type": "string", "minLength": 1, "maxLength": 400}} if diagnosis else {}
    head = ["action", "diagnosis"] if diagnosis else ["action"]
    python = {"type": "object", "properties": {"action": {"const": "python"}, **extra, "plan": {"type": "string", "minLength": 1, "maxLength": 600}, "rules": {"type": "array", "maxItems": 8, "items": {"type": "string", "minLength": 1, "maxLength": 240}}, "answer_type": {"enum": list(VALUE_TYPES)}, "code_lines": {"type": "array", "minItems": 1, "maxItems": 40, "items": {"type": "string"}}}, "required": head + ["plan", "rules", "answer_type", "code_lines"], "additionalProperties": False}
    answers = [{"type": "object", "properties": {"action": {"const": "answer"}, **extra, "plan": {"type": "string", "minLength": 1, "maxLength": 600}, "answer_type": {"const": kind}}, "required": head + ["plan", "answer_type"], "additionalProperties": False} for kind in ("unanswerable", "abstain")]
    return {"type": "json_schema", "json_schema": {"name": "agent_action", "strict": True, "schema": {"anyOf": [python, *answers]}}}


def openrouter_complete(*, model: str, seed: int, reasoning: bool) -> Complete:
    client = openai.OpenAI(base_url=os.environ["OPENROUTER_BASE_URL"], api_key=os.environ["OPENROUTER_API_KEY"], timeout=REQUEST_TIMEOUT_S, max_retries=0)

    def complete(messages: list[dict[str, Any]], response_format: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(API_TRIES):
            try:
                response = client.chat.completions.create(model=model, messages=messages, temperature=0, seed=seed, response_format=response_format, extra_body={"usage": {"include": True}, "reasoning": {"enabled": reasoning}, "provider": {"require_parameters": True}})
                break
            except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError, openai.APITimeoutError):
                if attempt == API_TRIES - 1:
                    raise
                time.sleep(API_WAIT_S)
        message = response.choices[0].message
        usage = response.usage.model_dump() if response.usage else {}
        return {"content": message.content or "", "reasoning": getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None), "usage": usage}

    return complete


def execute(code: str, *, tables_path: Path, as_of: str) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(SYNTH_ROOT), str(SRC_ROOT))), "PYTHONWARNINGS": "ignore"}
    try:
        done = subprocess.run([sys.executable, "-m", "datamate_synth.runner", str(tables_path), as_of], input=code, capture_output=True, text=True, timeout=CODE_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "error": {"type": "Timeout", "message": f"the program ran longer than {CODE_TIMEOUT_S}s", "line": None, "source": None}}
    if MARKER not in done.stdout:
        return {"ok": False, "stdout": done.stdout[-STDOUT_LIMIT:], "error": {"type": "RunnerCrash", "message": done.stderr[-500:], "line": None, "source": None}}
    return json.loads(done.stdout.split(MARKER, 1)[1])


def observation(outcome: dict[str, Any]) -> dict[str, Any]:
    stdout = outcome.get("stdout", "")[-STDOUT_LIMIT:]
    if not outcome["ok"]:
        error = outcome["error"]
        text = f"{error['type']}: {error['message']}" + (f" (line {error['line']}: {error['source']})" if error.get("line") else "")
        return {"status": "error", "error": text, "stdout": stdout, **({"variables": outcome["variables"]} if outcome.get("variables") else {})}
    return {"status": "check_failed", "issues": outcome["issues"], "result": outcome["result"], "stdout": stdout}


def user_turn(base: dict[str, Any], *, remaining: int) -> str:
    payload = copy.deepcopy(base)
    payload["remaining_calls"] = remaining
    payload["terminal_only"] = remaining == 1
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def solve(question: dict[str, Any], *, catalog: dict[str, Any], lookup: list[dict[str, Any]], tables_path: Path, complete: Complete) -> dict[str, Any]:
    """Một câu: tối đa MAX_CALLS lượt; code chạy được, có result, không vướng kiểm tra thì tự chốt đáp án."""
    base = {"catalog": catalog, "question": question["question"], "as_of": question["as_of_date"], "data_lookup": lookup, "remaining_calls": MAX_CALLS, "terminal_only": False}
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_turn(base, remaining=MAX_CALLS)}]
    events: list[dict[str, Any]] = []
    usage: list[dict[str, Any]] = []
    final: dict[str, Any] = {"type": "abstain"}
    reason = "exhausted"
    started = time.monotonic()
    for turn in range(1, MAX_CALLS + 1):
        remaining = MAX_CALLS - turn + 1
        messages[1] = {"role": "user", "content": user_turn(base, remaining=remaining)}
        reply = complete(messages, action_schema(diagnosis=turn > 1))
        usage.append(reply["usage"])
        messages.append({"role": "assistant", "content": reply["content"]})
        events.append({"event": "model", "turn": turn, "content": reply["content"], "reasoning": reply["reasoning"]})
        try:
            action = json.loads(reply["content"])
        except json.JSONDecodeError as error:
            note = {"status": "error", "error": f"FormatError: the reply is not one JSON object ({error.msg})", "stdout": ""}
            messages.append({"role": "user", "content": json.dumps(note, ensure_ascii=False)})
            events.append({"event": "observation", "turn": turn, "observation": note})
            continue
        if action.get("action") == "answer":
            final = {"type": action.get("answer_type", "abstain")}
            reason = "answered"
            break
        code = "\n".join(action.get("code_lines", []))
        outcome = execute(code, tables_path=tables_path, as_of=str(question["as_of_date"]))
        events.append({"event": "execution", "turn": turn, "code": code, **outcome})
        if outcome["ok"] and not outcome["issues"]:
            kind = action.get("answer_type", "number")
            final = {"type": kind, "answer": outcome["result"]}
            reason = "auto_finalized"
            break
        note = observation(outcome)
        messages.append({"role": "user", "content": json.dumps(note, ensure_ascii=False)})
        events.append({"event": "observation", "turn": turn, "observation": note})
    return {"id": question["id"], "business_id": question["business_id"], "question": question["question"], "as_of": question["as_of_date"], "final": final, "reason": reason, "calls": len(usage), "elapsed_s": round(time.monotonic() - started, 1), "usage": usage, "messages": messages, "events": events}
