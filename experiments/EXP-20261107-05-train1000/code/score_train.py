from __future__ import annotations

import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments/EXP-20261107-04-example-selection/code"))
sys.argv = ["final_score", str(ROOT / "experiments/EXP-20261105-07-domain-helpers")]
exec((ROOT / "experiments/EXP-20261105-07-domain-helpers/code/final_score.py").read_text(encoding="utf-8").split("Q, G = load(")[0].replace("artifacts/norm/public_test/", str(ROOT / "artifacts/norm/train") + "/"))

from datamate.shop import Shop
from datamate_agent.agent import NORM_ROOT, RERANK_CANDIDATES, RERANK_MARGIN, mask_question
from datamate_agent.fewshot import entities_of, load_library
from follow_rate import parts, skeleton

EXP_DIR = ROOT / "experiments/EXP-20261107-05-train1000"
ORACLE = ROOT / "experiments/EXP-20261106-04-pos-header-detail/out/oracle_train.jsonl"


def rows(path: Path | str) -> dict[str, dict]:
    return {row["id"]: row for row in map(json.loads, Path(path).read_text(encoding="utf-8").splitlines()) if row}


def stage(*, answer: dict | None, gold: dict, oracle: dict, examples: list[str], final: str | None) -> str:
    kind = (answer or {}).get("type")
    if gold["type"] == "unanswerable":
        return "gold không trả lời được, agent vẫn trả lời"
    if kind in (None, "abstain", "unanswerable"):
        return "agent bỏ trống / báo không trả lời được"
    if not oracle["ok"]:
        return "oracle cũng sai (thiếu helper hoặc dữ liệu)"
    if final is None:
        return "không có code cuối"
    want = skeleton(oracle["code"])
    if skeleton(final) == want:
        return "đúng hàm, sai tham số / kỳ / tên" if kind == gold["type"] else "đúng hàm, sai dạng đáp án"
    ranks = [index for index, code in enumerate(examples) if skeleton(code) == want]
    if ranks[:1] == [0]:
        return "top-1 đúng hàm, model không theo"
    if ranks:
        return "ví dụ đúng hàm ở hạng 2–4"
    return "không ví dụ nào đúng hàm"


def main() -> int:
    run = Path(sorted(glob.glob(str(EXP_DIR / "run/train1000/*")))[-1])
    questions = rows(EXP_DIR / "out/train1000.jsonl")
    gold = rows(ROOT / "train/answers.jsonl")
    oracle = rows(ORACLE)
    answers = rows(run / "answers.jsonl")
    if "--partial" in sys.argv[1:] or len(answers) < len(questions):
        questions = {qid: row for qid, row in questions.items() if qid in answers}
    lenient = {qid: status(answers.get(qid), gold[qid], questions[qid]["business_id"], True) for qid in questions}
    strict = {qid: status(answers.get(qid), gold[qid], questions[qid]["business_id"], False) for qid in questions}
    for name, verdict in (("lenient", lenient), ("strict", strict)):
        count = Counter(verdict.values())
        print(f"{name:8} PA={(count['ok'] - count['wrong']) / len(questions):+.3f}  đúng={count['ok']} sai={count['wrong']} trống={count['blank']}")
    print(f"oracle đúng {sum(oracle[qid]['ok'] for qid in questions)}/{len(questions)}")
    library = load_library()
    shops: dict[str, Shop] = {}
    entities: dict[str, dict] = {}
    report = []
    by = defaultdict(Counter)
    for qid, question in questions.items():
        shop_id = question["business_id"]
        if shop_id not in shops:
            shops[shop_id] = Shop(NORM_ROOT / "train" / shop_id, as_of=question["as_of_date"], calendar=str(ROOT / "train/calendar.csv"))
            entities[shop_id] = entities_of(shops[shop_id])
        scored = library.scored(mask_question(question["question"], entities[shop_id]), count=RERANK_CANDIDATES, domains=shops[shop_id].domains(), exclude=question["question"], shop=shop_id)
        log = (run / f"{qid}.log").read_text(encoding="utf-8") if (run / f"{qid}.log").exists() else ""
        examples, final = parts(log)
        sure = len(scored) < 2 or scored[0][0] - scored[1][0] >= RERANK_MARGIN
        route = "TF-IDF chắc" if sure else "gemma giữ top-1" if examples and scored and examples[0] == scored[0][1].code else "gemma đổi top-1"
        verdict = lenient[qid]
        for key, value in (("shop", shop_id), ("dạng gold", gold[qid]["type"]), ("đường chọn ví dụ", route), ("oracle", "oracle đúng" if oracle[qid]["ok"] else "oracle sai")):
            by[key, value][verdict] += 1
        if verdict == "ok":
            continue
        where = stage(answer=answers.get(qid), gold=gold[qid], oracle=oracle[qid], examples=examples, final=final)
        report.append({"id": qid, "shop": shop_id, "verdict": verdict, "stage": where, "route": route, "question": question["question"], "gold": gold[qid], "got": answers.get(qid), "final_code": final, "oracle_code": oracle[qid]["code"] if oracle[qid]["ok"] else None, "top1": examples[0] if examples else None, "api_error": "LỖI API" in log})
    for group in ("dạng gold", "đường chọn ví dụ", "oracle", "shop"):
        print(f"\ntheo {group}:")
        for (key, value), count in sorted(by.items(), key=lambda item: -sum(item[1].values())):
            if key == group:
                total = sum(count.values())
                print(f"  {value:22} {total:4} câu  PA={(count['ok'] - count['wrong']) / total:+.3f}  sai={count['wrong']} trống={count['blank']}")
    print(f"\n{len(report)} câu không đúng, theo giai đoạn:")
    for name, count in Counter(item["stage"] for item in report).most_common():
        sub = [item for item in report if item["stage"] == name]
        print(f"  {name:44} {count:3}  (sai {sum(item['verdict'] == 'wrong' for item in sub)}, trống {sum(item['verdict'] == 'blank' for item in sub)})")
    print("lỗi API:", sum(item["api_error"] for item in report))
    (EXP_DIR / "out/errors_train1000.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
