"""Replay saved analytical rl certificates under the Strict acceptance policy."""
from __future__ import annotations

import json
import math
import sys
import time
import traceback
from pathlib import Path

STAGE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(STAGE))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common.env import find_dataset, prepare_method_sys_path
from _common.schema import failure_reason_from_queries, strict_pass_from_queries

PAPER_EPS = math.exp(-3)
PAPER_DELTA = math.exp(-12)
SOLVER_PRECISION = 1e-5


def _parse_expression(raw) -> str:
    text = str(raw).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text


def _domain_formula(dreal, xs, domain):
    if domain["shape"] == "box":
        parts = []
        for var, (lo, hi) in zip(xs, domain["bounds"]):
            parts.append(var >= float(lo))
            parts.append(var <= float(hi))
        return dreal.And(*parts)
    center = domain["center"]
    r2 = float(domain["radius_squared"])
    quad = sum((var - float(c)) ** 2 for var, c in zip(xs, center))
    return quad <= r2


def _not_origin(dreal, xs, epsilon: float):
    if epsilon and epsilon > 0:
        return sum(var ** 2 for var in xs) >= epsilon ** 2
    zeros = [var == 0 for var in xs]
    return dreal.Not(dreal.And(*zeros)) if len(zeros) > 1 else dreal.Not(zeros[0])


def _check(dreal, formula, precision):
    raw = dreal.CheckSatisfiability(formula, precision)
    if raw is None:
        return "unsat", raw
    return "delta-sat", raw


def recheck_case(case, stage_root: Path, **kwargs) -> dict:
    started = time.monotonic()
    payload = json.loads(case.artifact_path.read_text())
    expression = payload.get("expression") or (payload.get("native_result") or {}).get("expression")
    if not expression:
        return {
            "passed": False,
            "failure_reason": "no_expression",
            "artifact": str(case.artifact_path),
            "wall_seconds": time.monotonic() - started,
        }
    try:
        prepare_method_sys_path("analytical_rl", stage_root)
        try:
            import dreal
        except Exception as exc:
            return {
                "passed": False,
                "failure_reason": "blocked_missing_dreal",
                "error": str(exc),
                "note": "author GitHub has no dReal script; sidecar needs dreal python binding",
                "artifact": str(case.artifact_path),
                "wall_seconds": time.monotonic() - started,
            }
        import sympy as sp
        from common import simple_neighborhood, symbolic
        from fossil.consts import DREAL_FNCS
        from fossil.sympy_converter import sympy_converter

        record = next(
            r for r in json.loads(find_dataset(stage_root).read_text())["records"]
            if r["record_id"] == case.case_id
        )
        names, xs_sp, rhs = symbolic(record["problem"])

        runtime_xs = list(sp.symbols([f"x{i+1}" for i in range(len(xs_sp))]))
        rhs = [expr.xreplace(dict(zip(xs_sp, runtime_xs))) for expr in rhs]
        domain = simple_neighborhood(record["problem"])
        V_sp = sp.sympify(
            _parse_expression(expression),
            locals={str(s): s for s in runtime_xs},
        )
        lie_sp = sum(sp.diff(V_sp, xi) * fi for xi, fi in zip(runtime_xs, rhs))
        xs = [dreal.Variable(str(s)) for s in runtime_xs]
        syms = {**DREAL_FNCS, **{str(s): v for s, v in zip(runtime_xs, xs)}}
        V = sympy_converter(syms, V_sp, to_number=lambda x: float(x))
        lie = sympy_converter(syms, lie_sp, to_number=lambda x: float(x))
        inside = _domain_formula(dreal, xs, domain)
        queries = []
        for mode, eps, delta in (
            ("native_paper", PAPER_EPS, PAPER_DELTA),
            ("strict", 0.0, 0.0),
        ):
            away = _not_origin(dreal, xs, eps)
            for label, bad in (
                ("V_not_positive", V <= delta),
                ("lie_not_negative", lie >= -delta),
            ):
                t0 = time.perf_counter()
                status, raw = _check(dreal, dreal.And(inside, away, bad), SOLVER_PRECISION)
                queries.append({
                    "mode": mode,
                    "label": label,
                    "status": status,
                    "epsilon": eps,
                    "delta": delta,
                    "wall_seconds": time.perf_counter() - t0,
                    "raw": None if raw is None else str(raw),
                })
        strict_queries = [q for q in queries if q["mode"] == "strict"]
        passed = strict_pass_from_queries(strict_queries)
        return {
            "passed": passed,
            "failure_reason": None if passed else failure_reason_from_queries(strict_queries),
            "expression": _parse_expression(expression),
            "native_note": "stage1 Native is SHGO; this sidecar adds paper dReal (GitHub has no script)",
            "strict_native_recheck": {
                "origin_ball": "disabled_point_exclusion",
                "delta_margin": 0.0,
                "solver_precision": SOLVER_PRECISION,
                "delta_sat_counts_as_fail": True,
                "queries": queries,
                "all_queries_unsat": passed,
            },
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
    for case in load_accepted_cases("analytical_rl", stage_root=args.stage_root):
        result = recheck_case(case, args.stage_root)
        write_case_result(args.out, "analytical_rl", case.case_id, result)
        print(json.dumps({"case": case.case_id, "passed": result.get("passed"),
                          "reason": result.get("failure_reason")}))


if __name__ == "__main__":
    raise SystemExit(main())
