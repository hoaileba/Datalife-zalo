from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE / "src"))

from datamate_agent.llm import openai_client, resolve_model


def main() -> int:
    spec = importlib.util.spec_from_file_location("experiment_runner", CODE / "runner.py")
    if spec is None or spec.loader is None:
        raise ValueError("cannot load logging sanitizer")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    started = time.monotonic()
    model = resolve_model(backend="vllm", model=None)
    client = openai_client(backend="vllm", timeout=20, max_retries=0)
    try:
        reply = client.chat.completions.create(model=model, messages=[{"role": "user", "content": "Chỉ trả lời OK."}], temperature=0, seed=20261103, max_tokens=16)
        print(json.dumps({"event": "health_chat_probe", "success": True, "seconds": time.monotonic() - started, "model": model, "reply": reply.choices[0].message.content, "usage": reply.usage.model_dump() if reply.usage else None}, ensure_ascii=False), flush=True)
        return 0
    except Exception as error:
        print(json.dumps({"event": "health_chat_probe", "success": False, "seconds": time.monotonic() - started, "error_type": type(error).__name__, "error": runner.redact(str(error))}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
