"""Token counts of SFT samples as the student sees them: the Gemma chat template renders the prompt (thinking off, so
the generation prompt ends with an empty thought channel, exactly what vLLM sends), the completion is the reply text
plus the end-of-turn token the model must learn to emit.

Exact when `tokenizers` and `jinja2` are importable and a tokenizer folder (tokenizer.json + chat_template.jinja) is
found: --tokenizer, $DM_TOKENIZER, or outputs/tokenizers/gemma-4-12B-it (fetch it with `python -m gen.tokens --fetch`,
about 32 MB, no model weights). Otherwise an estimate from characters that errs on the long side (measured on teacher
samples: 2.9-3.5 characters per Gemma token in prompts, 2.7-3.2 in completions).

  python -m gen.tokens --fetch [--repo google/gemma-4-12B-it]      # tokenizer files only
  python -m gen.tokens --check                                      # which counter is active
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = 'google/gemma-4-12B-it'
DEFAULT_DIR = ROOT / 'outputs' / 'tokenizers' / 'gemma-4-12B-it'
FILES = ('tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja', 'config.json', 'generation_config.json')
EOT = '<turn|>'                                   # Gemma 4 end of turn (id 106, one of the eos ids vLLM stops on)
PROMPT_CHARS, COMPLETION_CHARS = 2.8, 2.6         # per token, below every measured ratio: estimates run long
TURN_OVERHEAD = 6                                 # role markers per message in the estimate


def completion_text(content: str) -> str:
    """What the model generates after the prompt: the reply (trimmed, as the template stores it) and end of turn."""
    return content.strip() + EOT


class TokenCounter:
    """count(prompt_messages, completion_content) -> (prompt_tokens, completion_tokens); `exact` says which mode."""

    def __init__(self, path: str | Path | None = None, required=False):
        self.exact, self.name, self.why = False, f'estimate ({PROMPT_CHARS} / {COMPLETION_CHARS} chars per token)', ''
        folder = Path(path or os.environ.get('DM_TOKENIZER') or DEFAULT_DIR)
        try:
            from jinja2.sandbox import ImmutableSandboxedEnvironment
            from tokenizers import Tokenizer
            if not (folder / 'tokenizer.json').is_file() or not (folder / 'chat_template.jinja').is_file():
                raise FileNotFoundError(f'{folder}: no tokenizer.json + chat_template.jinja (python -m gen.tokens --fetch)')
            env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True, extensions=['jinja2.ext.loopcontrols'])
            env.globals['raise_exception'] = _raise
            self.template = env.from_string((folder / 'chat_template.jinja').read_text(encoding='utf-8'))
            self.tokenizer = Tokenizer.from_file(str(folder / 'tokenizer.json'))
            if self.tokenizer.token_to_id(EOT) is None:
                raise ValueError(f'{folder}: tokenizer has no {EOT} token (not a Gemma 4 tokenizer)')
            self.exact, self.name = True, f'exact ({folder.name})'
        except Exception as exc:                           # noqa: BLE001 - no tokenizer here: estimate
            self.why = f'{type(exc).__name__}: {exc}'
            if required:
                raise SystemExit(f'exact token counts requested but unavailable: {self.why}')

    def render_prompt(self, messages) -> str:
        """The prompt string the serving engine builds (bos, turns, generation prompt with thinking off)."""
        if not self.exact:
            return ''.join(m['content'] for m in messages)
        return self.template.render(messages=messages, add_generation_prompt=True, bos_token='<bos>', enable_thinking=False)

    def tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)

    def count(self, messages, completion: str):
        if self.exact:
            return self.tokens(self.render_prompt(messages)), self.tokens(completion_text(completion))
        prompt_chars = sum(len(m['content']) for m in messages)
        return (round(prompt_chars / PROMPT_CHARS) + TURN_OVERHEAD * len(messages) + 8,
                round(len(completion.strip()) / COMPLETION_CHARS) + 1)


def _raise(message):
    raise ValueError(message)


def fetch(repo=REPO, out: Path = DEFAULT_DIR):
    """Tokenizer and template files of `repo` (public, no token needed for Gemma 4); no weights."""
    out.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        url = f'https://huggingface.co/{repo}/resolve/main/{name}'
        tmp = out / (name + '.tmp')
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, 'wb') as f:
            f.write(r.read())
        tmp.replace(out / name)
        print(f'{name}: {(out / name).stat().st_size} bytes', file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--fetch', action='store_true', help='download the tokenizer files of --repo into --dir')
    ap.add_argument('--repo', default=REPO)
    ap.add_argument('--dir', default=str(DEFAULT_DIR))
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args(argv)
    if a.fetch:
        fetch(a.repo, Path(a.dir))
    c = TokenCounter(a.dir)
    print(c.name + (f'  [{c.why}]' if c.why else ''))


if __name__ == '__main__':
    main()
