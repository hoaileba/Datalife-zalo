from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

FENCE = "````"


def _block(text: str, language: str = "") -> str:
    return f"{FENCE}{language}\n{text}\n{FENCE}"


def render(index: int, row: dict[str, Any]) -> str:
    gold = row.get("gold") or {}
    tag = f"{'DUNG' if row['correct'] else 'SAI'}_{row['calls']}luot"
    lines = [
        f"# {index}. {row['id']} [{tag}]",
        "",
        f"- business: {row['business_id']}, as_of: {row.get('as_of')}",
        f"- **Câu hỏi:** {row['question']}",
        f"- **Pred** ({row['final'].get('type')}): `{json.dumps(row['final'].get('answer'), ensure_ascii=False)}`",
        f"- **Gold** ({gold.get('type')}): `{json.dumps(gold.get('answer'), ensure_ascii=False)}`",
        f"- Gold reason: {gold.get('reason')}",
        f"- Agent: reason={row['reason']}, calls={row['calls']}",
    ]
    messages = row.get("messages", [])
    for turn in range(1, row["calls"] + 1):
        lines += ["", f"## Lượt {turn}", ""]
        if turn == 1 and len(messages) > 1:
            lines += ["### Prompt", "", "**system:** `synth/datamate_synth/prompts/system_prompt.md`", "", "**user:**", "", _block(json.dumps(json.loads(messages[1]["content"]), ensure_ascii=False, indent=2), "json")]
        for event in (item for item in row.get("events", []) if item.get("turn") == turn):
            if event["event"] == "model":
                lines += ["", "### Output model", "", _block(event["content"])]
                if event.get("reasoning"):
                    lines += ["", "### Reasoning", "", _block(event["reasoning"])]
            elif event["event"] == "execution":
                shown = {key: value for key, value in event.items() if key not in ("event", "turn")}
                lines += ["", "### execution", "", _block(json.dumps(shown, ensure_ascii=False, indent=2), "json")]
            elif event["event"] == "observation":
                lines += ["", "### observation", "", _block(json.dumps(event["observation"], ensure_ascii=False, indent=2), "json")]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="In trajectory ra markdown theo từng lượt: prompt, output model, execution, observation")
    parser.add_argument("--trajectories", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", choices=("all", "correct", "wrong"), default="all")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in args.trajectories.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if args.only == "all" or row["correct"] == (args.only == "correct")][: args.limit]
    args.out.write_text("\n\n".join(render(index, row) for index, row in enumerate(rows, start=1)) + "\n", encoding="utf-8")
    print(f"{args.out}: {len(rows)} câu")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
