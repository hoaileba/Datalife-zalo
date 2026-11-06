from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

from datamate.shop import Shop

out: dict[str, str] = {}
for root, calendar in (("artifacts/norm/public_test", "public_test/calendar.csv"), ("artifacts/norm/train", "train/calendar.csv")):
    for shop_dir in sorted(Path(root).iterdir()):
        if not shop_dir.is_dir():
            continue
        try:
            lines = Shop(str(shop_dir), as_of="2030-01-01", calendar=calendar).lines
        except (ValueError, KeyError, TypeError) as error:
            out[shop_dir.name] = f"error {type(error).__name__}"
            continue
        out[shop_dir.name] = "none" if lines is None else hashlib.sha1(pd.util.hash_pandas_object(lines.astype(str), index=False).values.tobytes()).hexdigest()
Path(sys.argv[1]).write_text(json.dumps(out), encoding="utf-8")
