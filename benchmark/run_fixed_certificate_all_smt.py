"""Replay frozen certificate obligations using SMT."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4


REPOSITORY = Path(__file__).resolve().parents[1]
CURRENT = REPOSITORY / "llm2cert"
FRAMEWORK = CURRENT / "framework"
sys.path.insert(0, str(FRAMEWORK))

from lean_barrier.s01_models import (
    Backend,
    CandidateSpec,
    Condition,
    ProblemSpec,
    ReplayStatus,
    SolverStatus,
    Witness,
)
from lean_barrier.s02_expressions import content_hash, is_polynomial
from lean_barrier.s03_family_expression import FamilyCandidateSpec
from lean_barrier.s04_semantics import build_conditions
from lean_barrier.s09_router import capability_summary
from lean_barrier.s12_smt_backend import (
    DREAL_DELTA,
    parse_model,
    parse_status,
    query_to_smt2,
)
from lean_barrier.s13_runtime import (
    LocalExecutor,
    LocalRuntime,
    LocalRuntimeManifest,
    has_exact_version_token,
    load_local_runtime_manifest,
    runtime_for_backend,
)
from lean_barrier.s14_replay import (
    interval_replay_witness,
    replay_witness,
)
from lean_barrier.tasks import verify_plan


DEFAULT_SOURCE_EXPERIMENT = (
    REPOSITORY
    / "results" / "main" / "data"
)
DEFAULT_RUNTIME_MANIFEST = Path(
    os.environ.get(
        "DYNACERT_RUNTIME_MANIFEST", str(CURRENT / "config" / "runtime.example.json")
    )
)
DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_CUTOFFS = (30.0, 120.0, 300.0, 600.0, 900.0)
DEFAULT_WORKERS = 8
EXPECTED_CERTIFICATES: int | None = None


RESUME_MUTABLE_KEYS = frozenset(
    {"record_ids", "source_summary_sha256", "workers"}
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_metadata() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPOSITORY,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        return {
            "git_commit": commit,
            "git_dirty": bool(dirty),
            "git_dirty_hash": hashlib.sha256(dirty.encode()).hexdigest(),
        }
    except (OSError, subprocess.SubprocessError):
        return {"git_commit": None, "git_dirty": None, "git_dirty_hash": None}


def _verified_candidate(run_path: Path) -> Path:
    matches: list[Path] = []
    for verdict_path in sorted((run_path / "candidates").glob("*/verdict.json")):
        if _load_json(verdict_path).get("status") == "verified":
            matches.append(verdict_path.parent)
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one final verified candidate in {run_path}, found {matches}"
        )
    return matches[0]


def _query_is_polynomial(condition: Condition) -> bool:
    if condition.query is None:
        raise ValueError("query polynomiality requires a query-backed condition")
    expressions = []
    for constraint in condition.query.constraints:
        expressions.extend((constraint.lhs, constraint.rhs))
    for group in condition.query.any_of:
        for constraint in group.constraints:
            expressions.extend((constraint.lhs, constraint.rhs))
    return all(is_polynomial(expression) for expression in expressions)


def _candidate_class(
    candidate: CandidateSpec | FamilyCandidateSpec,
    active: tuple[Condition, ...],
) -> str:
    if isinstance(candidate, FamilyCandidateSpec):
        expressions = [candidate.certificate_family_ast.body]
        if candidate.shared_controller_ast is not None:
            expressions.append(candidate.shared_controller_ast)
        return (
            "polynomial"
            if all(is_polynomial(expression) for expression in expressions)
            else "non_polynomial"
        )
    polynomial = True
    for condition in active:
        polynomial = polynomial and (
            _query_is_polynomial(condition)
            if condition.query is not None
            else is_polynomial(candidate.certificate_ast)
        )
    return "polynomial" if polynomial else "non_polynomial"


def _load_and_audit_case(
    summary_row: dict[str, Any],
) -> tuple[
    ProblemSpec,
    CandidateSpec | FamilyCandidateSpec,
    tuple[Condition, ...],
    dict[str, Any],
]:
    run_path = Path(summary_row["run_path"].replace("<RELEASE_ROOT>", str(REPOSITORY)))
    candidate_dir = _verified_candidate(run_path)
    problem_path = run_path / "input" / "problem.json"
    candidate_path = candidate_dir / "candidate.json"
    problem = ProblemSpec.model_validate_json(problem_path.read_text(encoding="utf-8"))
    candidate_text = candidate_path.read_text(encoding="utf-8")
    candidate_payload = json.loads(candidate_text)
    candidate: CandidateSpec | FamilyCandidateSpec
    if candidate_payload.get("schema_version") == "lean-barrier.family-candidate.v1":
        candidate = FamilyCandidateSpec.model_validate(candidate_payload, strict=False)
    else:
        candidate = CandidateSpec.model_validate(candidate_payload, strict=False)
    saved_paths = sorted((candidate_dir / "conditions").glob("*/condition.json"))
    saved = tuple(
        Condition.model_validate_json(path.read_text(encoding="utf-8"))
        for path in saved_paths
    )
    digest = content_hash(candidate)
    if any(condition.candidate_hash != digest for condition in saved):
        raise RuntimeError(
            f"{summary_row['record_id']}: candidate hash does not match conditions"
        )


    authoritative = saved
    if isinstance(candidate, FamilyCandidateSpec):
        by_id = {condition.condition_id: condition for condition in authoritative}
        expected_ids = {
            "indexed_family:lyapunov_premises",
            "indexed_family:all_positive_dimensions",
        }
        if set(by_id) != expected_ids:
            raise RuntimeError(
                f"{summary_row['record_id']}: unexpected indexed-family conditions"
            )
        rebuilt = authoritative
        mismatches: list[str] = []
        parallel: tuple[Condition, ...] = ()
        sequential = (
            by_id["indexed_family:lyapunov_premises"],
            by_id["indexed_family:all_positive_dimensions"],
        )
        static: tuple[Condition, ...] = ()
        closing = by_id["indexed_family:all_positive_dimensions"]
        dreal_positive_allowed = False
    else:
        rebuilt = build_conditions(problem, candidate)
        rebuilt_by_id = {condition.condition_id: condition for condition in rebuilt}
        saved_by_id = {condition.condition_id: condition for condition in saved}
        if rebuilt_by_id.keys() != saved_by_id.keys():
            raise RuntimeError(
                f"{summary_row['record_id']}: rebuilt/saved condition id mismatch"
            )
        mismatches = [
            condition_id
            for condition_id in rebuilt_by_id
            if rebuilt_by_id[condition_id] != saved_by_id[condition_id]
        ]
        plan = verify_plan(problem, authoritative)
        parallel = plan.parallel
        sequential = plan.sequential
        static = plan.static
        closing = plan.closing
        dreal_positive_allowed = plan.dreal_positive_allowed
    active = (*parallel, *sequential)
    audit = {
        "source_run_path": str(run_path),
        "source_candidate_path": str(candidate_path),
        "source_problem_sha256": _sha256(problem_path),
        "source_candidate_sha256": _sha256(candidate_path),
        "candidate_hash": digest,
        "condition_count": len(authoritative),
        "active_obligation_count": len(active),
        "condition_manifest_hash": content_hash(
            [condition.model_dump(mode="json") for condition in authoritative]
        ),
        "condition_manifest_exact_match": not mismatches,
        "current_rebuild_mismatch_condition_ids": mismatches,
        "current_rebuild_manifest_hash": content_hash(
            [condition.model_dump(mode="json") for condition in rebuilt]
        ),
        "parallel_condition_ids": [item.condition_id for item in parallel],
        "sequential_condition_ids": [item.condition_id for item in sequential],
        "static_condition_ids": [item.condition_id for item in static],
        "closing_condition_id": closing.condition_id,
        "dreal_positive_allowed": dreal_positive_allowed,
        "certificate_class": _candidate_class(candidate, active),
    }
    return problem, candidate, authoritative, audit


def _runtime_command(
    runtime: LocalRuntime,
    *,
    container_name: str | None,
) -> list[str]:
    if runtime.transport == "host":
        return list(runtime.query_command)
    if runtime.image is None or container_name is None:
        raise RuntimeError("docker runtime requires an image and unique container name")
    command = ["docker", "run", "--rm", "--name", container_name]
    if runtime.platform:
        command.extend(("--platform", runtime.platform))
    command.extend(
        (
            "--network=none",
            "--read-only",
            "--pids-limit=256",
            "--memory=2g",
            "--cpus=1",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=256m",
            "-i",
            runtime.image,
            *runtime.query_command,
        )
    )
    return command


@dataclass
class RunningAttempt:
    backend: Backend
    runtime: LocalRuntime
    query: str
    query_hash: str
    process: asyncio.subprocess.Process
    task: asyncio.Task[tuple[bytes, bytes]]
    started: float
    portfolio_started: float
    container_name: str | None


async def _start_attempt(
    manifest: LocalRuntimeManifest,
    condition: Condition,
    backend: Backend,
    portfolio_started: float,
) -> RunningAttempt:
    assert condition.query is not None
    runtime = runtime_for_backend(manifest, backend)
    if not isinstance(runtime, LocalRuntime):
        raise TypeError("fixed-certificate replay requires a local runtime manifest")
    query = query_to_smt2(condition.query, backend)
    container_name = (
        f"dynacert-rq2-{os.getpid()}-{uuid4().hex[:12]}"
        if runtime.transport == "docker"
        else None
    )
    command = _runtime_command(runtime, container_name=container_name)
    started = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    task = asyncio.create_task(process.communicate(query.encode()))
    return RunningAttempt(
        backend=backend,
        runtime=runtime,
        query=query,
        query_hash=content_hash(query),
        process=process,
        task=task,
        started=started,
        portfolio_started=portfolio_started,
        container_name=container_name,
    )


async def _terminate_attempt(attempt: RunningAttempt) -> None:
    if attempt.process.returncode is not None:
        return
    if attempt.container_name is not None:
        killer = await asyncio.create_subprocess_exec(
            "docker",
            "kill",
            attempt.container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(killer.wait(), timeout=10)
        except TimeoutError:
            killer.kill()
            await killer.wait()
    if attempt.process.returncode is None:
        try:
            attempt.process.terminate()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(attempt.process.wait(), timeout=5)
    except TimeoutError:
        if attempt.process.returncode is None:
            try:
                attempt.process.kill()
            except ProcessLookupError:
                pass
        await attempt.process.wait()


def _point_witness(witness: Witness | None) -> Witness | None:
    if witness is None or witness.point is not None or witness.box is None:
        return witness
    from fractions import Fraction

    point = {
        name: str((Fraction(interval.lower) + Fraction(interval.upper)) / 2)
        for name, interval in witness.box.items()
    }
    return Witness(point=point)


def _completed_result(
    attempt: RunningAttempt,
    stdout_bytes: bytes,
    stderr_bytes: bytes,
    condition: Condition,
    *,
    dreal_positive_allowed: bool,
) -> tuple[dict[str, Any], str | None]:
    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")
    duration = time.monotonic() - attempt.started
    completed_at = time.monotonic() - attempt.portfolio_started
    returncode = attempt.process.returncode if attempt.process.returncode is not None else -1
    status = parse_status(
        stdout,
        stderr,
        timed_out=False,
        returncode=returncode,
    )
    result: dict[str, Any] = {
        "backend": attempt.backend.value,
        "status": status.value,
        "duration_seconds": duration,
        "completed_at_seconds": completed_at,
        "returncode": returncode,
        "expected_version": attempt.runtime.expected_version,
        "container_image": attempt.runtime.image,
        "query_hash": attempt.query_hash,
        "formal_query": attempt.query,
        "stdout": stdout,
        "stderr": stderr,
        "replay_status": ReplayStatus.NOT_APPLICABLE.value,
    }
    if status == SolverStatus.UNSAT:
        if attempt.backend == Backend.DREAL and not dreal_positive_allowed:
            result["acceptance"] = "dreal_unsat_not_allowed_for_this_global_claim"
            return result, None
        result["acceptance"] = "formal_unsat"
        return result, "verified"
    if status not in (SolverStatus.SAT, SolverStatus.DELTA_SAT):
        return result, None
    assert condition.query is not None
    witness = parse_model(stdout, condition.query.variables)
    replayable = _point_witness(witness)
    high_precision = replay_witness(condition.query, replayable)
    interval = interval_replay_witness(condition.query, replayable)
    if interval.status != ReplayStatus.CONFIRMED and status == SolverStatus.DELTA_SAT:
        interval = interval_replay_witness(
            condition.query,
            replayable,
            equality_tolerance=DREAL_DELTA,
        )
    result.update(
        {
            "witness": witness.model_dump(mode="json") if witness else None,
            "replayable_witness": (
                replayable.model_dump(mode="json") if replayable else None
            ),
            "replay_status": interval.status.value,
            "replay_residual": (
                f"high_precision={high_precision.residual}; "
                f"interval={interval.residual}"
            ),
        }
    )
    if interval.status == ReplayStatus.CONFIRMED and replayable is not None:
        result["acceptance"] = "confirmed_counterexample"
        return result, "rejected"
    result["acceptance"] = "unconfirmed_model"
    return result, None


async def _run_portfolio(
    manifest: LocalRuntimeManifest,
    condition: Condition,
    *,
    timeout_seconds: float,
    dreal_positive_allowed: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    capabilities = capability_summary(condition)
    eligible = list(capabilities.eligible_backends)
    excluded: list[dict[str, str]] = []
    if Backend.DREAL in eligible and not dreal_positive_allowed:
        eligible.remove(Backend.DREAL)
        excluded.append(
            {
                "backend": Backend.DREAL.value,
                "reason": "dreal positive conclusion is not allowed for this global claim",
            }
        )
    base: dict[str, Any] = {
        "condition_id": condition.condition_id,
        "condition_kind": condition.kind.value,
        "candidate_hash": condition.candidate_hash,
        "query_hash": (
            content_hash(condition.query.model_dump(mode="json"))
            if condition.query is not None
            else None
        ),
        "polynomial_nra": capabilities.polynomial_nra,
        "transcendental": capabilities.transcendental,
        "formally_bounded": capabilities.formally_bounded,
        "eligible_backends": [backend.value for backend in eligible],
        "excluded_backends": excluded,
        "timeout_seconds": timeout_seconds,
        "lean_rescue": False,
    }
    if condition.query is None or not eligible:
        return {
            **base,
            "portfolio_status": "unsupported",
            "first_conclusive": None,
            "duration_seconds": time.monotonic() - started,
            "backend_results": [],
        }

    attempts: list[RunningAttempt] = []
    immediate_results: list[dict[str, Any]] = []
    for backend in eligible:
        try:
            attempts.append(
                await _start_attempt(manifest, condition, backend, started)
            )
        except Exception as error:
            immediate_results.append(
                {
                    "backend": backend.value,
                    "status": "error",
                    "duration_seconds": time.monotonic() - started,
                    "completed_at_seconds": time.monotonic() - started,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    pending = {attempt.task: attempt for attempt in attempts}
    backend_results = list(immediate_results)
    first_conclusive: dict[str, Any] | None = None
    deadline = started + timeout_seconds
    timed_out = False

    while pending and first_conclusive is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        done, _ = await asyncio.wait(
            pending,
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            timed_out = True
            break
        completed: list[tuple[dict[str, Any], str | None]] = []
        for task in done:
            attempt = pending.pop(task)
            try:
                stdout, stderr = task.result()
                completed.append(
                    _completed_result(
                        attempt,
                        stdout,
                        stderr,
                        condition,
                        dreal_positive_allowed=dreal_positive_allowed,
                    )
                )
            except Exception as error:
                completed.append(
                    (
                        {
                            "backend": attempt.backend.value,
                            "status": "error",
                            "duration_seconds": time.monotonic() - attempt.started,
                            "completed_at_seconds": time.monotonic() - started,
                            "error": f"{type(error).__name__}: {error}",
                        },
                        None,
                    )
                )
        completed.sort(key=lambda item: item[0]["completed_at_seconds"])
        for result, conclusion in completed:
            backend_results.append(result)
            if conclusion is not None and first_conclusive is None:
                first_conclusive = {
                    "status": conclusion,
                    "backend": result["backend"],
                    "completed_at_seconds": result["completed_at_seconds"],
                }

    stop_reason = "portfolio_timeout" if timed_out else "first_conclusive_result"
    if first_conclusive is None and not timed_out:
        stop_reason = "all_backends_exhausted_without_conclusion"
    if pending:
        pending_items = list(pending.items())
        await asyncio.gather(
            *(_terminate_attempt(attempt) for _, attempt in pending_items)
        )
        for task, attempt in pending_items:
            try:
                stdout, stderr = await task
            except Exception:
                stdout, stderr = b"", b""
            backend_results.append(
                {
                    "backend": attempt.backend.value,
                    "status": "timeout" if timed_out else "cancelled",
                    "duration_seconds": time.monotonic() - attempt.started,
                    "completed_at_seconds": time.monotonic() - started,
                    "returncode": attempt.process.returncode,
                    "expected_version": attempt.runtime.expected_version,
                    "container_image": attempt.runtime.image,
                    "query_hash": attempt.query_hash,
                    "formal_query": attempt.query,
                    "stdout": stdout.decode(errors="replace"),
                    "stderr": stderr.decode(errors="replace"),
                    "cancel_reason": stop_reason,
                }
            )

    if first_conclusive is not None:
        portfolio_status = first_conclusive["status"]
    elif timed_out:
        portfolio_status = "timeout"
    else:
        portfolio_status = "unresolved"
    return {
        **base,
        "portfolio_status": portfolio_status,
        "first_conclusive": first_conclusive,
        "duration_seconds": time.monotonic() - started,
        "stop_reason": stop_reason,
        "backend_results": sorted(
            backend_results, key=lambda item: item.get("backend", "")
        ),
    }


def _replay_obligation(result: dict[str, Any], cutoff: float) -> dict[str, Any]:
    if result["portfolio_status"] == "unsupported":
        return {"status": "unsupported", "duration_seconds": 0.0}
    conclusion = result.get("first_conclusive")
    if conclusion is not None and conclusion["completed_at_seconds"] <= cutoff:
        return {
            "status": conclusion["status"],
            "duration_seconds": conclusion["completed_at_seconds"],
            "backend": conclusion["backend"],
        }
    terminal = []
    running_at_cutoff = False
    for backend in result["backend_results"]:
        completed_at = float(backend.get("completed_at_seconds", 0.0))
        status = backend.get("status")
        if completed_at > cutoff or status in {"timeout", "cancelled"}:
            running_at_cutoff = True
        else:
            terminal.append(completed_at)
    if running_at_cutoff:
        return {"status": "timeout", "duration_seconds": cutoff}
    return {
        "status": "unresolved",
        "duration_seconds": max(terminal, default=0.0),
    }


def _replay_candidate(
    obligation_results: dict[str, dict[str, Any]],
    audit: dict[str, Any],
    cutoff: float,
) -> dict[str, Any]:
    replayed = {
        condition_id: _replay_obligation(result, cutoff)
        for condition_id, result in obligation_results.items()
    }
    elapsed = 0.0
    parallel = [replayed[item] for item in audit["parallel_condition_ids"]]
    if parallel:
        elapsed += max(float(item["duration_seconds"]) for item in parallel)
        failed = [item for item in parallel if item["status"] != "verified"]
        if failed:
            status = "rejected" if any(item["status"] == "rejected" for item in failed) else "unresolved"
            return {
                "status": status,
                "duration_seconds": elapsed,
                "obligations": replayed,
            }
    for condition_id in audit["sequential_condition_ids"]:
        item = replayed[condition_id]
        elapsed += float(item["duration_seconds"])
        if item["status"] != "verified":
            return {
                "status": "rejected" if item["status"] == "rejected" else "unresolved",
                "duration_seconds": elapsed,
                "obligations": replayed,
            }
    return {"status": "verified", "duration_seconds": elapsed, "obligations": replayed}


async def _run_case(
    manifest: LocalRuntimeManifest,
    summary_row: dict[str, Any],
    *,
    timeout_seconds: float,
    cutoffs: tuple[float, ...],
) -> dict[str, Any]:
    _, _, conditions, audit = _load_and_audit_case(summary_row)
    plan_ids = set(audit["parallel_condition_ids"]) | set(
        audit["sequential_condition_ids"]
    )
    active = tuple(item for item in conditions if item.condition_id in plan_ids)
    started = time.monotonic()

    async def run_one(condition: Condition) -> tuple[str, dict[str, Any]]:
        return (
            condition.condition_id,
            await _run_portfolio(
                manifest,
                condition,
                timeout_seconds=timeout_seconds,
                dreal_positive_allowed=bool(audit["dreal_positive_allowed"]),
            ),
        )

    obligation_pairs = await asyncio.gather(*(run_one(item) for item in active))
    obligation_results = dict(obligation_pairs)
    replay = {
        f"{cutoff:g}": _replay_candidate(obligation_results, audit, cutoff)
        for cutoff in cutoffs
    }
    return {
        "schema_version": "dynacert-rq2-all-smt-certificate.v1",
        "record_id": summary_row["record_id"],
        "source_summary_row": summary_row,
        "audit": audit,
        "physical_collection_seconds": time.monotonic() - started,
        "obligation_results": obligation_results,
        "cutoff_replay": replay,
    }


def _summarize(records: list[dict[str, Any]], cutoffs: tuple[float, ...]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {
        "polynomial": [],
        "non_polynomial": [],
        "overall": list(records),
    }
    for record in records:
        groups[record["audit"]["certificate_class"]].append(record)
    summary: dict[str, Any] = {}
    for cutoff in cutoffs:
        key = f"{cutoff:g}"
        summary[key] = {}
        for group_name, group in groups.items():
            candidate_results = [item["cutoff_replay"][key] for item in group]
            obligations = [
                obligation
                for candidate in candidate_results
                for obligation in candidate["obligations"].values()
            ]
            summary[key][group_name] = {
                "certificate_count": len(group),
                "verified": sum(item["status"] == "verified" for item in candidate_results),
                "unresolved": sum(item["status"] == "unresolved" for item in candidate_results),
                "rejected": sum(item["status"] == "rejected" for item in candidate_results),
                "average_virtual_wall_seconds": (
                    mean(float(item["duration_seconds"]) for item in candidate_results)
                    if candidate_results
                    else None
                ),
                "active_obligations": len(obligations),
                "obligation_statuses": {
                    status: sum(item["status"] == status for item in obligations)
                    for status in ("verified", "timeout", "unsupported", "unresolved", "rejected")
                },
                "lean_usage_percent": 0.0,
            }
    return summary


def _runtime_preflight(
    manifest: LocalRuntimeManifest,
) -> dict[str, dict[str, Any]]:
    executor = LocalExecutor()
    results: dict[str, dict[str, Any]] = {}
    for backend in Backend:
        runtime = runtime_for_backend(manifest, backend)
        started = time.monotonic()
        execution = executor.version(runtime, timeout_seconds=30)
        output = f"{execution.stdout}\n{execution.stderr}"
        passed = (
            not execution.timed_out
            and execution.returncode == 0
            and has_exact_version_token(output, runtime.expected_version)
        )
        results[backend.value] = {
            "passed": passed,
            "expected_version": runtime.expected_version,
            "duration_seconds": time.monotonic() - started,
            "stdout": execution.stdout,
            "stderr": execution.stderr,
            "container_image": runtime.image,
        }
        if not passed:
            raise RuntimeError(
                f"{backend.value} version preflight failed; expected "
                f"{runtime.expected_version!r}, output={output.strip()!r}"
            )
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-experiment", type=Path, default=DEFAULT_SOURCE_EXPERIMENT)
    parser.add_argument("--runtime-manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--cutoffs", type=float, nargs="+", default=DEFAULT_CUTOFFS)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--record-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--expected-certificates",
        type=int,
        default=EXPECTED_CERTIFICATES,
        help="optional guard on the number of verified source certificates",
    )
    return parser


async def _async_main(args: argparse.Namespace) -> int:
    source_experiment = args.source_experiment.resolve()
    runtime_path = args.runtime_manifest.resolve()
    output = args.output.resolve()
    timeout_seconds = float(args.timeout_seconds)
    workers = int(args.workers)
    cutoffs = tuple(sorted(set(float(item) for item in args.cutoffs)))
    if timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if workers <= 0:
        raise SystemExit("--workers must be positive")
    if not cutoffs or cutoffs[-1] > timeout_seconds or cutoffs[0] <= 0:
        raise SystemExit("cutoffs must be positive and no larger than the physical timeout")
    summary_path = source_experiment / ("full.json" if (source_experiment / "full.json").exists() else "summary.json")
    rows = [item for item in _load_json(summary_path) if item.get("status") == "verified"]
    rows.sort(key=lambda item: item["record_id"])
    if args.record_id:
        requested = set(args.record_id)
        rows = [item for item in rows if item["record_id"] in requested]
        missing = requested - {item["record_id"] for item in rows}
        if missing:
            raise SystemExit(f"requested records are not verified RQ1 certificates: {sorted(missing)}")
    if args.limit is not None:
        if args.limit <= 0:
            raise SystemExit("--limit must be positive")
        rows = rows[: args.limit]
    expected_certificates = args.expected_certificates
    if (
        expected_certificates is not None
        and not args.record_id
        and args.limit is None
        and len(rows) != expected_certificates
    ):
        raise RuntimeError(
            f"expected {expected_certificates} final verified certificates, found {len(rows)}"
        )

    manifest = load_local_runtime_manifest(runtime_path)
    configuration = {
        "schema_version": "dynacert-rq2-all-smt.v1",
        "source_experiment": str(source_experiment),
        "source_summary_sha256": _sha256(summary_path),
        "runtime_manifest": str(runtime_path),
        "runtime_manifest_sha256": _sha256(runtime_path),
        "timeout_seconds": timeout_seconds,
        "cutoffs": list(cutoffs),
        "workers": workers,
        "record_ids": [item["record_id"] for item in rows],
        "strategy": "all_smt_fixed_parallel_portfolio_no_lean_rescue",
        "first_conclusive_wins": True,
        "candidate_synthesis": False,
        "router_llm": False,
        "proof_llm": False,
        **_git_metadata(),
    }
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        existing = _load_json(manifest_path)
        ignored = {
            "started_at_utc",
            "finished_at_utc",
            "runtime_preflight",
            "resume_history",
            *RESUME_MUTABLE_KEYS,
        }
        comparable = {
            key: value for key, value in existing.items() if key not in ignored
        }
        requested = {
            key: value for key, value in configuration.items() if key not in ignored
        }
        if comparable != requested:
            raise SystemExit(f"output manifest configuration mismatch: {manifest_path}")
        if not args.resume:
            raise SystemExit(f"output already exists; use --resume: {output}")
        history = list(existing.get("resume_history") or [])
        history.append(
            {
                "resumed_at_utc": _utc_now(),
                "previous_record_ids": existing.get("record_ids"),
                "previous_source_summary_sha256": existing.get("source_summary_sha256"),
                "previous_workers": existing.get("workers"),
            }
        )
        _atomic_json(
            manifest_path,
            {
                **existing,
                **{key: configuration[key] for key in RESUME_MUTABLE_KEYS},
                "resume_history": history,
            },
        )
    else:
        output.mkdir(parents=True, exist_ok=False)
        preflight = _runtime_preflight(manifest)
        _atomic_json(
            manifest_path,
            {**configuration, "started_at_utc": _utc_now(), "runtime_preflight": preflight},
        )

    records_dir = output / "records"
    completed_by_id: dict[str, dict[str, Any]] = {}
    pending_rows: list[tuple[int, dict[str, Any]]] = []
    for index, row in enumerate(rows, start=1):
        record_path = records_dir / f"{row['record_id']}.json"
        if record_path.exists() and args.resume:
            completed_by_id[row["record_id"]] = _load_json(record_path)
        else:
            pending_rows.append((index, row))

    semaphore = asyncio.Semaphore(workers)

    async def run_record(index: int, row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        async with semaphore:
            record_id = str(row["record_id"])
            print(f"[{index}/{len(rows)}] {record_id} starting", flush=True)
            result = await _run_case(
                manifest,
                row,
                timeout_seconds=timeout_seconds,
                cutoffs=cutoffs,
            )
            _atomic_json(records_dir / f"{record_id}.json", result)
            print(
                f"[{index}/{len(rows)}] {record_id} "
                f"{cutoffs[-1]:g}s="
                f"{result['cutoff_replay'][f'{cutoffs[-1]:g}']['status']} "
                f"physical={result['physical_collection_seconds']:.2f}s",
                flush=True,
            )
            return record_id, result

    tasks = [
        asyncio.create_task(run_record(index, row))
        for index, row in pending_rows
    ]
    for task in asyncio.as_completed(tasks):
        record_id, result = await task
        completed_by_id[record_id] = result
        completed = [
            completed_by_id[row["record_id"]]
            for row in rows
            if row["record_id"] in completed_by_id
        ]
        _atomic_json(
            output / "summary.partial.json",
            {
                "completed_records": len(completed),
                "total_records": len(rows),
                "results": _summarize(completed, cutoffs),
            },
        )

    completed = [completed_by_id[row["record_id"]] for row in rows]

    summary = {
        "schema_version": "dynacert-rq2-all-smt-summary.v1",
        "strategy": "All-SMT",
        "candidate_source": "only the unique final verified candidate from each RQ1 run",
        "certificate_count": len(completed),
        "active_obligation_count": sum(
            item["audit"]["active_obligation_count"] for item in completed
        ),
        "llm_calls": 0,
        "lean_calls": 0,
        "results": _summarize(completed, cutoffs),
        "finished_at_utc": _utc_now(),
    }
    _atomic_json(output / "summary.json", summary)
    manifest_payload = _load_json(manifest_path)
    _atomic_json(
        manifest_path,
        {**manifest_payload, "finished_at_utc": summary["finished_at_utc"]},
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
