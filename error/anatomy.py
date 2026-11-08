from __future__ import annotations

import collections
import glob
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.argv = ["final_score", str(ROOT / "experiments/EXP-20261105-07-domain-helpers")]
exec((ROOT / "experiments/EXP-20261105-07-domain-helpers/code/final_score.py").read_text(encoding="utf-8").split("Q, G = load(")[0])

from datamate.shop import Shop
from datamate_agent.agent import NORM_ROOT, local_runner, parse_answer, prepare_workspace
from datamate_agent.fewshot import LINKED_KEYS, entities_of, linked_match
from datamate_agent.intents import period_of
from datamate_agent.question_norm import normalize

LOG_DIRS = ("experiments/EXP-20261106-01-deterministic-fixes/run/public_retry/*", "experiments/EXP-20261106-01-deterministic-fixes/run/public/*", "experiments/EXP-20261105-07-domain-helpers/run/public/v9-20261105-141323", "experiments/EXP-20261105-07-domain-helpers/run/public/v9-20261105-132202")
EXAMPLE = re.compile(r"^- (.*)\n  FINAL (\w+): (.*)$", re.M)
PERIOD = re.compile(r"clock\.\w+\([^()]*\)")
LITERAL = {"item": re.compile(r"item=(['\"])(.*?)\1"), "group": re.compile(r"group=(['\"])(.*?)\1"), "customer": re.compile(r"customer=(['\"])(.*?)\1"), "ingredient": re.compile(r"ingredient=(['\"])(.*?)\1")}
WORK = ROOT / "error" / "anatomy_work"


def rows(path: Path | str) -> dict[str, dict]:
    return {row["id"]: row for row in map(json.loads, Path(path).read_text(encoding="utf-8").splitlines()) if row}


def find_log(qid: str, answer: dict) -> str | None:
    for pattern in LOG_DIRS:
        for folder in sorted(glob.glob(str(ROOT / pattern)), reverse=True):
            path = Path(folder) / f"{qid}.log"
            if path.exists() and json.dumps(answer, ensure_ascii=False) in path.read_text(encoding="utf-8"):
                return str(path)
    return None


def adapt(code: str, *, period: str | None, names: dict[str, str]) -> str:
    """Code của ví dụ đổi sang kỳ và tên của câu hỏi; ví dụ có nhiều kỳ thì chỉ đổi khi câu hỏi cũng chỉ có một kỳ."""
    out = code
    if period is not None and len(set(PERIOD.findall(code))) == 1:
        out = PERIOD.sub(period, out)
    for key, pattern in LITERAL.items():
        if key in names:
            out = pattern.sub(lambda match, key=key: f"{key}={json.dumps(names[key], ensure_ascii=False)}", out)
    return out


def main() -> int:
    questions = rows(ROOT / "public_test/questions.jsonl")
    truth = rows(ROOT / "experiments/EXP-20261104-05-public-1000-v7/inputs/claude_reference.jsonl")
    answers = rows(ROOT / "error/answers_public_current.jsonl")
    labels = json.loads((ROOT / "error/labels_public.json").read_text(encoding="utf-8"))
    group_of = {qid: group for group, row in labels.items() for qid in row["ids"]}
    wrong = [qid for qid in questions if status(answers.get(qid), truth[qid], questions[qid]["business_id"], True) != "ok"]
    entities: dict[str, dict] = {}
    jobs = []
    report = []
    for qid in wrong:
        question = questions[qid]
        shop = question["business_id"]
        log = find_log(qid, answers[qid])
        text = Path(log).read_text(encoding="utf-8") if log else ""
        user = text.split("\n--------\nUSER:\n", 1)[1].split("\n--------\nASSISTANCE:", 1)[0] if log else ""
        examples = EXAMPLE.findall(user)
        if shop not in entities:
            entities[shop] = entities_of(Shop(NORM_ROOT / "public_test" / shop, as_of=question["as_of_date"], calendar=str(ROOT / "public_test/calendar.csv")))
        folded = normalize(question["question"])
        names = {key: match for key, found in entities[shop].items() if key in LINKED_KEYS and (match := linked_match(question["question"], folded, found))}
        period = period_of(folded, as_of=date.fromisoformat(question["as_of_date"]))
        candidates = [(rank, kind, adapt(code, period=period, names=names)) for rank, (_, kind, code) in enumerate(examples)]
        final = re.findall(r"^\[CODE\]\n(.*)", text, re.M)
        report.append({"id": qid, "shop": shop, "group": group_of.get(qid, "?"), "question": question["question"], "truth": truth[qid], "got": answers[qid], "log": log, "examples": [{"question": q, "type": k, "code": c} for q, k, c in examples], "final_code": final[-1] if final else None, "candidates": [{"rank": rank, "type": kind, "code": code} for rank, kind, code in candidates]})
        jobs.extend((len(report) - 1, rank, kind, code) for rank, kind, code in candidates)

    def run(job: tuple[int, int, str, str]) -> tuple[int, int, str]:
        index, rank, kind, code = job
        item = report[index]
        question = questions[item["id"]]
        work = prepare_workspace(WORK / f"{item['id']}_{rank}", raw_dir=(ROOT / "public_test/data" / item["shop"]).resolve(), norm_dir=(NORM_ROOT / "public_test" / item["shop"]).resolve(), calendar=ROOT / "public_test/calendar.csv")
        result = local_runner(work.resolve(), as_of=question["as_of_date"])(code)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if result.exit_code != 0 or not lines:
            return index, rank, "error"
        try:
            answer = {"id": item["id"], "type": "percent" if kind == "number" and item["truth"]["type"] == "percent" else kind, "answer": parse_answer(lines[-1].strip(), kind)}
        except (ValueError, SyntaxError):
            return index, rank, "error"
        return index, rank, status(answer, item["truth"], item["shop"], True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for index, rank, verdict in pool.map(run, jobs):
            report[index]["candidates"][rank]["verdict"] = verdict
    for item in report:
        verdicts = [candidate.get("verdict") for candidate in item["candidates"]]
        item["stage"] = "không có log" if item["log"] is None else "top-1 đúng mà model không theo" if verdicts[:1] == ["ok"] else "ví dụ đúng ở hạng 2-4" if "ok" in verdicts else "không ví dụ nào ra đúng"
    (ROOT / "error/anatomy.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in report), encoding="utf-8")
    print("tổng", len(report), collections.Counter(item["stage"] for item in report).most_common())
    by_group = collections.defaultdict(collections.Counter)
    for item in report:
        by_group[item["group"]][item["stage"]] += 1
    for group, count in sorted(by_group.items()):
        print(f"  {group:3} {dict(count)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
