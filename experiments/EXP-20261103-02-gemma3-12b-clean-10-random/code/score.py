from __future__ import annotations

import json
import sys
from pathlib import Path

EXPERIMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT / "code" / "src"))

from datamate_agent.modules.score import is_correct

ARMS = ("vi", "en")
PRICE_INPUT = 0.05e-6
PRICE_OUTPUT = 0.15e-6


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def arm_report(arm: str, questions: dict[str, dict], claude: dict[str, dict]) -> tuple[dict, list[tuple]]:
    run = EXPERIMENT / f"run-{arm}"
    answers = {line["id"]: line for line in read_jsonl(run / "out" / "submission.jsonl")}
    state = json.loads((run / "state.json").read_text(encoding="utf-8")) if (run / "state.json").exists() else {"shops": {}}
    events = [json.loads(line) for d in sorted((run / "logs" / "runs").iterdir()) for line in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = []
    right = wrong = blank = 0
    for qid, question in questions.items():
        mine = answers.get(qid, {"type": "abstain"})
        if mine.get("type") == "abstain":
            verdict = "blank"
            blank += 1
        elif is_correct(mine, claude[qid]):
            verdict = "right"
            right += 1
        else:
            verdict = "wrong"
            wrong += 1
        rows.append((arm, question["business_id"], qid, question["question"], claude[qid], mine, verdict))
    calls = [e for e in events if e["event"] == "api_call"]
    tools = [e for e in events if e["event"] == "tool"]
    verifies = [e for e in events if e["event"] == "verify"]
    input_tokens = sum(e["prompt_tokens"] for e in calls)
    output_tokens = sum(e["completion_tokens"] for e in calls)
    report = {
        "score_vs_claude": right - wrong,
        "right": right,
        "wrong": wrong,
        "blank": blank,
        "accepted_shops": sum(1 for o in state["shops"].values() if o["status"] == "verified"),
        "shops": {shop: {"status": o["status"], "turns": o["turns"], "tokens": o["tokens"]} for shop, o in sorted(state["shops"].items())},
        "submit_calls": len(verifies),
        "submit_rejections": sum(1 for e in verifies if not e["ok"]),
        "api_calls": len(calls),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(input_tokens * PRICE_INPUT + output_tokens * PRICE_OUTPUT, 4),
        "api_errors": sum(1 for e in events if e["event"] == "api_error"),
        "tool_calls": len(tools),
        "tool_error_rate": round(sum(1 for e in tools if not e["ok"]) / len(tools), 4) if tools else 0.0,
        "tool_mix": {name: sum(1 for e in tools if e["tool"] == name) for name in sorted({e["tool"] for e in tools})},
    }
    return report, rows


def main() -> int:
    questions = {q["id"]: q for q in read_jsonl(EXPERIMENT / "inputs" / "questions.jsonl")}
    claude = {line["id"]: line for line in read_jsonl(EXPERIMENT / "inputs" / "claude_reference.jsonl")}
    reports: dict[str, dict] = {}
    table = ["| Nhánh | Shop | Câu | Câu hỏi | Claude | gemma | Kết quả |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for arm in ARMS:
        if not (EXPERIMENT / f"run-{arm}" / "logs" / "runs").exists():
            continue
        report, rows = arm_report(arm, questions, claude)
        reports[arm] = report
        for arm_name, shop, qid, text, reference, mine, verdict in rows:
            table.append(
                f"| {arm_name} | {shop} | `{qid}` | {text} | `{json.dumps(reference.get('answer'), ensure_ascii=False)}` "
                f"| `{mine.get('type')}` `{json.dumps(mine.get('answer'), ensure_ascii=False)}` | {verdict} |"
            )
    out = EXPERIMENT / "out"
    out.mkdir(exist_ok=True)
    (out / "comparison.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "comparison.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    print("\n".join(table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
