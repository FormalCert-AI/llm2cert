#!/usr/bin/env python3
"""Run the supported baseline Strict replay adapters."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(STAGE))

from _common.env import apply_stage_env
from _common.inventory import load_accepted_cases
from _common.io import write_case_result, write_summary

METHODS = ("ahmed", "fossil", "cbf", "analytical_rl", "synnlf")
MODULE = {
    "ahmed": "ahmed.strict_recheck",
    "fossil": "fossil_method.strict_recheck",
    "cbf": "cbf_lbp.strict_recheck",
    "analytical_rl": "analytical_rl.strict_recheck",
    "synnlf": "synnlf.strict_recheck",
}


def run_method(method: str, stage_root: Path, out: Path) -> dict:
    cases = load_accepted_cases(method, stage_root=stage_root)
    mod = importlib.import_module(MODULE[method])
    results = []
    for case in cases:
        payload = mod.recheck_case(case, stage_root)
        write_case_result(out, method, case.case_id, payload)
        results.append({"case_id": case.case_id, "passed": bool(payload.get("passed")),
                        "failure_reason": payload.get("failure_reason")})
        print(json.dumps({"method": method, **results[-1]}), flush=True)
    extra = {}
    if hasattr(mod, "summarize_existing") and method == "ahmed":
        extra = mod.summarize_existing(stage_root)
        write_summary(out / "ahmed", extra)
    passed = sum(1 for r in results if r["passed"])
    denom = len(cases)
    reasons = {}
    for r in results:
        if not r["passed"]:
            reasons[r["failure_reason"] or "unknown"] = reasons.get(r["failure_reason"] or "unknown", 0) + 1
    return {
        "method": method,
        "native_accepted_denominator": denom,
        "strict_passed": passed,
        "strict": f"{passed}/{denom}" if method != "ahmed" or denom else ("--/--" if denom == 0 else f"{passed}/{denom}"),
        "failure_reasons": reasons,
        "cases": results,
        **extra,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["strict"], default="strict")
    ap.add_argument("--methods", nargs="+", default=list(METHODS))
    ap.add_argument("--stage-root", type=Path, default=Path(os.environ.get("STAGE1_ROOT", STAGE)))
    ap.add_argument("--stamp", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    args = ap.parse_args()
    env_info = apply_stage_env(args.stage_root)
    out = args.stage_root / "results" / f"strict_replay_{args.stamp}"
    out.mkdir(parents=True, exist_ok=True)
    summary = {"mode": "strict", "stamp": args.stamp, "stage_root": str(args.stage_root),
               "env": env_info, "methods": {}}
    for method in args.methods:
        if method not in MODULE:
            raise SystemExit(f"unknown method {method}")
        try:
            summary["methods"][method] = run_method(method, args.stage_root, out)
        except Exception as exc:
            summary["methods"][method] = {"error": str(exc), "error_type": type(exc).__name__}
            print(json.dumps({"method": method, "error": str(exc)}), flush=True)
    write_summary(out, summary)
    print(json.dumps({m: v.get("strict") or v.get("error") for m, v in summary["methods"].items()}), flush=True)
    return 1 if any("error" in value for value in summary["methods"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
