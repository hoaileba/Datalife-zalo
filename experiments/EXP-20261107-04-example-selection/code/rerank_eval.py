from __future__ import annotations

import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from datamate_agent.agent import llm_client
from datamate_agent.example_rerank import rerank
from datamate_agent.fewshot import load_library
from retrieval_eval import public_items

EXP_DIR = ROOT / "experiments/EXP-20261107-04-example-selection"
CANDIDATES = 8


def main() -> int:
    model = sys.argv[1]
    library = load_library()
    analysis = {row["id"]: row for row in map(json.loads, (ROOT / "experiments/EXP-20261107-03-gates-public1000/out/analysis_public_gemma.jsonl").read_text(encoding="utf-8").splitlines())}
    sample = random.Random(20261107).sample(list(library.examples), 300)
    jobs = [("public", qid, question, masked, intent, analysis[qid]["rewritten"] if analysis[qid]["problem"] is None else None) for qid, _, question, masked, intent in public_items()]
    jobs += [("thư viện", example.question, example.question, example.masked, example.intent, None) for example in sample]
    complete = llm_client(model=model, seed=20261103)

    def one(job: tuple) -> dict:
        source, key, question, masked, intent, rewritten = job
        found = library.nearest(masked, count=CANDIDATES, exclude=question)
        try:
            ordered = rerank(question, found, complete=complete, rewritten=rewritten)
            error = None
        except Exception as exc:
            ordered, error = found, f"{type(exc).__name__}: {str(exc)[:80]}"
        return {"source": source, "key": key, "intent": intent, "tfidf_top1": found[0].intent, "rerank_top1": ordered[0].intent, "in_top": intent in {item.intent for item in found}, "error": error}

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(one, jobs))
    (EXP_DIR / f"out/rerank_eval_{model.split('/')[-1]}.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    for source in ("public", "thư viện"):
        part = [row for row in rows if row["source"] == source]
        tfidf = sum(row["tfidf_top1"] == row["intent"] for row in part)
        llm = sum(row["rerank_top1"] == row["intent"] for row in part)
        covered = sum(row["in_top"] for row in part)
        print(f"{source} ({len(part)} câu): TF-IDF top-1 {tfidf / len(part):.1%}, gemma xếp lại top-1 {llm / len(part):.1%}, loại đúng có trong {CANDIDATES} ứng viên {covered / len(part):.1%}, lỗi API {sum(row['error'] is not None for row in part)}")
        print(f"   TF-IDF đúng → gemma sai: {sum(row['tfidf_top1'] == row['intent'] != row['rerank_top1'] for row in part)}, TF-IDF sai → gemma đúng: {sum(row['tfidf_top1'] != row['intent'] == row['rerank_top1'] for row in part)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
