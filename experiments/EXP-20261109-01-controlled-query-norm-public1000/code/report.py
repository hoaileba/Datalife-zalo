from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

FOLDER = Path(__file__).resolve().parents[1]
ROOT = FOLDER.parents[1]


class Dataset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    rows: int
    reference: str


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    opened_at: str
    goal: str
    hypothesis: str
    metrics: tuple[str, ...]
    dataset: Dataset
    phase: str
    model: str
    seed: int
    prompt: str
    parent: str
    status: Literal["open", "closed", "failed"]


def sha(path: Path) -> str:
    state = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            state.update(block)
    return state.hexdigest()


def main() -> int:
    manifest_path = FOLDER / "manifest.json"
    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if manifest.status != "open":
        raise ValueError("experiment is not open; do not alter a closed experiment")
    metrics = json.loads((FOLDER / "out/metrics.json").read_text(encoding="utf-8"))
    if set(metrics) != set(manifest.metrics):
        raise ValueError("metrics differ from preregistration")
    questions = [json.loads(line) for line in (FOLDER / "code/inputs/questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    submitted = [json.loads(line) for line in (FOLDER / "out/submission.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(submitted) != 1000 or {row["id"] for row in submitted} != {row["id"] for row in questions}:
        raise ValueError("submission is incomplete")
    hashes = json.loads((FOLDER / "code/snapshot_hashes.json").read_text(encoding="utf-8"))
    changed = tuple(name for name, expected in hashes.items() if sha(FOLDER / name) != expected)
    if changed:
        raise ValueError("source or input snapshot changed during run")
    helper_hashes = {path.relative_to(FOLDER).as_posix(): sha(path) for path in sorted((FOLDER / "code").glob("*")) if path.is_file()}
    (FOLDER / "code/helper_hashes.json").write_text(json.dumps(helper_hashes, indent=2) + "\n", encoding="utf-8")
    verdicts = [json.loads(line) for line in (FOLDER / "out/verdicts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    old = Counter(row["baseline"] for row in verdicts)
    parent = {
        "score_lenient": (old["ok"] - old["wrong"]) / 1000,
        "accuracy_lenient": old["ok"] / (old["ok"] + old["wrong"]),
        "coverage_lenient": (old["ok"] + old["wrong"]) / 1000,
        "right_lenient": old["ok"], "wrong_lenient": old["wrong"], "blank_lenient": old["blank"],
        "score_strict": 0.915, "accuracy_strict": 951 / 987, "coverage_strict": 0.987,
        "right_strict": 951, "wrong_strict": 36, "blank_strict": 13,
        "agent_api_errors": 13, "order_count_9_right": 0, "order_count_9_wrong": 9, "order_count_9_blank": 0,
    }
    lines = [
        "# Kết quả controlled query normalization", "",
        "Một variant preprocessing: controlled edits thay câu rewrite tự do, vẫn sinh lại shape/count/needs trong cùng response. Không sửa helper/library/prompt v10 hoặc giới hạn generation của agent. Default pipeline vẫn rewrite; normalize là opt-in.", "",
        "## Số đo đã khai trước", "",
        "| Metric | Parent | Controlled normalization |", "| --- | --- | --- |",
    ]
    for name in manifest.metrics:
        value = metrics[name]
        rendered = f"{value:.6f}" if isinstance(value, float) else str(value)
        old_value = parent.get(name)
        old_text = "không so tương đương" if old_value is None else f"{old_value:.6f}" if isinstance(old_value, float) else str(old_value)
        lines.append(f"| {name} | {old_text} | {rendered} |")
    met = metrics["score_lenient"] >= parent["score_lenient"] and metrics["score_strict"] >= parent["score_strict"]
    lines.extend((
        "", "## Đọc kết quả", "",
        f"Điểm lenient {metrics['score_lenient']:+.3f}; accuracy {100 * metrics['accuracy_lenient']:.2f}%; coverage {100 * metrics['coverage_lenient']:.2f}%. Đúng/sai/trống: {metrics['right_lenient']}/{metrics['wrong_lenient']}/{metrics['blank_lenient']}.",
        f"Điểm strict {metrics['score_strict']:+.3f}; accuracy {100 * metrics['accuracy_strict']:.2f}%; coverage {100 * metrics['coverage_strict']:.2f}%.",
        f"So với cached parent: được {metrics['gained_vs_parent']} câu, mất {metrics['lost_vs_parent']} câu; chênh điểm lenient {metrics['delta_score_vs_parent']:+.3f}. Không quy toàn bộ chênh lệch cho riêng edits vì metadata được sinh lại và parent không phải control chạy đồng thời.",
        "", "## Milestone", "",
        "Đã đạt mục tiêu thực thi user yêu cầu: đủ 1000 câu mới từ snapshot, submission đủ ID, chấm strict/lenient và đối chiếu từng câu. Smoke không chấm gold và không ghép vào full run. docs/02-plan-kien-truc.md không có trong checkout, không khẳng định đạt milestone kiến trúc không đọc được.",
        "", "## Kết luận", "",
        "Chỉ tiêu quan sát không giảm cả hai điểm local: " + ("đạt trong lần chạy này." if met else "không đạt trong lần chạy này."),
        "Đây là một lần đo trên public đã dùng để phát triển, tham chiếu Claude và scorer local; chưa chứng minh tác động nhân quả tách riêng normalization hoặc độ tổng quát private/biz mới.",
        "", "## Việc còn treo", "",
        "- Phân tích out/changed_cases.jsonl và kiểm các câu mất; chưa tự promote normalize thành default.",
        "- Giữ source/input snapshot và log raw. Lần sửa prompt/guard tiếp theo phải mở thực nghiệm khác.",
        "- Có thể cần paired control cùng thời điểm và đánh giá nguồn/câu độc lập trước khi chốt triển khai.",
        "", "## Tái hiện", "",
        "code/reproduce.sh nhận cấu hình VLLM_* qua env. code/src là snapshot; code/inputs freeze questions/reference/baseline/norm. Lệnh và output ở logs/*.cmd, *.log; raw request/reply/usage/status ở logs/events.jsonl. Không có endpoint/key trong các file này.",
        "", "Không chạy reproduce.sh trực tiếp vào thư mục đã đóng; sao bộ thực nghiệm sang một run/work mới để giữ tính bất biến.",
    ))
    (FOLDER / "RESULT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat()
    with (FOLDER / "STEPS.md").open("a", encoding="utf-8") as sink:
        sink.write(f"\n## {now} — bước 7/7\nĐã làm: kiểm đủ1000 ID, hash snapshot không đổi; chấm và ghi RESULT theo26 metrics đã khai.\nKết quả: lenient {metrics['score_lenient']:+.3f}, accuracy {metrics['accuracy_lenient']:.6f}, coverage {metrics['coverage_lenient']:.6f}; hypothesis observed {'met' if met else 'not met'}.\nBước tiếp: đóng thực nghiệm; phân tích hậu kiểm ở artifact mới nếu cần.\n")
    with (ROOT / "experiments/INDEX.md").open("a", encoding="utf-8") as sink:
        sink.write(f"\n| `{manifest.id}` | P0 | Controlled normalization; 1000 public, frozen Gemma4 pipeline | {metrics['score_lenient']:+.3f} lenient / {metrics['score_strict']:+.3f} strict | {metrics['accuracy_lenient']:.6f} | {metrics['coverage_lenient']:.6f} | `closed` | `{manifest.parent}` |\n")
    print(json.dumps({"status": "closed", "score": metrics["score_lenient"], "accuracy": metrics["accuracy_lenient"], "coverage": metrics["coverage_lenient"]}), flush=True)
    manifest_path.write_text(manifest.model_copy(update={"status": "closed"}).model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
