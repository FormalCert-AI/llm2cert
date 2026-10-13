#!/usr/bin/env python3
"""Summarize observed routing and replay costs from Full traces."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = (
    REPOSITORY / "results/main/data"
)
sys.path.insert(0, str(REPOSITORY / "benchmark"))
from run_fixed_certificate_all_smt import _load_and_audit_case


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = sorted({key for row in rows for key in row})
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _verified_candidate(run: Path) -> Path:
    matches = [
        path.parent
        for path in sorted((run / "candidates").glob("*/verdict.json"))
        if _load(path).get("status") == "verified"
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one verified candidate in {run}, found {matches}")
    return matches[0]


def _synthesis_finished(candidate: Path) -> datetime:
    finished: list[datetime] = []
    for call_path in (candidate / "synthesis" / "calls").glob("*.json"):
        call = _load(call_path)
        stamp = _parse_time(call.get("updated_at_utc"))
        if stamp is not None:
            finished.append(stamp)
            continue
        info = call.get("call_info") or {}
        called = _parse_time(info.get("called_at_utc"))
        if called is not None and info.get("duration_seconds") is not None:
            finished.append(called + timedelta(seconds=float(info["duration_seconds"])))
    if not finished:
        trace_path = REPOSITORY / "results/main/data/traces.json"
        if trace_path.is_file():
            for row in _load(trace_path):
                archived = str(row.get("candidate_path") or "").removeprefix("<RELEASE_ROOT>/")
                if archived and str(candidate).endswith(archived):
                    stamp = _parse_time(row.get("synthesis_finished_at"))
                    if stamp is not None:
                        return stamp
        raise RuntimeError(f"missing synthesis completion timestamp in {candidate}")
    return max(finished)


def _call_seconds(directory: Path) -> tuple[int, float]:
    calls = [_load(path) for path in sorted(directory.glob("*.json"))]
    seconds = sum(
        float((call.get("call_info") or {}).get("duration_seconds", 0) or 0)
        for call in calls
    )
    return len(calls), seconds


def _observed(summary_row: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run = Path(summary_row["run_path"].replace("<RELEASE_ROOT>", str(REPOSITORY)))
    candidate = _verified_candidate(run)

    certificate_class = _load_and_audit_case(summary_row)[3]["certificate_class"]
    obligations: list[dict[str, Any]] = []
    for condition_dir in sorted((candidate / "conditions").glob("*")):
        condition_path = condition_dir / "condition.json"
        if not condition_path.exists():
            continue
        condition = _load(condition_path)
        result_path = condition_dir / "result.json"
        result = _load(result_path) if result_path.exists() else {}
        if result.get("source") == "static" or not condition.get("required", True):
            continue
        query = condition.get("query")
        routing_path = condition_dir / "routing.json"
        routing = _load(routing_path) if routing_path.exists() else {}
        timing_path = condition_dir / "timing.json"
        timing = _load(timing_path) if timing_path.exists() else {}
        router_calls, router_seconds = _call_seconds(condition_dir / "routing" / "calls")
        solver_statuses = {
            path.stem: _load(path).get("status")
            for path in sorted((condition_dir / "solver").glob("*.json"))
        }
        lean_path = condition_dir / "lean" / "result.json"
        lean = _load(lean_path) if lean_path.exists() else None
        attempts = (lean or {}).get("attempts") or []
        lean_calls, lean_llm_seconds = _call_seconds(condition_dir / "lean" / "calls")
        if lean is None:
            path_taken = "smt"
        elif not routing:
            path_taken = "direct_lean_query_free"
        elif routing.get("route") == "direct_lean":
            path_taken = "direct_lean_router"
        else:
            path_taken = "smt_then_lean_rescue"
        obligations.append(
            {
                "record_id": summary_row["record_id"],
                "candidate_dir": candidate.name,
                "condition_slug": condition_dir.name,
                "condition_id": condition.get("condition_id"),
                "condition_kind": condition.get("kind"),
                "query_backed": query is not None,
                "route": routing.get("route"),
                "router_used_fallback": routing.get("used_fallback"),
                "router_llm_calls": router_calls,
                "router_llm_seconds": round(router_seconds, 3),
                "path": path_taken,
                "source": result.get("source"),
                "passed": result.get("passed"),
                "solver_statuses": json.dumps(solver_statuses, sort_keys=True),
                "condition_seconds": timing.get("duration_seconds"),
                "lean_used": lean is not None,
                "lean_seconds": None if lean is None else lean.get("duration_seconds"),
                "lean_attempts": len(attempts),
                "lean_llm_calls": lean_calls,
                "lean_llm_seconds": round(lean_llm_seconds, 3),
                "lean_compiled": None if lean is None else bool(lean.get("compiled")),
                "lean_audit_passed": None if lean is None else bool(lean.get("audit_passed")),
                "lean_repaired": bool(
                    len(attempts) >= 2
                    and not attempts[0].get("compiled", False)
                    and attempts[-1].get("compiled", False)
                ),
            }
        )
    manifest = _load(run / "manifest.json")
    finished_at = _parse_time(manifest.get("finished_at_utc"))
    if finished_at is None:
        raise RuntimeError(f"missing finish timestamp in {run}")
    lean_count = sum(item["lean_used"] for item in obligations)
    certificate = {
        "record_id": summary_row["record_id"],
        "problem_class": summary_row.get("problem_class"),
        "certificate_class": certificate_class,
        "candidate_dir": candidate.name,
        "backend_profile": summary_row.get("backend_profile"),
        "active_obligations": len(obligations),
        "lean_obligations": lean_count,
        "direct_lean_router_obligations": sum(
            item["path"] == "direct_lean_router" for item in obligations
        ),
        "lean_repaired_obligations": sum(item["lean_repaired"] for item in obligations),
        "verification_seconds_trace": (
            finished_at - _synthesis_finished(candidate)
        ).total_seconds(),
        "condition_seconds_sum": sum(
            float(item["condition_seconds"] or 0) for item in obligations
        ),
        "router_llm_calls": sum(item["router_llm_calls"] for item in obligations),
        "lean_llm_calls": sum(item["lean_llm_calls"] for item in obligations),
    }
    return certificate, obligations


def _protocol(
    certificate: dict[str, Any],
    obligations: list[dict[str, Any]],
    all_smt_record: dict[str, Any],
    smt_seconds: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    key = f"{smt_seconds:g}"
    replay = all_smt_record["cutoff_replay"].get(key)
    if replay is None:
        raise RuntimeError(
            f"{certificate['record_id']}: All-SMT record lacks the {key}s cutoff"
        )
    by_id = {item["condition_id"]: item for item in obligations}
    audit = all_smt_record["audit"]
    rows: list[dict[str, Any]] = []
    for condition_id, smt in replay["obligations"].items():
        full = by_id.get(condition_id)
        row: dict[str, Any] = {
            "record_id": certificate["record_id"],
            "condition_id": condition_id,
            "smt_status": smt["status"],
            "smt_seconds": float(smt["duration_seconds"]),
        }
        if smt["status"] == "verified":
            row.update(status="verified", backend="smt", lean_used=False)
            row["seconds"] = row["smt_seconds"]
        elif full is None or not full["lean_used"]:
            row.update(status="missing_lean_trace", backend="lean", lean_used=True)
            row["seconds"] = None
        else:
            lean_ok = bool(full["lean_compiled"] and full["lean_audit_passed"])
            row.update(
                status="verified" if lean_ok else "unresolved",
                backend="lean",
                lean_used=True,
                lean_seconds=float(full["lean_seconds"] or 0),
                lean_llm_calls=full["lean_llm_calls"],
            )
            row["seconds"] = row["smt_seconds"] + row["lean_seconds"]
        rows.append(row)
    rows_by_id = {row["condition_id"]: row for row in rows}
    missing = [row["condition_id"] for row in rows if row["seconds"] is None]
    parallel = [rows_by_id[item] for item in audit["parallel_condition_ids"]]
    sequential = [rows_by_id[item] for item in audit["sequential_condition_ids"]]
    seconds = None
    if not missing:
        seconds = max((row["seconds"] for row in parallel), default=0.0) + sum(
            row["seconds"] for row in sequential
        )
    status = (
        "incomplete"
        if missing
        else "verified"
        if all(row["status"] == "verified" for row in rows)
        else "unresolved"
    )
    return (
        {
            "record_id": certificate["record_id"],
            "certificate_class": audit["certificate_class"],
            "status": status,
            "active_obligations": len(rows),
            "lean_obligations": sum(row["lean_used"] for row in rows),
            "missing_lean_trace": ";".join(missing),
            "virtual_seconds": seconds,
        },
        rows,
    )


def _group(rows: list[dict[str, Any]], seconds_key: str) -> dict[str, Any]:
    active = sum(int(row["active_obligations"]) for row in rows)
    lean = sum(int(row["lean_obligations"]) for row in rows)
    times = [float(row[seconds_key]) for row in rows if row.get(seconds_key) is not None]
    return {
        "certificate_count": len(rows),
        "status_counts": dict(Counter(row.get("status", "verified") for row in rows)),
        "active_obligations": active,
        "lean_obligations": lean,
        "lean_usage_percent": 100.0 * lean / active if active else None,
        f"mean_{seconds_key}": mean(times) if times else None,
    }


def _grouped(rows: list[dict[str, Any]], seconds_key: str) -> dict[str, Any]:
    return {
        "polynomial": _group(
            [row for row in rows if row["certificate_class"] == "polynomial"], seconds_key
        ),
        "non_polynomial": _group(
            [row for row in rows if row["certificate_class"] == "non_polynomial"],
            seconds_key,
        ),
        "overall": _group(rows, seconds_key),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-experiment", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--all-smt",
        type=Path,
        default=None,
        help="All-SMT fixed-certificate output (enables the protocol view)",
    )
    parser.add_argument("--smt-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    source = args.source_experiment.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = sorted(
        (row for row in _load(source / ("full.json" if (source / "full.json").exists() else "summary.json")) if row.get("status") == "verified"),
        key=lambda row: row["record_id"],
    )
    certificates: list[dict[str, Any]] = []
    obligations: list[dict[str, Any]] = []
    protocol_certificates: list[dict[str, Any]] = []
    protocol_obligations: list[dict[str, Any]] = []
    missing_all_smt: list[str] = []
    for row in rows:
        certificate, items = _observed(row)
        certificates.append(certificate)
        obligations.extend(items)
        if args.all_smt is None:
            continue
        record_path = args.all_smt / "records" / f"{row['record_id']}.json"
        if not record_path.exists():
            missing_all_smt.append(row["record_id"])
            continue
        protocol_row, protocol_items = _protocol(
            certificate, items, _load(record_path), args.smt_seconds
        )
        protocol_certificates.append(protocol_row)
        protocol_obligations.extend(protocol_items)

    _write_csv(output / "routed_observed_certificates.csv", certificates)
    _write_csv(output / "routed_observed_obligations.csv", obligations)
    summary: dict[str, Any] = {
        "schema_version": "dynacert-routed-trace.v1",
        "source_experiment": str(source),
        "verified_certificates": len(rows),
        "observed": {
            "definition": (
                "Full-run trace: router LLM -> SMT (30 s/solver) -> Lean rescue "
                "(900 s); query-free radial unboundedness and router-selected "
                "Direct Lean skip SMT. Time = final synthesis completion to run "
                "finalization (includes router LLM calls)."
            ),
            "path_counts": dict(Counter(item["path"] for item in obligations)),
            "results": _grouped(certificates, "verification_seconds_trace"),
        },
    }
    if args.all_smt is not None:
        _write_csv(output / "routed_protocol_certificates.csv", protocol_certificates)
        _write_csv(output / "routed_protocol_obligations.csv", protocol_obligations)
        summary["protocol"] = {
            "definition": (
                f"SMT portfolio for {args.smt_seconds:g} s (All-SMT replay cutoff), "
                "then Lean with the Full-run Lean duration for unresolved obligations"
            ),
            "all_smt_output": str(args.all_smt.resolve()),
            "records_missing_all_smt": missing_all_smt,
            "results": _grouped(
                [row for row in protocol_certificates if row["status"] != "incomplete"],
                "virtual_seconds",
            ),
            "incomplete_certificates": [
                row["record_id"]
                for row in protocol_certificates
                if row["status"] == "incomplete"
            ],
        }
    _atomic_json(output / "routed_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
