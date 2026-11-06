from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..models import ShopOutcome, StepRecord
from .merge import MergeReport
from .paths import WorkLayout
from .score import ScoreReport

FENCE_RUN = re.compile(r"`{3,}")


class RunLog:
    """Thư mục log của một lần chạy: event, console, và log từng shop, từng câu hỏi."""

    def __init__(self, root: Path, *, started_at: datetime) -> None:
        stamp = started_at.strftime("%Y%m%d-%H%M%S")
        candidate = root / stamp
        suffix = 2
        while candidate.exists():
            candidate = root / f"{stamp}-{suffix}"
            suffix += 1
        candidate.mkdir(parents=True)
        self.dir = candidate

    @property
    def events_path(self) -> Path:
        return self.dir / "events.jsonl"

    @property
    def console_path(self) -> Path:
        return self.dir / "console.log"

    def shop(self, shop: str) -> ShopLog:
        return ShopLog(self.dir / "shops" / shop)

    def question_path(self, qid: str) -> Path:
        return self.dir / "questions" / f"{qid}.md"


class ShopLog:
    """Log từng bước của một shop agent: request đầy đủ gửi model, và bản ghi input → process → output."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    @property
    def steps_path(self) -> Path:
        return self.dir / "steps.jsonl"

    @property
    def requests_path(self) -> Path:
        return self.dir / "requests.jsonl"

    @property
    def system_prompt_path(self) -> Path:
        return self.dir / "system_prompt.md"

    def start(self, *, system_prompt: str, task_prompt: str, tools: Sequence[dict[str, Any]]) -> None:
        self.system_prompt_path.write_text(system_prompt, encoding="utf-8")
        (self.dir / "task_prompt.md").write_text(task_prompt, encoding="utf-8")
        (self.dir / "tools.json").write_text(json.dumps(list(tools), ensure_ascii=False, indent=2), encoding="utf-8")

    def request(self, turn: int, messages: Sequence[dict[str, Any]]) -> None:
        _append(self.requests_path, {"turn": turn, "messages": list(messages)})

    def step(self, record: StepRecord) -> None:
        _append(self.steps_path, record.model_dump(mode="json"))

    def steps(self) -> tuple[StepRecord, ...]:
        if not self.steps_path.exists():
            return ()
        lines = self.steps_path.read_text(encoding="utf-8").splitlines()
        return tuple(StepRecord.model_validate_json(line) for line in lines if line.strip())


def write_question_logs(
    run_log: RunLog,
    *,
    shop: str,
    questions: Sequence[Mapping[str, Any]],
    layout: WorkLayout,
    outcome: ShopOutcome,
) -> tuple[Path, ...]:
    shop_log = run_log.shop(shop)
    steps = shop_log.steps()
    answers = _answers_by_id(layout.answers(shop))
    script = layout.script(shop).read_text(encoding="utf-8") if layout.script(shop).exists() else None
    written = []
    for question in questions:
        path = run_log.question_path(str(question["id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render_question(question, steps=steps, outcome=outcome, answer=answers.get(str(question["id"])), script=script, shop_log=shop_log),
            encoding="utf-8",
        )
        written.append(path)
    return tuple(written)


def render_question(
    question: Mapping[str, Any],
    *,
    steps: Sequence[StepRecord],
    outcome: ShopOutcome,
    answer: dict[str, Any] | None,
    script: str | None,
    shop_log: ShopLog,
) -> str:
    qid = str(question["id"])
    shop = str(question["business_id"])
    mentions = [step.turn for step in steps if _mentions(step, qid)]
    out = [
        f"# {qid} · {shop}",
        "",
        f"- Câu hỏi: {question['question']}",
        f"- as_of_date: {question['as_of_date']}",
        f"- Trạng thái shop: `{outcome.status}` · {outcome.turns} bước · {outcome.tokens:,} token",
        f"- Bước có nhắc tới câu này: {', '.join(map(str, mentions)) or 'không có'} (★ bên dưới)",
        "",
        "## Output cuối",
        "",
        _fence(json.dumps(answer, ensure_ascii=False, indent=2) if answer is not None else "không có dòng đáp án cho câu này", "json"),
    ]
    if outcome.verify is not None:
        verdict = "nhận" if outcome.verify.ok else "từ chối"
        out += ["", f"Verifier lần cuối: **{verdict}**"]
        out += [f"- {problem}" for problem in outcome.verify.problems]
    if outcome.report:
        out += ["", "Báo cáo của agent:", "", _fence(outcome.report, "text")]
    if outcome.error:
        out += ["", "Lỗi:", "", _fence(outcome.error, "text")]
    out += ["", f"## Các bước của agent shop {shop}", "", "Agent phụ trách cả shop, nên các bước dưới đây dùng chung cho mọi câu của shop. Input đầy đủ từng request ở `shops/{0}/requests.jsonl`.".format(shop)]
    out += ["", *overview_table(steps, qid=qid), "", "## Chi tiết từng bước"]
    for step in steps:
        out += ["", *_render_step(step, qid=qid, shop_log=shop_log)]
    out += ["", f"## Process ra đáp án: script cuối `code/shops/{shop}.py`", ""]
    out.append(_fence(script, "python") if script is not None else "Chưa có script.")
    return "\n".join(out) + "\n"


def write_shop_trace(run_log: RunLog, *, shop: str, outcome: ShopOutcome) -> Path:
    shop_log = run_log.shop(shop)
    steps = shop_log.steps()
    out = [
        f"# Trace agent shop {shop}",
        "",
        f"Trạng thái `{outcome.status}` · {outcome.turns} bước · {outcome.tokens:,} token",
        "",
        "## Tổng quan: action → kết quả",
        "",
        *overview_table(steps, qid=None),
        "",
        "## Chi tiết từng bước",
    ]
    for step in steps:
        out += ["", *_render_step(step, qid=None, shop_log=shop_log)]
    path = shop_log.dir / "trace.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def overview_table(steps: Sequence[StepRecord], *, qid: str | None) -> list[str]:
    rows = ["| Bước | Action | Kết quả | Token vào / ra |", "| --- | --- | --- | --- |"]
    for step in steps:
        star = " ★" if qid is not None and _mentions(step, qid) else ""
        tokens = f"{step.prompt_tokens:,} / {step.completion_tokens:,}"
        if not step.tool_calls:
            rows.append(f"| {step.turn}{star} | (không gọi tool) | harness nhắc gọi tool | {tokens} |")
            continue
        results = {output.call_id: output for output in step.outputs}
        for call in step.tool_calls:
            output = results.get(call.id)
            result = _result_brief(output.full) if output is not None else "(không chạy: bước đã kết thúc trước)"
            rows.append(f"| {step.turn}{star} | {_cell(_action_brief(call.name, call.arguments))} | {_cell(result)} | {tokens} |")
    return rows


def _action_brief(name: str, raw: str) -> str:
    try:
        arguments = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return f"`{name}` (tham số JSON hỏng)"
    if not isinstance(arguments, dict):
        return f"`{name}` (tham số không phải object)"
    if "code" in arguments:
        code_lines = [line for line in str(arguments["code"]).splitlines() if line.strip() and not line.startswith(("import ", "from "))]
        return f"`{name}` code: {code_lines[0].strip() if code_lines else '(chỉ import)'} … ({len(str(arguments['code'])):,} ký tự)"
    if "content" in arguments:
        return f"`{name}` {arguments.get('path')} ({len(str(arguments['content'])):,} ký tự)"
    if "path" in arguments:
        return f"`{name}` {arguments['path']}"
    if "report" in arguments:
        return f"`{name}` report: {str(arguments['report']).splitlines()[0] if str(arguments['report']).strip() else ''}"
    return f"`{name}`"


def _result_brief(full: str) -> str:
    lines = [line for line in full.splitlines() if line.strip()]
    if not lines:
        return "(rỗng)"
    head = lines[0]
    if head.startswith(("NOT ACCEPTED", "ACCEPTED")):
        detail = next((line[2:] for line in lines if line.startswith("- ")), lines[1] if len(lines) > 1 else "")
        return f"{head}: {detail}".rstrip(": ")
    if head.startswith("[exit") or head.startswith("[timed out"):
        body = [line for line in lines[1:] if line not in ("stdout:", "stderr:")]
        return f"{head} {body[-1] if 'Error' in full and body else (body[0] if body else '')}".strip()
    if lines[-1].startswith("[lines "):
        return lines[-1]
    return head if len(lines) == 1 else f"{head} (+{len(lines) - 1} dòng)"


def _cell(text: str) -> str:
    flat = " ".join(text.split()).replace("|", "\\|")
    return flat if len(flat) <= 140 else flat[:140] + "…"


def _render_step(step: StepRecord, *, qid: str | None, shop_log: ShopLog) -> list[str]:
    names = ", ".join(call.name for call in step.tool_calls) or "không gọi tool"
    star = " ★" if qid is not None and _mentions(step, qid) else ""
    compacted = ", ".join(f"#{index}" for index in step.compacted) or "không"
    lines = [
        f"### Bước {step.turn} · {names}{star}",
        "",
        f"Token: input {step.prompt_tokens:,} · output {step.completion_tokens:,} · {step.request_messages} message gửi lên · đã lược: {compacted} · finish_reason: `{step.finish_reason}`",
        "",
        "**Input mới gửi lên model**",
        "",
    ]
    for message in step.inputs:
        role = message.get("role")
        content = str(message.get("content") or "")
        if role == "system":
            lines.append(f"- system prompt: `{shop_log.system_prompt_path.name}` ({len(content):,} ký tự)")
        elif role == "tool":
            lines.append(f"- kết quả tool `{message.get('tool_call_id')}` của bước trước ({len(content):,} ký tự, xem Output bước trước)")
        else:
            lines += [f"- {role}:", "", _fence(content, "text")]
    lines += ["", "**Process của model**", ""]
    if step.reasoning:
        lines += ["Reasoning:", "", _fence(step.reasoning, "text"), ""]
    if step.content:
        lines += ["Nội dung:", "", _fence(step.content, "text"), ""]
    for call in step.tool_calls:
        lines += [f"Gọi `{call.name}` (`{call.id}`):", "", *_render_arguments(call.arguments), ""]
    if not step.tool_calls:
        lines += ["Không gọi tool, harness nhắc gọi tool ở bước sau.", ""]
    lines += ["**Output của tool**", ""]
    for output in step.outputs:
        cut = "" if output.full == output.sent_to_model else f" (model nhận bản cắt {len(output.sent_to_model):,}/{len(output.full):,} ký tự)"
        lines += [f"`{output.name}`{cut}:", "", _fence(output.full, "text"), ""]
    if not step.outputs:
        lines.append("Không có.")
    return lines


def _render_arguments(raw: str) -> list[str]:
    try:
        arguments = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return [_fence(raw, "text")]
    if not isinstance(arguments, dict):
        return [_fence(raw, "text")]
    lines: list[str] = []
    for key, value in arguments.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if "\n" in text:
            language = "python" if key == "code" or str(arguments.get("path", "")).endswith(".py") else "text"
            lines += [f"- `{key}`:", "", _fence(text, language)]
        else:
            lines.append(f"- `{key}`: `{text}`")
    return lines or ["(không tham số)"]


def _mentions(step: StepRecord, qid: str) -> bool:
    return any(qid in call.arguments for call in step.tool_calls) or any(qid in output.full for output in step.outputs)


def _answers_by_id(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(line, dict) and "id" in line:
            out[str(line["id"])] = line
    return out


def _fence(text: str, language: str) -> str:
    longest = max((len(run) for run in FENCE_RUN.findall(text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{language}\n{text}\n{ticks}"


def _append(path: Path, record: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def write_summary(
    run_log: RunLog,
    *,
    run_id: str,
    model: str,
    tokens_used: int,
    outcomes: Mapping[str, ShopOutcome],
    merged: MergeReport | None,
    scored: ScoreReport | None,
) -> Path:
    api_problems = _api_problems(run_log.events_path)
    out = [
        f"# Tóm tắt lần chạy {run_log.dir.name}",
        "",
        f"- run_id: `{run_id}` · model: `{model}` · token đã dùng (cộng dồn cả các lần chạy trước): {tokens_used:,}",
    ]
    if merged is not None:
        out.append(f"- Merge: {merged.answered}/{merged.questions} câu có đáp án, {merged.abstain} abstain, coverage {merged.coverage:.4f}")
    else:
        out.append("- Lần chạy chưa kết thúc: bảng dưới cập nhật sau mỗi shop")
    if scored is not None:
        out.append(f"- Điểm: {scored.score} · accuracy {scored.accuracy} · coverage {scored.coverage} · sai: {', '.join(scored.wrong_ids) or 'không'}")
    out += [
        "",
        "| Shop | Trạng thái | Bước | Token | Tool lỗi | finish bị từ chối | Không gọi tool | Output bị cắt (length) | API lỗi/retry |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    details: list[str] = []
    for shop, outcome in sorted(outcomes.items()):
        steps = run_log.shop(shop).steps()
        tool_errors = [(s.turn, o) for s in steps for o in s.outputs if o.sent_to_model.startswith("ERROR:")]
        rejected = [(s.turn, o) for s in steps for o in s.outputs if o.name == "finish" and not o.finished]
        silent = [s.turn for s in steps if not s.tool_calls]
        truncated = [s.turn for s in steps if s.finish_reason == "length"]
        api = api_problems.get(shop, [])
        out.append(
            f"| {shop} | `{outcome.status}` | {outcome.turns} | {outcome.tokens:,} | {len(tool_errors)} | {len(rejected)} | {len(silent)} | {len(truncated)} | {len(api)} |"
        )
        notes = [f"- tool lỗi ở bước {turn} `{o.name}`: {_first_line(o.sent_to_model)}" for turn, o in tool_errors]
        notes += [f"- finish bị từ chối ở bước {turn}: {'; '.join(_problem_lines(o.full))}" for turn, o in rejected]
        notes += [f"- bước {turn}: model trả lời mà không gọi tool" for turn in silent]
        notes += [f"- bước {turn}: output bị cắt vì hết max_output_tokens (tool call có thể hỏng)" for turn in truncated]
        notes += [f"- {line}" for line in api]
        if outcome.error:
            notes += ["- shop dừng vì exception:", "", _fence(outcome.error, "text")]
        if notes:
            details += ["", f"## {shop}", "", f"Log: `shops/{shop}/steps.jsonl`, câu hỏi trong `questions/`.", "", *notes]
    out += details or ["", "Không có chỗ bất thường."]
    path = run_log.dir / "summary.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def _api_problems(events_path: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    if not events_path.exists():
        return found
    for raw in events_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        if event.get("event") == "api_error":
            found.setdefault(str(event.get("shop")), []).append(f"API lỗi status {event.get('status')} lần thử {event.get('attempt')}: {_first_line(str(event.get('message')))}")
        elif event.get("event") == "api_retry":
            found.setdefault(str(event.get("shop")), []).append(f"API retry lần {event.get('attempt')} ({event.get('reason')}), chờ {event.get('delay_s')}s")
    return found


def _first_line(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= 200 else line[:200] + "…"


def _problem_lines(text: str) -> list[str]:
    return [line[2:] for line in text.splitlines() if line.startswith("- ")][:5] or [_first_line(text)]
