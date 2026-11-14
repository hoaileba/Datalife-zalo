from __future__ import annotations

import argparse
import json
import pickle
import random
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Sequence

from datamate_agent.score import is_correct

from .catalog import build_catalog, cookbook_titles, data_lookup, load_calendar, load_shop, rulebook_changes, shop_questions
from .teacher import SYSTEM_PROMPT, openrouter_complete, solve

DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
DEFAULT_SEED = 20261111


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def prepare_shop(*, shop: str, train: Path, cache: Path, changes: Sequence[str]) -> Path:
    """Bảng và catalog của một shop, đọc file thô một lần rồi lưu lại."""
    folder = cache / shop
    tables_path = folder / "tables.pkl"
    if tables_path.exists() and (folder / "catalog.json").exists():
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    frames, metas = load_shop(train / "data" / shop)
    calendar = load_calendar(train / "calendar.csv")
    catalog = build_catalog(shop_dir=train / "data" / shop, frames=frames, metas=metas, calendar=calendar, changes=changes)
    with tables_path.open("wb") as handle:
        pickle.dump({**frames, "calendar": calendar}, handle)
    (folder / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    return folder


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sinh trajectory của teacher theo protocol multi-turn (catalog + cookbook + code pandas) trên câu train, chấm theo gold")
    parser.add_argument("--train", type=Path, default=Path("train"))
    parser.add_argument("--questions", type=Path, default=None, help="mặc định <train>/split/train_questions.jsonl: không đụng 450 câu test_* giữ để đo")
    parser.add_argument("--answers", type=Path, default=None, help="mặc định <train>/answers.jsonl")
    parser.add_argument("--standard-rulebook", type=Path, default=None, help="luật chuẩn mà cookbook viết lại; mặc định <train>/rulebook.md")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning", action="store_true", help="bật reasoning của teacher (đắt hơn)")
    parser.add_argument("--parallel", type=int, default=5)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", nargs="*", default=None, help="chỉ chạy các id này")
    args = parser.parse_args(argv)
    questions_path = args.questions or args.train / "split" / "train_questions.jsonl"
    gold = {str(row["id"]): row for row in _rows(args.answers or args.train / "answers.jsonl")}
    pool = _rows(questions_path)
    chosen = [row for row in pool if row["id"] in set(args.only)] if args.only else random.Random(args.seed).sample(pool, min(args.count, len(pool)))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "sample.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in chosen), encoding="utf-8")
    trajectories = args.out / "trajectories.jsonl"
    kept = [row for row in _rows(trajectories) if not row["reason"].startswith("error")] if trajectories.exists() else []
    if trajectories.exists():
        trajectories.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in kept), encoding="utf-8")
    done = {row["id"] for row in kept}
    todo = [row for row in chosen if row["id"] not in done]
    standard = (args.standard_rulebook or args.train / "rulebook.md").read_text(encoding="utf-8")
    changes = rulebook_changes((args.train / "rulebook.md").read_text(encoding="utf-8"), standard, cookbook_titles(SYSTEM_PROMPT))
    print(f"{len(chosen)} câu, đã có {len(done)}, còn {len(todo)}; rulebook_changes {len(changes)} dòng", flush=True)
    cache = args.out / "shops"
    folders: dict[str, Path] = {}
    for shop in sorted(shop_questions(todo)):
        started = time.monotonic()
        folders[shop] = prepare_shop(shop=shop, train=args.train, cache=cache, changes=changes)
        print(f"catalog {shop} {time.monotonic() - started:.0f}s", flush=True)
    complete = openrouter_complete(model=args.model, seed=args.seed, reasoning=args.reasoning)
    frames_cache: dict[str, dict[str, Any]] = {}
    lock = threading.Lock()

    def lookup(question: dict[str, Any]) -> list[dict[str, Any]]:
        shop = str(question["business_id"])
        with lock:
            if shop not in frames_cache:
                with (folders[shop] / "tables.pkl").open("rb") as handle:
                    frames_cache[shop] = {name: frame for name, frame in pickle.load(handle).items() if name != "calendar"}
        return data_lookup(str(question["question"]), frames_cache[shop])

    def one(question: dict[str, Any]) -> dict[str, Any]:
        folder = folders[str(question["business_id"])]
        catalog = json.loads((folder / "catalog.json").read_text(encoding="utf-8"))
        try:
            trajectory = solve(question, catalog=catalog, lookup=lookup(question), tables_path=folder / "tables.pkl", complete=complete)
        except Exception as error:
            trajectory = {"id": question["id"], "business_id": question["business_id"], "question": question["question"], "final": {"type": "abstain"}, "reason": f"error: {type(error).__name__}: {str(error)[:300]}", "calls": 0, "usage": [], "messages": [], "events": []}
        truth = gold.get(str(question["id"]))
        trajectory["gold"] = truth
        trajectory["model"] = args.model
        trajectory["correct"] = bool(truth) and trajectory["final"]["type"] != "abstain" and is_correct({"id": question["id"], **trajectory["final"]}, truth)
        return trajectory

    with ThreadPoolExecutor(max_workers=args.parallel) as executor, trajectories.open("a", encoding="utf-8") as sink:
        futures = [executor.submit(one, question) for question in todo]
        for index, future in enumerate(as_completed(futures), start=1):
            trajectory = future.result()
            with lock:
                sink.write(json.dumps(trajectory, ensure_ascii=False, default=str) + "\n")
                sink.flush()
            cost = sum(item.get("cost") or 0 for item in trajectory["usage"])
            print(f"{index}/{len(todo)} {trajectory['id']} {trajectory['reason']} calls={trajectory['calls']} {'ĐÚNG' if trajectory['correct'] else 'sai'} ${cost:.4f}", flush=True)
    rows = _rows(trajectories)
    summary = {
        "questions": len(rows),
        "correct": sum(row["correct"] for row in rows),
        "accuracy": round(sum(row["correct"] for row in rows) / max(len(rows), 1), 4),
        "reasons": dict(Counter(row["reason"].split(":")[0] for row in rows)),
        "calls": dict(Counter(row["calls"] for row in rows)),
        "cost_usd": round(sum(item.get("cost") or 0 for row in rows for item in row["usage"]), 4),
        "prompt_tokens": sum(item.get("prompt_tokens") or 0 for row in rows for item in row["usage"]),
        "completion_tokens": sum(item.get("completion_tokens") or 0 for row in rows for item in row["usage"]),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
