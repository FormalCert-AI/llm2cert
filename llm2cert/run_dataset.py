"""Run the dataset with bounded parallelism."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
FRAMEWORK = ROOT / "framework"
sys.path.insert(0, str(FRAMEWORK))

from config import API_KEY, MODEL
from lean_barrier.s03_case_io import import_case
from lean_barrier.s04_semantics import validate_problem
from lean_barrier.s10_lean_runner import LEAN_REPAIR_FEEDBACK_MODES


_DATASET_DIR = REPOSITORY / "data"
_DATASET = _DATASET_DIR / "dynacertbench_executable.json"


DEFAULT_DATASET = Path(
    os.environ.get("DYNACERT_DATASET", str(_DATASET))
)
MAX_OUTER_WORKERS = 128
PIPELINE_TIMEOUT_SECONDS = 2400.0
LAUNCHER_TIMEOUT_SECONDS = 2640.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)


def _default_experiment_id(
    *,
    smt_only: bool = False,
    lean_only: bool = False,
    lean_repair_feedback: str = "processed",
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if smt_only:
        mode = "onlysmt"
    elif lean_only:
        mode = "onlylean"
    elif lean_repair_feedback != "processed":
        mode = lean_repair_feedback.replace("_", "")
    else:
        mode = "baseline"
    return _safe_id(f"dynacertbench-full-{MODEL}-{mode}-{timestamp}")


def _parse_record_ids(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    record_ids = [item.strip() for item in raw.split(",") if item.strip()]
    if not record_ids:
        raise SystemExit("--record-ids requires at least one id")
    duplicates = [item for item in record_ids if record_ids.count(item) > 1]
    if duplicates:
        raise SystemExit(f"--record-ids contains duplicates: {sorted(set(duplicates))}")
    return record_ids


def _select_records(
    records: list[dict[str, Any]], record_ids: list[str] | None
) -> list[dict[str, Any]]:
    if record_ids is None:
        return records
    by_id = {record["record_id"]: record for record in records}
    missing = [record_id for record_id in record_ids if record_id not in by_id]
    if missing:
        raise SystemExit("unknown --record-ids: " + ", ".join(missing))
    return [by_id[record_id] for record_id in record_ids]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _problem_class(task_type: str) -> str:
    return {
        "stability": "P1_stability",
        "roa": "P2_roa",
        "invariant": "P3_invariant",
        "safety": "P4_safety",
    }[task_type]


def _load_records(dataset: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(dataset.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "dynacertbench.executable":
        raise ValueError("this release accepts only dynacertbench.executable")
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != payload.get("record_count"):
        raise ValueError("dataset record_count does not match records")
    record_ids = [record.get("record_id") for record in records]
    if any(not isinstance(record_id, str) or not record_id for record_id in record_ids):
        raise ValueError("every executable record requires a non-empty record_id")
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("executable record_id values must be unique")

    for index, record in enumerate(records):
        if record.get("candidate") is not None:
            raise ValueError(f"{record['record_id']} contains a pre-supplied candidate")
        imported = import_case(record, bench_id=index)
        validate_problem(imported.problem)
    return payload, records


def _load_exclusions(report_path: Path, expected_count: int) -> list[dict[str, Any]]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    exclusions = payload.get("excluded_records")
    if not isinstance(exclusions, list) or len(exclusions) != expected_count:
        raise ValueError(
            "companion exclusion report does not match the executable dataset"
        )
    return exclusions


def _latest_index_row(experiment_root: Path, record_id: str) -> dict[str, Any] | None:
    path = experiment_root / "index.jsonl"
    if not path.exists():
        return None
    matches: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("record_id") == record_id:
            matches.append(row)
    return matches[-1] if matches else None


class BatchCheckpoint:
    def __init__(self, path: Path, initial: dict[str, Any]) -> None:
        self.path = path
        self.value = initial
        self.lock = threading.Lock()
        _atomic_json(self.path, self.value)

    def update(self, record_id: str, **updates: Any) -> None:
        with self.lock:
            self.value["records"][record_id].update(updates)
            self.value["updated_at_utc"] = _utc_now()
            states = [item["state"] for item in self.value["records"].values()]
            self.value["counts"] = {
                state: states.count(state)
                for state in (
                    "pending",
                    "running",
                    "finished",
                    "process_failed",
                    "launcher_timeout",
                )
            }
            _atomic_json(self.path, self.value)


def _stop_process_group(process: subprocess.Popen[Any]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _run_record(
    *,
    dataset: Path,
    record: dict[str, Any],
    experiment_id: str,
    experiment_root: Path,
    batch_dir: Path,
    checkpoint: BatchCheckpoint,
    launcher_timeout: float,
    smt_only: bool = False,
    lean_only: bool = False,
    lean_repair_feedback: str = "processed",
    output_root: Path | None = None,
) -> dict[str, Any]:
    record_id = record["record_id"]
    started = time.monotonic()
    log_path = batch_dir / "logs" / f"{record_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.update(
        record_id,
        state="running",
        started_at_utc=_utc_now(),
        finished_at_utc=None,
        log_path=str(log_path),
    )

    command = [
        sys.executable,
        str(ROOT / "run_pipeline.py"),
        str(dataset),
        record_id,
        "--experiment-id",
        experiment_id,
    ]
    if smt_only:
        command.append("--smt-only")
    if lean_only:
        command.append("--lean-only")
    if lean_repair_feedback != "processed":
        command.extend(["--lean-repair-feedback", lean_repair_feedback])
    if output_root is not None:
        command.extend(["--output-root", str(output_root)])
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(FRAMEWORK)
        if not existing_pythonpath
        else os.pathsep.join((str(FRAMEWORK), existing_pythonpath))
    )

    return_code: int | None = None
    state = "process_failed"
    error: str | None = None
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"launcher_started_at_utc={_utc_now()}\n")
        log.write(f"record_id={record_id}\n")
        log.flush()
        try:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            try:
                return_code = process.wait(timeout=launcher_timeout)
            except subprocess.TimeoutExpired:
                _stop_process_group(process)
                return_code = process.returncode
                state = "launcher_timeout"
                error = f"launcher exceeded {launcher_timeout:.0f} seconds"
            else:
                state = "finished" if return_code == 0 else "process_failed"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        log.write(f"launcher_finished_at_utc={_utc_now()}\n")
        log.write(f"launcher_return_code={return_code}\n")
        if error:
            log.write(f"launcher_error={error}\n")

    index_row = _latest_index_row(experiment_root, record_id)
    if index_row is not None:


        state = "finished"
    update = {
        "state": state,
        "finished_at_utc": _utc_now(),
        "duration_seconds": time.monotonic() - started,
        "return_code": return_code,
        "pipeline_status": index_row.get("status") if index_row else None,
        "run_path": index_row.get("run_path") if index_row else None,
        "error": error,
    }
    checkpoint.update(record_id, **update)
    return {"record_id": record_id, **update}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "companion exclusion report; by default infer "
            "<dataset-stem>_report.json next to the selected dataset"
        ),
    )
    parser.add_argument("--workers", type=int, default=MAX_OUTER_WORKERS)
    parser.add_argument("--experiment-id", default=None)
    parser.add_argument(
        "--launcher-timeout-seconds", type=float, default=LAUNCHER_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate all records and print the execution plan without calling an agent",
    )
    parser.add_argument(
        "--smt-only",
        action="store_true",
        help="disable Lean: force SMT when eligible, stop when SMT cannot close",
    )
    parser.add_argument(
        "--lean-only",
        action="store_true",
        help="disable SMT: send every formal condition to Lean",
    )
    parser.add_argument(
        "--lean-repair-feedback",
        choices=LEAN_REPAIR_FEEDBACK_MODES,
        default="processed",
        help="Lean repair diagnostics: processed (default), verbatim, or failure_only",
    )
    parser.add_argument(
        "--record-ids",
        default=None,
        help="comma-separated executable record_id subset; default is the full set",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="write this batch under DIR instead of benchmark/experiments/<experiment-id>",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    dataset = args.dataset.resolve()
    if not dataset.is_file():
        raise SystemExit(
            "canonical executable dataset is missing: "
            f"{dataset}. Build or deploy dynacertbench_executable.json "
            "before starting a paper run."
        )
    report_path = (
        args.report.resolve()
        if args.report is not None
        else dataset.with_name(f"{dataset.stem}_report.json")
    )
    if not 1 <= args.workers <= MAX_OUTER_WORKERS:
        raise SystemExit(
            f"--workers must be between 1 and {MAX_OUTER_WORKERS}; "
            "each problem already has nested condition/solver parallelism"
        )
    if args.launcher_timeout_seconds <= PIPELINE_TIMEOUT_SECONDS:
        raise SystemExit(
            "--launcher-timeout-seconds must exceed the pipeline's "
            f"{PIPELINE_TIMEOUT_SECONDS:g}-second deadline"
        )
    if args.smt_only and args.lean_only:
        raise SystemExit("--smt-only and --lean-only cannot be combined")

    payload, records = _load_records(dataset)
    records = _select_records(records, _parse_record_ids(args.record_ids))
    exclusions = _load_exclusions(report_path, int(payload.get("excluded_count", 0)))
    experiment_id = _safe_id(
        args.experiment_id
        or _default_experiment_id(
            smt_only=bool(args.smt_only),
            lean_only=bool(args.lean_only),
            lean_repair_feedback=str(args.lean_repair_feedback),
        )
    )
    if not experiment_id:
        raise SystemExit("--experiment-id must contain at least one safe character")

    experiment_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else REPOSITORY / "benchmark" / "experiments" / experiment_id
    )
    plan = {
        "experiment_id": experiment_id,
        "output_root": str(experiment_root),
        "executable_records": len(records),
        "record_ids": [record["record_id"] for record in records],
        "excluded_records": len(exclusions),
        "outer_workers": args.workers,
        "pipeline_timeout_seconds": PIPELINE_TIMEOUT_SECONDS,
        "launcher_timeout_seconds": args.launcher_timeout_seconds,
        "smt_only": bool(args.smt_only),
        "lean_only": bool(args.lean_only),
        "lean_repair_feedback": str(args.lean_repair_feedback),
    }
    if args.validate_only:
        print(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    if not API_KEY or API_KEY.startswith("<REDACTED>"):
        raise SystemExit("set DYNACERT_API_KEY (see .env.example) to run model-backed cases")

    batch_dir = experiment_root / "batch"
    manifest_path = batch_dir / "batch_manifest.json"
    if manifest_path.exists():
        raise SystemExit(
            f"batch already exists at {batch_dir}; use a new --experiment-id"
        )

    manifest = {
        "schema_version": "dynacert-batch.v2",
        **plan,
        "created_at_utc": _utc_now(),
        "dataset_path": str(dataset),
        "dataset_sha256": _sha256(dataset),
        "report_path": str(report_path),
        "report_sha256": _sha256(report_path),
        "model": MODEL,
        "strategy": {
            "policy": "baseline",
            "smt_only": bool(args.smt_only),
            "lean_only": bool(args.lean_only),
            "lean_repair_feedback": str(args.lean_repair_feedback),
        },
        "records": [
            {
                "record_id": record["record_id"],
                "problem_id": record["problem"]["problem_id"],
                "problem_class": _problem_class(record["problem"]["task_type"]),
            }
            for record in records
        ],
        "excluded": exclusions,
    }
    _atomic_json(manifest_path, manifest)
    initial_status = {
        "schema_version": "dynacert-batch-status.v2",
        "experiment_id": experiment_id,
        "started_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "finished_at_utc": None,
        "counts": {
            "pending": len(records),
            "running": 0,
            "finished": 0,
            "process_failed": 0,
            "launcher_timeout": 0,
        },
        "records": {
            record["record_id"]: {
                "problem_class": _problem_class(record["problem"]["task_type"]),
                "state": "pending",
                "pipeline_status": None,
            }
            for record in records
        },
    }
    checkpoint = BatchCheckpoint(batch_dir / "batch_status.json", initial_status)

    print(json.dumps(plan, ensure_ascii=False, sort_keys=True), flush=True)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _run_record,
                dataset=dataset,
                record=record,
                experiment_id=experiment_id,
                experiment_root=experiment_root,
                batch_dir=batch_dir,
                checkpoint=checkpoint,
                launcher_timeout=args.launcher_timeout_seconds,
                smt_only=bool(args.smt_only),
                lean_only=bool(args.lean_only),
                lean_repair_feedback=str(args.lean_repair_feedback),
                output_root=experiment_root,
            ): record["record_id"]
            for record in records
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(
                f"[{len(results)}/{len(records)}] {result['record_id']}: "
                f"{result['state']} / {result['pipeline_status']}",
                flush=True,
            )

    with checkpoint.lock:
        checkpoint.value["finished_at_utc"] = _utc_now()
        checkpoint.value["updated_at_utc"] = _utc_now()
        _atomic_json(checkpoint.path, checkpoint.value)
    pipeline_statuses: dict[str, int] = {}
    for item in checkpoint.value["records"].values():
        status = str(item.get("pipeline_status") or "no_final_result")
        pipeline_statuses[status] = pipeline_statuses.get(status, 0) + 1
    _atomic_json(
        batch_dir / "batch_summary.json",
        {
            "schema_version": "dynacert-batch-summary.v2",
            "experiment_id": experiment_id,
            "finished_at_utc": _utc_now(),
            "counts": checkpoint.value["counts"],
            "pipeline_statuses": pipeline_statuses,
            "excluded": exclusions,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
