"""Configuration (config.yaml) and environment (.env) loading.

In:  path of config.yaml; optional .env next to it.  Out: a plain dict.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path = ROOT / '.env') -> None:
    """KEY=VALUE lines into os.environ without overriding; tolerant of CRLF and quotes."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path: Path = ROOT / 'config.yaml') -> dict:
    return yaml.safe_load(Path(path).read_text(encoding='utf-8'))
