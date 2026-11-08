from __future__ import annotations

import glob
import re
import statistics
import sys
from pathlib import Path

CHARS_PER_TOKEN = {"gemma": 3.10, "qwen": 3.20}
PRICES = {"gemma": {"rẻ nhất (DeepInfra)": (0.04, 0.12), "đắt nhất (DeepInfra bậc cao)": (0.075, 0.225)}, "qwen": {"rẻ nhất (PrimeIntellect)": (0.019, 0.029), "DeepInfra": (0.10, 0.15), "đắt nhất (Together)": (0.17, 0.25)}}
TURN = re.compile(r"^Turn \d+:\n", re.M)


def conversation(path: str) -> tuple[int, int, int]:
    """Ký tự đầu vào cộng dồn qua mọi lượt, ký tự đầu ra ghi được, số lượt."""
    text = Path(path).read_text(encoding="utf-8")
    head, _, body = text.partition("\n--------\nASSISTANCE:")
    system = head.split("SYSTEM PROMPT:\n", 1)[1].split("\n--------\nUSER:\n", 1)
    context = len(system[0]) + len(system[1])
    sent = 0
    written = 0
    turns = TURN.split(body.split("\n--------\nFINAL:")[0])[1:]
    for turn in turns:
        sent += context
        reasoning = turn.split("[REASONING]\n", 1)[1].split("\n[CALL]", 1)[0] if "[REASONING]" in turn else ""
        code = turn.split("[CODE]\n", 1)[1].split("\n[OUTPUT]", 1)[0] if "[CODE]" in turn else turn.split("[ARGS] ", 1)[1].split("\n", 1)[0] if "[ARGS]" in turn else ""
        result = turn.split("[RESULT GỬI CHO MODEL]\n", 1)[1] if "[RESULT GỬI CHO MODEL]" in turn else ""
        reply = len(reasoning) + len(code) + 20
        written += reply
        context += reply + len(result)
    return sent, written, len(turns)


def main() -> int:
    for model, pattern in (("gemma", sys.argv[1]), ("qwen", sys.argv[2])):
        rows = [conversation(path) for path in glob.glob(pattern)]
        per_in = statistics.mean(row[0] for row in rows) / CHARS_PER_TOKEN[model]
        per_out = statistics.mean(row[1] for row in rows) / CHARS_PER_TOKEN[model]
        top_out = max(row[1] for row in rows) / CHARS_PER_TOKEN[model]
        turns = statistics.mean(row[2] for row in rows)
        print(f"== {model}: {len(rows)} câu, trung bình {turns:.1f} lượt, đầu vào {per_in:,.0f} token/câu, đầu ra ghi được {per_out:,.0f} token/câu (câu dài nhất {top_out:,.0f})")
        for name, (price_in, price_out) in PRICES[model].items():
            cost = 1000 * (per_in * price_in + per_out * price_out) / 1e6
            print(f"   1000 câu, giá {name}: ${cost:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
