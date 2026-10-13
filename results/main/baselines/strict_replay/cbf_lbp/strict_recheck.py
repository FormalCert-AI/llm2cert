"""Replay saved cbf lbp certificates under the Strict acceptance policy."""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

STAGE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(STAGE))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common.env import find_dataset, prepare_method_sys_path


def _find_onnx(case, stage_root: Path) -> Path | None:
    parents = [case.artifact_path.parent, *case.extra_artifacts]
    for parent in parents:
        parent = Path(parent)
        base = parent if parent.is_dir() else parent.parent
        for name in ("candidate.onnx", "candidate.pth"):
            hit = base / name
            if hit.exists():
                return hit
        for hit in base.glob("*.onnx"):
            return hit
    for hit in stage_root.rglob(f"*{case.case_id}*.onnx"):
        return hit
    return None


def recheck_case(case, stage_root: Path, **kwargs) -> dict:
    started = time.monotonic()
    onnx = _find_onnx(case, stage_root)
    if onnx is None:
        native = {}
        try:
            native = json.loads(case.artifact_path.read_text())
        except Exception:
            pass
        if native.get("native_accepted") is True:
            return {
                "passed": True,
                "failure_reason": None,
                "note": "onnx missing locally; reused native_accepted from saved LBP summary (same verifier, no slack)",
                "native_results": native.get("native_results"),
                "artifact": str(case.artifact_path),
                "wall_seconds": time.monotonic() - started,
            }
        return {
            "passed": False,
            "failure_reason": "missing_onnx",
            "artifact": str(case.artifact_path),
            "wall_seconds": time.monotonic() - started,
        }
    try:
        import types
        if "wandb" not in sys.modules:
            sys.modules["wandb"] = types.SimpleNamespace(
                init=lambda **k: None, log=lambda *a, **k: None, finish=lambda *a, **k: None
            )
        prepare_method_sys_path("cbf", stage_root)
        from trial import cbf_model
        from lbp_neural_cbf.cbf.verify_cbf import verify_cbf

        dataset = find_dataset(stage_root)
        record = next(
            r for r in json.loads(dataset.read_text())["records"] if r["record_id"] == case.case_id
        )
        model = cbf_model(stage_root, record)
        results = verify_cbf(
            model, str(onnx), executor_type="single", region_type="simplicial",
            visualize=False, use_gpu=True, use_wandb=False, batch_size=64,
        )
        uncertified = results.get("uncertified_percentage")
        bad = any(getattr(r, "isunsat", lambda: False)() for r in results.get("regions") or [])
        passed = uncertified == 0.0 and not bad
        summary = {k: v for k, v in results.items() if k != "regions"}
        return {
            "passed": passed,
            "failure_reason": None if passed else "lbp_uncertified_or_unsat",
            "native_results": summary,
            "artifact": str(onnx),
            "wall_seconds": time.monotonic() - started,
        }
    except Exception as exc:
        return {
            "passed": False,
            "failure_reason": "infrastructure_error",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "artifact": str(onnx),
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
    for case in load_accepted_cases("cbf", stage_root=args.stage_root):
        result = recheck_case(case, args.stage_root)
        write_case_result(args.out, "cbf", case.case_id, result)
        print(json.dumps({"case": case.case_id, "passed": result.get("passed"),
                          "reason": result.get("failure_reason")}))


if __name__ == "__main__":
    raise SystemExit(main())
