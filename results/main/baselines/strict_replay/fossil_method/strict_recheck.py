"""Replay saved fossil method certificates under the Strict acceptance policy."""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import sympy as sp

STAGE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common.env import find_dataset, prepare_method_sys_path
from _common.schema import failure_reason_from_queries, strict_pass_from_queries


def _status(verifier, raw, timed_out):
    if timed_out:
        return "timeout"
    if verifier.is_unsat(raw):
        return "unsat"
    if verifier.is_sat(raw):
        return "delta-sat"
    return "unknown"


def _parse_symbolic(text: str, names):
    local = {name: sp.symbols(name, real=True) for name in names}
    local["pow"] = sp.Pow
    return sp.sympify(text, locals=local)


def _disable_origin_ball(config) -> bool:
    changed = False
    for attr in ("INNER_RADIUS", "inner"):
        if hasattr(config, attr):
            try:
                setattr(config, attr, 0)
                changed = True
            except Exception:
                pass
    domains = getattr(config, "DOMAINS", None) or {}
    for domain in domains.values():
        for attr in ("inner_radius", "INNER_RADIUS", "inner"):
            if hasattr(domain, attr):
                try:
                    setattr(domain, attr, 0)
                    changed = True
                except Exception:
                    pass
    return changed


def recheck_case(case, stage_root: Path, **kwargs) -> dict:
    started = time.monotonic()
    payload = json.loads(case.artifact_path.read_text())
    expression = (
        payload.get("symbolic_candidate")
        or payload.get("expression")
        or (payload.get("candidate") if isinstance(payload.get("candidate"), str) else None)
    )
    if not expression:
        return {
            "passed": False,
            "failure_reason": "no_symbolic_candidate",
            "artifact": str(case.artifact_path),
            "wall_seconds": time.monotonic() - started,
        }
    try:
        prepare_method_sys_path("fossil", stage_root)
        try:
            import dreal
        except Exception as exc:
            return {
                "passed": False,
                "failure_reason": "blocked_missing_dreal",
                "error": str(exc),
                "artifact": str(case.artifact_path),
                "wall_seconds": time.monotonic() - started,
            }
        from fossil.cegis import Cegis
        from fossil.sympy_converter import sympy_converter
        from fossil_v4_adapter import build_config_generic

        dataset = find_dataset(stage_root)
        config, _meta = build_config_generic(
            dataset, case.case_id, "square10", 167, 1, None
        )
        ball_disabled = _disable_origin_ball(config)
        cegis = Cegis(config)
        names = [str(v) for v in cegis.x]
        B_sym = _parse_symbolic(str(expression), names)
        f_exprs = cegis.xdot
        if callable(cegis.f):
            f_exprs = cegis.f(cegis.x)
        syms = {str(v): v for v in cegis.x}
        B = sympy_converter(syms, B_sym, to_number=lambda x: float(x))
        Bdot = 0
        for var, f_i in zip(cegis.x, f_exprs):
            dB = sp.diff(B_sym, sp.symbols(str(var), real=True))
            dB_dr = sympy_converter(syms, dB, to_number=lambda x: float(x))
            Bdot = dB_dr * f_i + Bdot
        queries = []
        for group_index, group in enumerate(
            cegis.certificate.get_constraints(cegis.verifier, B, Bdot)
        ):
            for label, formula in group.items():
                t0 = time.perf_counter()
                raw, timed_out = cegis.verifier.solve_with_timeout(
                    cegis.verifier.new_solver(), formula
                )
                queries.append({
                    "group": group_index,
                    "label": str(label),
                    "status": _status(cegis.verifier, raw, timed_out),
                    "fossil_timeout_flag": bool(timed_out),
                    "wall_seconds": time.perf_counter() - t0,
                    "formula": str(formula),
                })
        passed = strict_pass_from_queries(queries)
        return {
            "passed": passed,
            "failure_reason": None if passed else failure_reason_from_queries(queries),
            "strict_native_recheck": {
                "mode": "strict_native",
                "origin_ball": "disabled" if ball_disabled else "not_present_on_config",
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
    ap.add_argument("--case", default=None)
    args = ap.parse_args()
    cases = load_accepted_cases("fossil", stage_root=args.stage_root)
    if args.case:
        cases = [c for c in cases if c.case_id == args.case]
    for case in cases:
        result = recheck_case(case, args.stage_root)
        write_case_result(args.out, "fossil", case.case_id, result)
        print(json.dumps({"case": case.case_id, "passed": result.get("passed"),
                          "reason": result.get("failure_reason")}, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
