from __future__ import annotations

import json
import sys
from pathlib import Path

from datamate_agent.agent import NORM_ROOT, user_hints

dataset, questions, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
rows = [json.loads(line) for line in questions.read_text(encoding="utf-8").splitlines() if line.strip()]
hints = {row["id"]: user_hints(row, norm_dir=NORM_ROOT / dataset.name / row["business_id"], calendar=dataset / "calendar.csv") for row in rows}
out.write_text(json.dumps(hints, ensure_ascii=False), encoding="utf-8")
