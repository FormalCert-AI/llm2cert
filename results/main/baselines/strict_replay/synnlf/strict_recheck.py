"""Replay saved synnlf certificates under the Strict acceptance policy."""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

STAGE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(STAGE))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common.env import apply_mosek, find_dataset, prepare_method_sys_path

NATIVE_EPS = 0.0005
NATIVE_DEG = [2, 2, 0]
NATIVE_BETA = 10**6


def recheck_case(case, stage_root: Path, **kwargs) -> dict:
    started = time.monotonic()
    payload = json.loads(case.artifact_path.read_text())
    expression = payload.get("expression")
    if not expression:
        return {"passed": False, "failure_reason": "no_expression",
                "artifact": str(case.artifact_path), "wall_seconds": time.monotonic() - started}
    try:
        prepare_method_sys_path("synnlf", stage_root)
        license_path = apply_mosek(stage_root)
        import sympy as sp
        from common import eval_tree, ode, simple_neighborhood, symbolic
        from benchmarks.Exampler_V import Example, Zone
        from verify.SosVerify_V import SosValidator_V

        record = next(
            r for r in json.loads(find_dataset(stage_root).read_text())["records"]
            if r["record_id"] == case.case_id
        )
        names, xs, rhs = symbolic(record["problem"])
        domain = simple_neighborhood(record["problem"])
        if domain["shape"] == "box":
            z = Zone("box", low=[b[0] for b in domain["bounds"]], up=[b[1] for b in domain["bounds"]])
        else:
            z = Zone("ball", center=domain["center"], r=domain["radius_squared"])
        _, _, trees = ode(record["problem"])
        functions = [(lambda x, t=t: eval_tree(t, dict(zip(names, x)))) for t in trees]
        ex = Example(n=len(xs), D_zones=z, f=functions, name=record["record_id"])
        V = sp.sympify(expression)
        probe = SosValidator_V(ex, sum(xi ** 2 for xi in sp.symbols([f"x{i+1}" for i in range(len(xs))])), NATIVE_BETA)
        probe.eps = NATIVE_EPS
        if not bool(probe.verify_positive(probe.V, [], 2)):
            return {
                "passed": False,
                "failure_reason": "blocked_missing_mosek" if not license_path else "sos_backend_unavailable",
                "mosek_license": str(license_path) if license_path else None,
                "artifact": str(case.artifact_path),
                "wall_seconds": time.monotonic() - started,
            }
        control = SosValidator_V(ex, V, NATIVE_BETA)
        control.eps = NATIVE_EPS
        native_like = bool(control.SolveAll(deg=NATIVE_DEG))
        strict = SosValidator_V(ex, V, NATIVE_BETA)
        strict.eps = 0.0
        ok = bool(strict.SolveAll(deg=NATIVE_DEG))
        return {
            "passed": ok,
            "failure_reason": None if ok else ("sos_infeasible_eps0" if native_like else "sos_infeasible_even_native_eps"),
            "native_tau": NATIVE_EPS,
            "strict_tau": 0.0,
            "native_eps_control_passed": native_like,
            "beta": NATIVE_BETA,
            "deg": NATIVE_DEG,
            "mosek_license": str(license_path) if license_path else None,
            "zone": {"shape": domain["shape"]},
            "expression": str(V),
            "artifact": str(case.artifact_path),
            "wall_seconds": time.monotonic() - started,
        }
    except Exception as exc:
        return {
            "passed": False,
            "failure_reason": "infrastructure_error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "artifact": str(case.artifact_path),
            "wall_seconds": time.monotonic() - started,
        }


def main():
    import argparse
    from _common.inventory import load_accepted_cases
    from _common.io import write_case_result

    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-root", type=Path, default=STAGE)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    for case in load_accepted_cases("synnlf", stage_root=args.stage_root):
        result = recheck_case(case, args.stage_root)
        write_case_result(args.out, "synnlf", case.case_id, result)
        print(json.dumps({"case": case.case_id, "passed": result.get("passed"),
                          "reason": result.get("failure_reason")}))


if __name__ == "__main__":
    raise SystemExit(main())
