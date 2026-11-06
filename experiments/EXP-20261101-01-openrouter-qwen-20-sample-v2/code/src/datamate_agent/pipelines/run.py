from __future__ import annotations

import argparse
import json
import traceback
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from datamate.fmt import load_questions
from tqdm import tqdm

from ..connectors import ChatClient, OpenRouterClient
from ..models import ConnectorConfig, RunConfig, RunState, ShopOutcome, load_run_config, run_env
from ..modules.agent import ShopAgent
from ..modules.budget import TokenBudget
from ..modules.executor import Executor, build_executor
from ..modules.merge import MergeReport, merge_answers
from ..modules.paths import PathSpace, WorkLayout
from ..modules.prompts import script_skeleton, system_prompt, task_prompt
from ..modules.runlog import RunLog, write_question_logs, write_shop_trace, write_summary
from ..modules.score import ScoreReport, score_submission
from ..modules.tools import ToolBox
from ..modules.verify import Verifier
from ..utils.events import EventLog, configure_console

SRC_ROOT = Path(__file__).resolve().parents[2]


class RunPipeline:
    """Ghép các module: chia batch, chạy shop agent, lưu trạng thái, merge, chấm nếu có gold."""

    def __init__(self, config: RunConfig, *, client: ChatClient | None, executor: Executor, run_log: RunLog, events: EventLog, env: str) -> None:
        self._config = config
        self._client = client
        self._executor = executor
        self._env = env
        self._layout = WorkLayout(config.output_dir)
        self._layout.root.mkdir(parents=True, exist_ok=True)
        self._run_log = run_log
        self._events = events
        self._outcomes: dict[str, ShopOutcome] = {}
        self._space = PathSpace(data_root=config.dataset_root, work_root=self._layout.root)
        questions = load_questions(config.questions_path)
        self._questions = tuple(q for q in questions if not config.shops or q["business_id"] in config.shops)
        by_shop: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for question in self._questions:
            by_shop[str(question["business_id"])].append(question)
        self._by_shop = {shop: tuple(rows) for shop, rows in sorted(by_shop.items())}
        missing = sorted(set(config.shops) - set(self._by_shop))
        if missing:
            raise ValueError(f"shops without questions in {config.questions_file}: {missing}")
        self._verifier = Verifier(
            question_ids={shop: frozenset(q["id"] for q in rows) for shop, rows in self._by_shop.items()},
            layout=self._layout,
            executor=executor,
            allow_abstain=config.allow_abstain,
        )

    def run(self, *, merge_only: bool) -> tuple[RunState, MergeReport, ScoreReport | None]:
        state = self._load_state()
        self._events.emit("run_start", run_id=self._config.run_id, log_dir=str(self._run_log.dir), env=self._env, model=self._config.model.name, executor=self._config.executor.kind, shops=list(self._by_shop), merge_only=merge_only, tokens_used=state.tokens_used)
        if not merge_only:
            state = self._run_agents(state)
        merged = merge_answers(questions=self._questions, answers_dir=self._layout.answers_dir(), submission=self._layout.submission())
        self._events.emit("merge", questions=merged.questions, answered=merged.answered, abstain=merged.abstain, coverage=round(merged.coverage, 4), missing=len(merged.missing), problems=list(merged.problems), per_type=merged.per_type)
        scored = None
        if self._config.truth_path is not None:
            scored = score_submission(self._layout.submission(), self._config.truth_path)
            self._layout.score().write_text(scored.model_dump_json(indent=2), encoding="utf-8")
            self._events.emit("score", score=scored.score, accuracy=scored.accuracy, coverage=scored.coverage, right=scored.right, wrong=scored.wrong, blank=scored.blank)
        statuses = {shop: outcome.status for shop, outcome in state.shops.items()}
        self._events.emit("run_end", tokens_used=state.tokens_used, statuses=statuses)
        self._write_summary(tokens_used=state.tokens_used, merged=merged, scored=scored)
        return state, merged, scored

    def _write_summary(self, *, tokens_used: int, merged: MergeReport | None, scored: ScoreReport | None) -> None:
        write_summary(
            self._run_log,
            run_id=self._config.run_id,
            model=self._config.model.name,
            tokens_used=tokens_used,
            outcomes=self._outcomes,
            merged=merged,
            scored=scored,
        )

    def _run_agents(self, state: RunState) -> RunState:
        if self._client is None:
            raise ValueError("chat client required unless merge_only")
        budget = TokenBudget(self._config.budget, already_used=state.tokens_used)
        rulebook = self._config.rulebook_path.read_text(encoding="utf-8")
        system = system_prompt(rulebook=rulebook, allow_abstain=self._config.allow_abstain)
        queue = sorted((shop for shop in self._by_shop if not state.is_verified(shop)), key=lambda shop: (-len(self._by_shop[shop]), shop))
        total = sum(len(rows) for rows in self._by_shop.values())
        done = total - sum(len(self._by_shop[shop]) for shop in queue)
        accepted = done
        running: dict[Future[ShopOutcome], str] = {}
        with tqdm(total=total, initial=done, unit="câu", desc="câu hỏi", dynamic_ncols=True) as bar, ThreadPoolExecutor(max_workers=self._config.parallel_shops) as pool:
            while queue or running:
                while queue and len(running) < self._config.parallel_shops and not budget.exhausted():
                    shop = queue.pop(0)
                    self._events.emit("shop_queued", shop=shop, questions=len(self._by_shop[shop]), tokens_used=budget.used)
                    running[pool.submit(self._run_shop, shop, system, budget)] = shop
                if not running:
                    break
                bar.set_postfix_str(f"đang chạy {', '.join(sorted(running.values()))}")
                finished, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in finished:
                    shop = running.pop(future)
                    outcome = self._settle(shop, future)
                    state = self._save_state(state, outcome, budget.used)
                    write_shop_trace(self._run_log, shop=shop, outcome=outcome)
                    written = write_question_logs(self._run_log, shop=shop, questions=self._by_shop[shop], layout=self._layout, outcome=outcome)
                    self._events.emit("question_logs", shop=shop, status=outcome.status, files=len(written))
                    self._outcomes[shop] = outcome
                    self._write_summary(tokens_used=budget.used, merged=None, scored=None)
                    count = len(self._by_shop[shop])
                    done += count
                    accepted += count if outcome.status == "verified" else 0
                    bar.update(count)
                    bar.set_postfix_str(f"{shop} {outcome.status} · nhận {accepted}/{done} · {budget.used:,} token")
                    self._events.emit("progress", done=done, total=total, accepted=accepted, last_shop=shop, last_status=outcome.status, tokens_used=budget.used)
            if queue:
                self._events.emit("run_paused", reason="budget", tokens_used=budget.used, stop_at=self._config.budget.stop_at, remaining_shops=queue)
        return state.model_copy(update={"tokens_used": budget.used})

    def _settle(self, shop: str, future: Any) -> ShopOutcome:
        if self._env == "dev":
            return future.result()
        try:
            return future.result()
        except Exception as error:
            trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            self._events.emit("shop_error", shop=shop, error=repr(error), traceback=trace)
            return ShopOutcome(shop=shop, status="error", turns=0, tokens=0, error=trace)

    def _run_shop(self, shop: str, system: str, budget: TokenBudget) -> ShopOutcome:
        questions = self._by_shop[shop]
        inputs = self._layout.questions(shop)
        inputs.parent.mkdir(parents=True, exist_ok=True)
        inputs.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in questions), encoding="utf-8")
        script = self._layout.script(shop)
        if not script.exists():
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(script_skeleton(shop=shop, questions=questions), encoding="utf-8")
        shop_log = self._run_log.shop(shop)
        shop_log.open_questions(questions)
        toolbox = ToolBox(
            shop=shop,
            space=self._space,
            layout=self._layout,
            executor=self._executor,
            verifier=self._verifier,
            output_limit=self._config.tool_output_char_limit,
            events=self._events,
        )
        agent = ShopAgent(
            shop=shop,
            client=self._client,
            toolbox=toolbox,
            budget=budget,
            system_prompt=system,
            task_prompt=task_prompt(shop=shop, questions=questions),
            max_turns=self._config.max_turns,
            stuck_after=self._config.stuck_after,
            context_char_limit=self._config.context_char_limit,
            shop_log=shop_log,
            events=self._events,
        )
        outcome = agent.run()
        if outcome.status == "verified":
            self._log_answers(shop)
        return outcome

    def _log_answers(self, shop: str) -> None:
        for raw in self._layout.answers(shop).read_text(encoding="utf-8").splitlines():
            if raw.strip():
                line = json.loads(raw)
                self._events.emit("question", shop=shop, id=line["id"], type=line["type"], answer=line.get("answer"), reason=line.get("reason"))

    def _load_state(self) -> RunState:
        path = self._layout.state()
        if not path.exists():
            return RunState(run_id=self._config.run_id)
        state = RunState.model_validate_json(path.read_text(encoding="utf-8"))
        if state.run_id != self._config.run_id:
            raise ValueError(f"output_dir belongs to run {state.run_id!r}, config says {self._config.run_id!r}")
        return state

    def _save_state(self, state: RunState, outcome: ShopOutcome, tokens_used: int) -> RunState:
        updated = state.model_copy(update={"tokens_used": tokens_used, "shops": {**state.shops, outcome.shop: outcome}})
        self._layout.state().write_text(updated.model_dump_json(indent=2), encoding="utf-8")
        return updated


def build_pipeline(config: RunConfig, *, merge_only: bool) -> RunPipeline:
    layout = WorkLayout(config.output_dir)
    layout.root.mkdir(parents=True, exist_ok=True)
    run_log = RunLog(layout.run_logs(), started_at=datetime.now())
    configure_console(files=(run_log.console_path, layout.combined_log()))
    events = EventLog(run_log.events_path)
    executor = build_executor(config.executor, data_root=config.dataset_root.resolve(), work_root=layout.root, src_root=SRC_ROOT)
    client = None
    if not merge_only:
        client = OpenRouterClient(ConnectorConfig.from_env(), model=config.model, retry=config.retry, events=events)
    return RunPipeline(config, client=client, executor=executor, run_log=run_log, events=events, env=run_env())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chạy shop agent qua API OpenAI-compatible rồi merge thành submission.jsonl")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--shops", nargs="*", default=None, help="chỉ chạy các shop này, ghi đè `shops` trong config")
    parser.add_argument("--merge-only", action="store_true", help="không gọi model, chỉ merge và chấm")
    args = parser.parse_args(argv)
    config = load_run_config(args.config)
    if args.shops:
        config = config.model_copy(update={"shops": tuple(args.shops)})
    _, merged, scored = build_pipeline(config, merge_only=args.merge_only).run(merge_only=args.merge_only)
    unfinished = merged.questions - merged.answered
    return 0 if scored is not None or unfinished == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
