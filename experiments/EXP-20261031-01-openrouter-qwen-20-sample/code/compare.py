from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

EXPERIMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT / "code" / "src"))

from datamate_agent.modules.score import is_correct

RUN = EXPERIMENT / "run"
PRICE_INPUT = 0.12e-6
PRICE_OUTPUT = 0.24e-6


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    questions = {q["id"]: q for q in read_jsonl(EXPERIMENT / "inputs" / "questions.jsonl")}
    groups = json.loads((EXPERIMENT / "inputs" / "groups.json").read_text(encoding="utf-8"))
    claude = {line["id"]: line for line in read_jsonl(EXPERIMENT / "out" / "claude_reference.jsonl")}
    qwen = {line["id"]: line for line in read_jsonl(RUN / "out" / "submission.jsonl")}
    state = json.loads((RUN / "state.json").read_text(encoding="utf-8")) if (RUN / "state.json").exists() else {"shops": {}}
    run_dirs = sorted((RUN / "logs" / "runs").iterdir())
    events = [json.loads(line) for d in run_dirs for line in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    rows = []
    agree: dict[str, Counter[str]] = defaultdict(Counter)
    for qid, question in questions.items():
        mine = qwen.get(qid, {"type": "abstain"})
        reference = claude[qid]
        if mine.get("type") == "abstain":
            verdict = "blank"
        else:
            verdict = "agree" if is_correct(mine, reference) else "differ"
        agree[groups[qid]][verdict] += 1
        agree["overall"][verdict] += 1
        rows.append((groups[qid], question["business_id"], qid, question["question"], reference, mine, verdict))

    calls = [e for e in events if e["event"] == "api_call"]
    input_tokens = sum(e["prompt_tokens"] for e in calls)
    output_tokens = sum(e["completion_tokens"] for e in calls)
    tools = [e for e in events if e["event"] == "tool"]
    report = {
        "agreement": {group: {**counts, "rate": round(counts["agree"] / sum(counts.values()), 4)} for group, counts in agree.items()},
        "coverage": round(sum(1 for r in rows if r[6] != "blank") / len(rows), 4),
        "shops": {shop: {"status": o["status"], "turns": o["turns"], "tokens": o["tokens"]} for shop, o in sorted(state["shops"].items())},
        "api_calls": len(calls),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(input_tokens * PRICE_INPUT + output_tokens * PRICE_OUTPUT, 4),
        "api_errors": sum(1 for e in events if e["event"] == "api_error"),
        "api_retries": sum(1 for e in events if e["event"] == "api_retry"),
        "tool_calls": len(tools),
        "tool_errors": sum(1 for e in tools if not e["ok"]),
        "tool_error_rate": round(sum(1 for e in tools if not e["ok"]) / len(tools), 4) if tools else 0.0,
    }
    (EXPERIMENT / "out" / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["| Nhóm | Shop | Câu | Claude | qwen3-14b | Kết quả |", "| --- | --- | --- | --- | --- | --- |"]
    for group, shop, qid, text, reference, mine, verdict in rows:
        def show(line: dict) -> str:
            value = line.get("answer") if line.get("type") not in ("unanswerable", "abstain") else line.get("type")
            return json.dumps(value, ensure_ascii=False).replace("|", "\\|")[:80]
        lines.append(f"| {group} | {shop} | {qid}: {text.replace('|', '/')} | {show(reference)} | {show(mine)} | {verdict} |")
    (EXPERIMENT / "out" / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
