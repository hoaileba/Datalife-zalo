from __future__ import annotations

import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
RUN_NAME = sys.argv[1] if len(sys.argv) > 1 else "public1000"
sys.argv = ["final_score", str(ROOT / "experiments/EXP-20261105-07-domain-helpers")]
exec((ROOT / "experiments/EXP-20261105-07-domain-helpers/code/final_score.py").read_text(encoding="utf-8").split("Q, G = load(")[0])

from datamate.shop import Shop
from datamate_agent.agent import DEFAULT_SHOWN, NORM_ROOT, RERANK_CANDIDATES, RERANK_MARGIN, mask_question
from datamate_agent.fewshot import entities_of, load_library

EXP_DIR = ROOT / "experiments/EXP-20261107-04-example-selection"
EXP03 = ROOT / "experiments/EXP-20261107-03-gates-public1000/out"
FIRST_EXAMPLE = re.compile(r"^- (.*)\n  FINAL \w+: ", re.M)


def rows(path: Path | str) -> dict[str, dict]:
    return {row["id"]: row for row in map(json.loads, Path(path).read_text(encoding="utf-8").splitlines()) if row}


def shown_first(log: str) -> str | None:
    user = log.split("\nUSER:\n", 1)[1] if "\nUSER:\n" in log else ""
    found = FIRST_EXAMPLE.search(user)
    return found.group(1) if found else None


def main() -> int:
    run = Path(sorted(glob.glob(str(EXP_DIR / f"run/{RUN_NAME}/*")))[-1])
    questions = rows(ROOT / "public_test/questions.jsonl")
    truth = rows(ROOT / "experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl")
    sets = {"gemma cũ 0,849": rows(ROOT / "error/answers_public_current.jsonl"), "EXP-03 cuối": rows(EXP03 / "answers_public_final.jsonl"), "EXP-03 nộp": rows(EXP03 / "submission.jsonl"), "EXP-04 mới": rows(run / "answers.jsonl")}
    verdict = {name: {qid: status(found.get(qid), truth[qid], questions[qid]["business_id"], True) for qid in questions} for name, found in sets.items()}
    for name, found in verdict.items():
        count = Counter(found.values())
        print(f"{name:16} PA={(count['ok'] - count['wrong']) / 1000:+.3f}  đúng={count['ok']} sai={count['wrong']} trống={count['blank']}")
    library = load_library()
    shops: dict[str, Shop] = {}
    entities: dict[str, dict] = {}
    route: dict[str, str] = {}
    for qid, question in questions.items():
        shop_id = question["business_id"]
        if shop_id not in shops:
            shops[shop_id] = Shop(NORM_ROOT / "public_test" / shop_id, as_of=question["as_of_date"], calendar=str(ROOT / "public_test/calendar.csv"))
            entities[shop_id] = entities_of(shops[shop_id])
        scored = library.scored(mask_question(question["question"], entities[shop_id]), count=RERANK_CANDIDATES, domains=shops[shop_id].domains(), exclude=question["question"])
        if len(scored) < 2 or scored[0][0] - scored[1][0] >= RERANK_MARGIN:
            route[qid] = "TF-IDF chắc"
            continue
        first = shown_first((run / f"{qid}.log").read_text(encoding="utf-8"))
        route[qid] = "gemma giữ top-1" if first == scored[0][1].question else "gemma đổi top-1" if first is not None else "không đọc được log"
    print(f"\nđường chọn ví dụ (margin < {RERANK_MARGIN}, {RERANK_CANDIDATES} ứng viên, hiện {DEFAULT_SHOWN}):", dict(Counter(route.values())))
    for base in ("EXP-03 cuối", "EXP-03 nộp"):
        print(f"\nso với {base}:")
        for name in ("TF-IDF chắc", "gemma giữ top-1", "gemma đổi top-1", "không đọc được log"):
            ids = [qid for qid in questions if route[qid] == name]
            if not ids:
                continue
            gain = sum(verdict[base][qid] != "ok" and verdict["EXP-04 mới"][qid] == "ok" for qid in ids)
            loss = sum(verdict[base][qid] == "ok" and verdict["EXP-04 mới"][qid] != "ok" for qid in ids)
            delta = sum((verdict["EXP-04 mới"][qid] == "ok") - (verdict["EXP-04 mới"][qid] == "wrong") - (verdict[base][qid] == "ok") + (verdict[base][qid] == "wrong") for qid in ids)
            print(f"  {name:18} {len(ids):4} câu  được {gain:3}  mất {loss:3}  ΔPA {delta / 1000:+.3f}")
    changed = [{"id": qid, "question": questions[qid]["question"], "route": route[qid], "exp03": verdict["EXP-03 cuối"][qid], "exp04": verdict["EXP-04 mới"][qid], "truth": truth[qid], "got_exp03": sets["EXP-03 cuối"].get(qid), "got_exp04": sets["EXP-04 mới"].get(qid)} for qid in questions if verdict["EXP-03 cuối"][qid] != verdict["EXP-04 mới"][qid]]
    (EXP_DIR / f"out/changed_vs_exp03_{RUN_NAME}.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in changed), encoding="utf-8")
    (EXP_DIR / f"out/route_{RUN_NAME}.json").write_text(json.dumps(route, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(changed)} câu đổi verdict so với EXP-03 cuối, ghi out/changed_vs_exp03_{RUN_NAME}.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
