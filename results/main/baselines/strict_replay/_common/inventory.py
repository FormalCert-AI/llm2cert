"""Collect saved baseline candidates for Strict replay."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AcceptedCase:
    method: str
    case_id: str
    artifact_path: Path
    certificate_kind: str
    extra_artifacts: tuple[Path, ...] = ()


def stage_root_from_here(here: Path | None = None) -> Path:
    here = here or Path(__file__).resolve()
    return here.parents[2]


def _load_json(path: Path):
    return json.loads(path.read_text())


def _resolve(stage: Path, rel: str) -> Path:
    raw = Path(rel)
    if raw.is_absolute():
        return raw
    parts = raw.parts
    if "results" in parts:
        idx = parts.index("results")
        return stage.joinpath(*parts[idx:])
    if stage.name in parts:
        idx = parts.index(stage.name)
        return stage.joinpath(*parts[idx + 1 :])
    if (stage / raw).exists():
        return stage / raw
    return stage / rel


def load_inventory_rows(stage: Path) -> list[dict]:
    path = stage / "accepted_certificate_inventory.json"
    return _load_json(path)


def load_accepted_cases(method: str, stage_root: Path | None = None) -> list[AcceptedCase]:
    stage = Path(stage_root) if stage_root else stage_root_from_here()
    rows = load_inventory_rows(stage)
    if method == "fossil":
        recount = _load_json(stage / "fossil_native_unified_recount.json")
        wanted = list(recount["native_accepted_cases"])
        by_case = {}
        for row in rows:
            if row["method"] not in ("fossil", "fossil_generic"):
                continue
            path = _resolve(stage, row["artifact"])
            extras = tuple(_resolve(stage, p) for p in row.get("alternative_artifacts") or [])
            by_case.setdefault(row["case"], AcceptedCase(
                method="fossil",
                case_id=row["case"],
                artifact_path=path,
                certificate_kind=row.get("certificate_kind") or "symbolic",
                extra_artifacts=extras,
            ))
        missing = []
        out = []
        for case_id in wanted:
            if case_id in by_case:
                out.append(by_case[case_id])
            else:
                missing.append(case_id)
        if missing:
            raise FileNotFoundError(f"FOSSIL accepted cases missing artifacts: {missing}")
        return out

    key = {"analytical_rl": "analytical_rl", "synnlf": "synnlf", "cbf": "cbf", "ahmed": "ahmed"}.get(method, method)
    out = []
    for row in rows:
        if row["method"] != key:
            continue
        if not row.get("used_in_paper_row", True) and method != "fossil":
            continue
        out.append(AcceptedCase(
            method=method,
            case_id=row["case"],
            artifact_path=_resolve(stage, row["artifact"]),
            certificate_kind=row.get("certificate_kind") or "unknown",
            extra_artifacts=tuple(_resolve(stage, p) for p in row.get("alternative_artifacts") or []),
        ))
    return out
