"""Read and write baseline replay artifacts."""
from __future__ import annotations

import json
from pathlib import Path

from .schema import SCHEMA_VERSION


def write_case_result(root: Path, method: str, case_id: str, payload: dict) -> Path:
    root = Path(root)
    path = root / method / f"{case_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema_version": SCHEMA_VERSION, "method": method, "case_id": case_id, **payload}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n")
    return path


def write_summary(root: Path, payload: dict) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "summary.json"
    body = {"schema_version": SCHEMA_VERSION, **payload}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n")
    return path
