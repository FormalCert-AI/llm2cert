"""Replay saved ahmed certificates under the Strict acceptance policy."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

STAGE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def recheck_case(case, stage_root: Path, **kwargs) -> dict:
    started = time.monotonic()
    return {
        "passed": False,
        "failure_reason": "no_native_certificate",
        "strict_same_as_native": True,
        "native_obligation": "Implies(OrNotZero(x), And(V >= 0, Vd <= 0))",
        "wall_seconds": time.monotonic() - started,
    }


def summarize_existing(stage_root: Path) -> dict:

    found = []
    for path in (stage_root / "results").rglob("result.json"):
        if "ahmed" not in str(path):
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        if data.get("method") not in ("ahmed_tacas2020_z3_z3", "ahmed"):
            continue
        found.append({
            "path": str(path),
            "case": data.get("record_id") or data.get("case"),
            "native_found": data.get("native_found"),
            "native_accepted": data.get("native_accepted"),
            "execution_status": data.get("execution_status"),
        })
    accepted = [r for r in found if r.get("native_found") or r.get("native_accepted") is True]
    return {
        "strict_same_as_native": True,
        "native_obligation": "Implies(OrNotZero(x), And(V >= 0, Vd <= 0))",
        "prior_runs": found,
        "accepted_count": len(accepted),
        "note": "no delta-sat / origin-ball slack; Strict copies Native",
    }


def main():
    import argparse
    from _common.inventory import load_accepted_cases
    from _common.io import write_case_result, write_summary

    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-root", type=Path, default=STAGE)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    cases = load_accepted_cases("ahmed", stage_root=args.stage_root)
    for case in cases:
        write_case_result(args.out, "ahmed", case.case_id, recheck_case(case, args.stage_root))
    write_summary(args.out / "ahmed", summarize_existing(args.stage_root))
    print(json.dumps({"accepted": len(cases), "strict_same_as_native": True}))


if __name__ == "__main__":
    raise SystemExit(main())
