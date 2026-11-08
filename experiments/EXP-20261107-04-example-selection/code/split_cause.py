from __future__ import annotations

import glob
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXP_DIR = ROOT / "experiments/EXP-20261107-04-example-selection"
EXP03_RUNS = ("api_retry", "raw_retrieval", "gate_rerun", "public1000")
EXAMPLES = re.compile(r"^- (.*)\n  FINAL \w+: ", re.M)


def shown(log: str) -> tuple[str, ...]:
    user = log.split("\nUSER:\n", 1)[1].split("\nASSISTANCE:", 1)[0] if "\nUSER:\n" in log else ""
    return tuple(EXAMPLES.findall(user))


def exp03_log(qid: str, answer: dict | None) -> str | None:
    text = json.dumps(answer, ensure_ascii=False) if answer else None
    fallback = None
    for name in EXP03_RUNS:
        for folder in glob.glob(str(ROOT / f"experiments/EXP-20261107-03-gates-public1000/run/{name}/*")):
            path = Path(folder) / f"{qid}.log"
            if not path.exists():
                continue
            log = path.read_text(encoding="utf-8")
            if text is not None and text in log:
                return log
            fallback = fallback or log
    return fallback


def main() -> int:
    route = json.loads((EXP_DIR / "out/route_public1000.json").read_text(encoding="utf-8"))
    answers03 = {row["id"]: row for row in map(json.loads, (ROOT / "experiments/EXP-20261107-03-gates-public1000/out/answers_public_final.jsonl").read_text(encoding="utf-8").splitlines()) if row}
    run = Path(sorted(glob.glob(str(EXP_DIR / "run/public1000/*")))[-1])
    changed = {row["id"]: row for row in map(json.loads, (EXP_DIR / "out/changed_vs_exp03_public1000.jsonl").read_text(encoding="utf-8").splitlines())}
    kind = {}
    for qid, way in route.items():
        if way != "TF-IDF chắc":
            continue
        old = shown(exp03_log(qid, answers03.get(qid)) or "")
        new = shown((run / f"{qid}.log").read_text(encoding="utf-8"))
        kind[qid] = "ví dụ y hệt" if old == new else "top-1 giữ, ví dụ sau đổi" if old[:1] == new[:1] else "top-1 đổi (thư viện)"
    for name in ("ví dụ y hệt", "top-1 giữ, ví dụ sau đổi", "top-1 đổi (thư viện)"):
        ids = [qid for qid, value in kind.items() if value == name]
        pairs = Counter((changed[qid]["exp03"], changed[qid]["exp04"]) for qid in ids if qid in changed)
        gain = sum(n for (a, b), n in pairs.items() if b == "ok")
        loss = sum(n for (a, b), n in pairs.items() if a == "ok")
        delta = sum(n * ((b == "ok") - (b == "wrong") - (a == "ok") + (a == "wrong")) for (a, b), n in pairs.items())
        print(f"{name:26} {len(ids):4} câu  được {gain:3}  mất {loss:3}  ΔPA {delta / 1000:+.3f}  {dict(pairs)}")
    (EXP_DIR / "out/cause_tfidf_sure.json").write_text(json.dumps(kind, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
