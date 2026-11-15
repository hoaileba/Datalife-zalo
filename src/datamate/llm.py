"""Model client: an OpenAI-compatible vLLM server, streamed, with early stops for degenerate output.

In:  messages, response_format, limits (config.yaml `llm`).  Out: `Reply` (text, finish, usage, seconds).
finish is the server's reason ('stop', 'length') or ours: 'repetition' (a line written many times) or 'comments'
(code_lines taken over by comment lines). Sampling: temperature from config (default 0), fixed seed, thinking off.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

DEFAULT_BASE_URL = 'http://127.0.0.1:8000/v1'          # the vLLM server inside the image
TRANSIENT = {'RateLimitError', 'APIConnectionError', 'APITimeoutError', 'InternalServerError'}


@dataclass
class Reply:
    text: str
    finish: str | None
    usage: dict | None
    seconds: float
    reasoning: str = ''          # thinking text of models that stream it (teacher runs); never parsed
    meta: dict = field(default_factory=dict)   # request settings, response ids, timings, retried errors (logs, stats)


def repeated_lines(text, min_len=12, repeats=6, consecutive=20):
    """A substantial line written `repeats` times, or any line repeated back to back `consecutive` times."""
    lines = [x.strip() for x in re.split(r'\\n|\n|",\s*"', text) if x.strip()]
    counts = {}
    for line in lines:
        if len(line) >= min_len:
            counts[line] = counts.get(line, 0) + 1
            if counts[line] >= repeats:
                return True
    run = 1
    for a, b in zip(lines, lines[1:]):
        run = run + 1 if a == b else 1
        if run >= consecutive:
            return True
    return False


def comment_flood(text, limit):
    """The code block taken over by comments: at least `limit` comment lines and three times more than code lines."""
    start = text.find('```python')
    if start < 0:
        return False
    items = [line for line in text[start + 9:].split('\n') if line.strip()]
    comments = sum(item.lstrip().startswith('#') for item in items)
    return comments >= limit and comments > 3 * (len(items) - comments)


class LLM:
    def __init__(self, cfg):
        from openai import OpenAI
        self.cfg = cfg
        self.model = cfg['model']
        self.client = OpenAI(base_url=os.environ.get(cfg['base_url_env']) or DEFAULT_BASE_URL, api_key=os.environ.get(cfg.get('api_key_env', ''), 'EMPTY'),
                             timeout=cfg['timeout_seconds'], max_retries=0)
        self.slots = threading.BoundedSemaphore(cfg['max_concurrency'])

    def _args(self, messages, response_format, max_tokens):
        body = {'chat_template_kwargs': {'enable_thinking': False}, **(self.cfg.get('extra_body') or {})}
        args = {'model': self.model, 'messages': messages, 'max_tokens': max_tokens or self.cfg['max_tokens'],
                'temperature': self.cfg.get('temperature', 0.0), 'seed': self.cfg['seed'], 'extra_body': body}
        if response_format:
            args['response_format'] = response_format
        return args

    def _stream(self, args, deadline):
        guard_every, max_comments = 200, self.cfg['max_comment_lines']
        left = max(1.0, deadline - time.monotonic())
        stream = self.client.chat.completions.create(**args, stream=True, stream_options={'include_usage': True},
                                                     timeout=min(self.cfg['timeout_seconds'], left))
        watchdog = threading.Timer(left + 2, stream.close)       # a server that stalls or only sends keep-alives
        watchdog.daemon = True
        watchdog.start()
        parts, thought, finish, usage, checked, size = [], [], None, None, 0, 0
        t0, meta = time.monotonic(), {'chunks': 0}
        try:
            for chunk in stream:
                meta['chunks'] += 1
                if 'id' not in meta:
                    meta.update(id=getattr(chunk, 'id', None), model=getattr(chunk, 'model', None),
                                system_fingerprint=getattr(chunk, 'system_fingerprint', None), created=getattr(chunk, 'created', None))
                if getattr(chunk, 'usage', None) is not None:
                    usage = chunk.usage.model_dump()
                for choice in chunk.choices or ():
                    if choice.delta is not None:      # thinking: reasoning_content (DeepSeek, OpenRouter) or reasoning (vLLM)
                        thought.append(getattr(choice.delta, 'reasoning_content', None) or getattr(choice.delta, 'reasoning', None) or '')
                        if thought[-1] and 'first_reasoning_s' not in meta:
                            meta['first_reasoning_s'] = round(time.monotonic() - t0, 3)
                    if choice.delta is not None and choice.delta.content:
                        if 'first_content_s' not in meta:
                            meta['first_content_s'] = round(time.monotonic() - t0, 3)
                        parts.append(choice.delta.content); size += len(choice.delta.content)
                    if choice.finish_reason:
                        finish = choice.finish_reason
                if size - checked >= guard_every:
                    checked, text = size, ''.join(parts)
                    if self.cfg.get('repetition_guard', True) and repeated_lines(text):   # off for JSON generators (gen/)
                        finish = 'repetition'; break
                    if max_comments and comment_flood(text, max_comments):
                        finish = 'comments'; break
                if time.monotonic() > deadline:
                    finish = 'deadline'; break
        except Exception:
            if time.monotonic() < deadline:
                raise
            finish = 'deadline'                              # closed by the watchdog at the deadline
        finally:
            watchdog.cancel()
            if finish in ('repetition', 'comments', 'deadline') or finish is None:
                stream.close()
        if finish is None and time.monotonic() > deadline:
            finish = 'deadline'
        meta['stream_s'] = round(time.monotonic() - t0, 3)
        return ''.join(parts), finish, usage, ''.join(thought), meta

    def chat(self, messages, response_format=None, max_tokens=None, deadline=None):
        deadline = deadline or time.monotonic() + self.cfg['timeout_seconds']
        args = self._args(messages, response_format, max_tokens)
        attempt, errors = 0, []
        request = {k: v for k, v in args.items() if k != 'messages'}
        while True:                    # a server down or still loading: keep trying until this question's deadline
            started = time.monotonic()
            with self.slots:
                waited = round(time.monotonic() - started, 3)           # time queued behind max_concurrency
                at = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
                try:
                    text, finish, usage, thought, meta = self._stream(args, deadline)
                    meta.update(request=request, started_at=at, queue_s=waited, attempts=attempt + 1, retried_errors=errors)
                    return Reply(text, finish, usage, round(time.monotonic() - started, 2), thought, meta)
                except Exception as exc:
                    errors.append({'at': at, 'error': f'{type(exc).__name__}: {exc}'[:500]})
                    if type(exc).__name__ not in TRANSIENT or time.monotonic() > deadline - 2:
                        raise
            attempt += 1
            time.sleep(min(2 ** min(attempt, 4), max(0.0, deadline - time.monotonic() - 1)))
