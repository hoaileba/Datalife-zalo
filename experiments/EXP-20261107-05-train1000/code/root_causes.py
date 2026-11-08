from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXP_DIR = ROOT / "experiments/EXP-20261107-05-train1000"
OUT_HTML = Path("/private/tmp/claude-501/-Users-lebahoai-Workspace-zalo-2026/28067a31-c11c-485a-bb9c-3c1eecd09c2a/scratchpad/error-catalog.html")

GROUPS = {
    "A": ("Câu không trả lời được, agent trả lời bằng số đo thay thế", "q_008fdebb6ec9 q_15711c61bb0d q_1d7f8fb3a5df q_20221903b95b q_29efb04a938b q_35b891c4eebe q_36182821dc30 q_576830198619 q_6ed01172bd03 q_76bdadbeb802 q_95aa9007198f q_a897b21c864d q_b5e65648c9dc q_c4fc35ebf2ee q_d0fb06a1ebb2 q_e2e4e0639619 q_05a8b30443a1 q_3ad4ff264376 q_6a623646996a q_88f914de4454 q_9f82b2f25fd6"),
    "B": ("Sai số đo: tiền, số lượng, số đơn, trung bình", "q_12712b3cc328 q_2bd15109007c q_c28a03d7a959 q_95a45f58351b q_dcb25c39e1cc q_cb02efab0f93 q_d08785ea5577 q_0c0a1a780164 q_de45f4311dbe q_715e9ea420ef q_3a9665052018 q_9d8949165b5e"),
    "F": ("Sai tham số, bộ lọc, mẫu số, thứ tự", "q_63cf15f33b1c q_4e280a1755de q_56ffb6b638d7 q_15dd37187b0d q_f5fae09ccd1e q_f9a0fa4ed236 q_dcd34fbf05f0 q_fe36c469e9f8 q_32b653051a42 q_a8441d838909 q_237a88f0c7e3"),
    "G": ("Helper hoặc chuẩn hoá dữ liệu thiếu, sai", "q_4497ce0830d8 q_dae1955698d3 q_3ac94b30991c q_4b82c6814a0d q_20e776dd4755 q_302e0a7d6e89 q_3fc34d6baada q_4ac933ecda53 q_4deb7fd6f277"),
    "H": ("Code lỗi hoặc bịa tham số, agent bỏ trống", "q_36edc7d2e347 q_3da612131082 q_501cc0b20b1b q_a6cf2d550014 q_ad512cd0cb75 q_f971c5fb2353 q_8217870b6fa8"),
    "C": ("Đếm đơn theo ngưỡng dùng order_total thay cho revenue", "q_0e72ff8aa98e q_8ee6eb9187d0 q_9ff971a2b435 q_effb17cba303 q_fc8cdf9ab156 q_ffc8757f6b7d"),
    "D": ("Sai dạng đáp án", "q_0537f6e4f5ab q_b1ee04ab9d3f q_bdbe8ca608ce q_69dbf1d3cdc5 q_8103cddd9040 q_2033f8c99c05"),
    "E": ("Sai kỳ dù gợi ý đã nhận ra đúng kỳ", "q_682e548226be q_dbb084b9361d q_cfa36137a14a q_ef01edd61255 q_b621b30b4b22 q_281d6d8a83c6"),
    "X": ("Nghi đáp án tham chiếu sai", "q_6e929cf36203"),
}


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    items = {row["id"]: row | {"set": "public"} for row in rows(EXP_DIR / "out/errors_public_v10.jsonl")}
    items |= {row["id"]: row | {"set": "train"} for row in rows(EXP_DIR / "out/errors_train1000.jsonl")}
    group_of = {qid: key for key, (_, ids) in GROUPS.items() for qid in ids.split()}
    missing = sorted(set(items) - set(group_of))
    extra = sorted(set(group_of) - set(items))
    if missing or extra:
        raise ValueError(f"unassigned: {missing}, unknown: {extra}")
    out = [items[qid] | {"root_cause": group_of[qid]} for qid in items]
    (EXP_DIR / "out/errors_root_cause.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in out), encoding="utf-8")
    count = Counter((row["root_cause"], row["set"], row["verdict"]) for row in out)
    for key, (name, _) in GROUPS.items():
        print(f"{key} {name:58} public sai {count[key, 'public', 'wrong']:2} trống {count[key, 'public', 'blank']:2} | train sai {count[key, 'train', 'wrong']:2} trống {count[key, 'train', 'blank']:2}")
    blocks = {}
    for key in GROUPS:
        lines = []
        for row in sorted((row for row in out if row["root_cause"] == key), key=lambda row: (row["set"], row["id"])):
            gold, got = row["gold"], row["got"] or {}
            gold_text = json.dumps(gold.get("answer"), ensure_ascii=False) if gold["type"] != "unanswerable" else f"unanswerable: {gold.get('reason') or ''}"
            lines.append(f"<tr><td><code>{row['id']}</code><br><span class=\"tag {row['set']}\">{row['set']}</span> <span class=\"tag\">{row['shop']}</span> <span class=\"tag {row['verdict']}\">{'sai' if row['verdict'] == 'wrong' else 'trống'}</span></td><td>{html.escape(row['question'])}</td><td><span class=\"k\">{gold['type']}</span> {html.escape(gold_text)}</td><td><span class=\"k\">{got.get('type')}</span> {html.escape(json.dumps(got.get('answer'), ensure_ascii=False))}</td><td><code>{html.escape(row['final_code'] or '-')}</code></td></tr>")
        blocks[key] = "\n".join(lines)
    template = OUT_HTML.with_name("error-catalog.template.html").read_text(encoding="utf-8")
    for key, block in blocks.items():
        template = template.replace(f"{{{{rows_{key}}}}}", block)
    OUT_HTML.write_text(template, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
