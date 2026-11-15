"""Thinking variant of a gen.package folder: each reply's REASON becomes the thinking (student runs with thinking ON).

completion  {"content": "[CAUSE: ...\\n]REASON:\\n<r>\\nASKED: ...code"}
   ->       {"content": "[CAUSE: ...\\n]ASKED: ...code", "reasoning": "<r>"}
train/sft_lora.py renders a completion with `reasoning` with thinking ON (Gemma 4: <|channel>thought\\n{reasoning}\\n<channel|>
{content}). Earlier assistant turns inside the prompt lose their REASON too: with thinking on, vLLM returns the thought
apart from the content and the agent's history keeps the content only, so the prompt the student sees at inference
has no REASON in earlier turns.

Inference must match: Docker config with thinking enabled for the student (chat_template_kwargs enable_thinking: true);
the system prompt still asks for REASON first, which the student then writes in its thought channel.

No model calls.  python scripts/reason_as_thinking.py --package outputs/sft/final --out outputs/sft/final_think
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

SPLIT = re.compile(r'(?s)^(?P<cause>CAUSE:.*?\n)?REASON:\s*\n?(?P<reason>.*?)\n(?=ASKED:)(?P<rest>ASKED:.*)$')


def split_reply(text):
    """(content without REASON, reasoning) or None when the reply is not in the strict form."""
    m = SPLIT.match((text or '').strip())
    if not m or not m.group('reason').strip():
        return None
    return (m.group('cause') or '') + m.group('rest'), m.group('reason').strip()


def convert(sample):
    out = split_reply(sample['completion'][0]['content'])
    if out is None:
        return None
    prompt = []
    for msg in sample['prompt']:
        if msg['role'] == 'assistant':
            prev = split_reply(msg['content'])
            msg = {**msg, 'content': prev[0]} if prev else msg
        prompt.append(msg)
    content, reasoning = out
    return {**sample, 'prompt': prompt, 'completion': [{'role': 'assistant', 'content': content, 'reasoning': reasoning}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--package', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    src, dst = Path(a.package), Path(a.out)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    report = {}
    for side in ('train', 'val'):
        p = src / f'{side}.jsonl'
        if not p.exists():
            continue
        rows = [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]
        meta = [json.loads(l) for l in open(src / f'{side}_meta.jsonl', encoding='utf-8') if l.strip()]
        keep_rows, keep_meta = [], []
        for s, m in zip(rows, meta):
            c = convert(s)
            if c is not None:
                keep_rows.append(c)
                keep_meta.append(m)
        for name, rr in ((f'{side}.jsonl', keep_rows), (f'{side}_meta.jsonl', keep_meta)):
            with open(dst / name, 'w', encoding='utf-8') as f:
                f.writelines(json.dumps(r, ensure_ascii=False) + '\n' for r in rr)
        report[side] = {'in': len(rows), 'out': len(keep_rows)}
    (dst / 'THINKING_VARIANT.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    print(report)


if __name__ == '__main__':
    main()
