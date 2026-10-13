"""Replay frozen certificate obligations using Lean."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4


REPOSITORY = Path(__file__).resolve().parents[1]
CURRENT = REPOSITORY / "llm2cert"
FRAMEWORK = CURRENT / "framework"
sys.path.insert(0, str(CURRENT))
sys.path.insert(0, str(FRAMEWORK))

from config import API_KEY, BASE_URL, MODEL, PROVIDER
from pipeline_app import (
    MAX_TOKENS,
    REASONING_EFFORT,
    ROLE_PARAMS,
    THINKING,
)
from lean_barrier.s01_models import (
    BackendProfile,
    CandidateSpec,
    CandidateStatus,
    CandidateVerdict,
    CertificationLevel,
    Condition,
    ConditionKind,
    ConditionOutcome,
    ProblemSpec,
    VerificationRoute,
    VerificationRouterDecision,
    VerificationScope,
)
from lean_barrier.s02_expressions import content_hash, is_polynomial
from lean_barrier.s03_family_expression import FamilyCandidateSpec
from lean_barrier.s04_semantics import build_conditions
from lean_barrier.s06_agent_suite import PromptedAgentSuite
from lean_barrier.s06_agents import MAX_FORMAT_REPAIRS, StructuredAgentRunner
from lean_barrier.s06_transport import make_http_transport
from lean_barrier.s10_lean_backend import (
    DevelopmentLeanCompiler,
    LeanProofRunner,
)
from lean_barrier.s10_family_lean_gen import generate_family_locked_theorem
from lean_barrier.s10_lean_runner import (
    MAX_NAME_REPAIR_ROUNDS,
    MAX_PROOF_ROUNDS,
    MAX_PROOF_SECONDS,
)
from lean_barrier.s13_runtime import (
    DEFAULT_FINALIZATION_RESERVE_SECONDS,
    ExecutionResult,
    RunDeadline,
    RunDeadlineExceeded,
)
from lean_barrier.s15_artifacts import RecordingTransport, RunBundleStore
from lean_barrier.s16_workflow import CandidateVerifier, FormalOutcome
from lean_barrier.s18_family_workflow import FamilyCandidateVerifier
from lean_barrier.tasks import verify_plan


DEFAULT_SOURCE_EXPERIMENT = (
    REPOSITORY
    / "results" / "main" / "data"
)
DEFAULT_BUDGET_SECONDS = 900.0
DEFAULT_WORKERS = 8
EXPECTED_CERTIFICATES: int | None = None


RESUME_MUTABLE_KEYS = frozenset({"record_ids", "source_summary_sha256"})
RESUME_MUTABLE_STRATEGY_KEYS = frozenset({"fixed_certificate_workers"})


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _assert_source_lean_configuration(
    source: Path,
    *,
    budget_seconds: float,
) -> dict[str, Any]:
    source_experiment = _load_json(source / "experiment.json")
    runtime_parameters = {
        "thinking": THINKING,
        "reasoning_effort": REASONING_EFFORT,
        "max_tokens": MAX_TOKENS,
        **ROLE_PARAMS["lean"],
    }
    source_parameters = (source_experiment.get("model_parameters") or {}).get("lean")
    source_strategy = source_experiment.get("strategy") or {}
    source_timeouts = source_experiment.get("timeouts") or {}
    expected_strategy = {
        "contextual_local_repair": False,
        "kernel_first": False,
        "json_format_repairs": MAX_FORMAT_REPAIRS,
        "lean_proof_rounds": MAX_PROOF_ROUNDS,
        "lean_name_repair_rounds": MAX_NAME_REPAIR_ROUNDS,
    }
    observed_strategy = {key: source_strategy.get(key) for key in expected_strategy}
    expected_timeouts = {
        "lean_condition_seconds": float(budget_seconds),
        "lean_llm_call_seconds": float(ROLE_PARAMS["lean"]["call_timeout_seconds"]),
        "finalization_reserve_seconds": DEFAULT_FINALIZATION_RESERVE_SECONDS,
    }
    observed_timeouts = {key: source_timeouts.get(key) for key in expected_timeouts}
    if source_experiment.get("provider") != PROVIDER or source_experiment.get("model") != MODEL:
        raise RuntimeError("All-Lean runtime provider/model differs from the source RQ1 run")
    if source_parameters != runtime_parameters:
        raise RuntimeError(
            "All-Lean runtime model parameters differ from the source RQ1 Lean role: "
            f"source={source_parameters}, runtime={runtime_parameters}"
        )
    if observed_strategy != expected_strategy:
        raise RuntimeError(
            "All-Lean proof-loop parameters differ from the source RQ1 run: "
            f"source={observed_strategy}, runtime={expected_strategy}"
        )
    if observed_timeouts != expected_timeouts or MAX_PROOF_SECONDS != budget_seconds:
        raise RuntimeError(
            "All-Lean timeout parameters differ from the source RQ1 run: "
            f"source={observed_timeouts}, runtime={expected_timeouts}"
        )
    return {
        "provider": PROVIDER,
        "model": MODEL,
        "model_parameters": runtime_parameters,
        "strategy": expected_strategy,
        "timeouts": expected_timeouts,
    }


def _verified_candidate(run_path: Path) -> Path:
    matches = []
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
    polynomial = all(
        _query_is_polynomial(condition)
        if condition.query is not None
        else is_polynomial(candidate.certificate_ast)
        for condition in active
    )
    return "polynomial" if polynomial else "non_polynomial"


def _load_fixed_case(
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
    authoritative = tuple(
        Condition.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted((candidate_dir / "conditions").glob("*/condition.json"))
    )
    digest = content_hash(candidate)
    if not authoritative or any(item.candidate_hash != digest for item in authoritative):
        raise RuntimeError(
            f"{summary_row['record_id']}: saved conditions do not match candidate hash"
        )
    rebuild_error = None
    mismatch_ids: list[str] = []
    rebuild_hash = None
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
        parallel: tuple[Condition, ...] = ()
        sequential = (
            by_id["indexed_family:lyapunov_premises"],
            by_id["indexed_family:all_positive_dimensions"],
        )
        static: tuple[Condition, ...] = ()
        closing = by_id["indexed_family:all_positive_dimensions"]
        rebuild_hash = content_hash(
            [item.model_dump(mode="json") for item in authoritative]
        )
    else:
        plan = verify_plan(problem, authoritative)
        parallel = plan.parallel
        sequential = plan.sequential
        static = plan.static
        closing = plan.closing
        try:
            rebuilt = build_conditions(problem, candidate)
            rebuilt_by_id = {item.condition_id: item for item in rebuilt}
            saved_by_id = {item.condition_id: item for item in authoritative}
            mismatch_ids = sorted(
                set(rebuilt_by_id).symmetric_difference(saved_by_id)
                | {
                    condition_id
                    for condition_id in set(rebuilt_by_id).intersection(saved_by_id)
                    if rebuilt_by_id[condition_id] != saved_by_id[condition_id]
                }
            )
            rebuild_hash = content_hash(
                [item.model_dump(mode="json") for item in rebuilt]
            )
        except Exception as error:
            rebuild_error = f"{type(error).__name__}: {error}"
    active = (*parallel, *sequential)

    audit = {
        "record_id": summary_row["record_id"],
        "source_run_path": str(run_path),
        "source_candidate_path": str(candidate_path),
        "source_problem_sha256": _sha256(problem_path),
        "source_candidate_sha256": _sha256(candidate_path),
        "candidate_hash": digest,
        "condition_source": "authoritative saved RQ1 manifests",
        "condition_count": len(authoritative),
        "active_obligation_count": len(active),
        "condition_manifest_hash": content_hash(
            [item.model_dump(mode="json") for item in authoritative]
        ),
        "current_rebuild_exact_match": not rebuild_error and not mismatch_ids,
        "current_rebuild_error": rebuild_error,
        "current_rebuild_mismatch_condition_ids": mismatch_ids,
        "current_rebuild_manifest_hash": rebuild_hash,
        "parallel_condition_ids": [item.condition_id for item in parallel],
        "sequential_condition_ids": [item.condition_id for item in sequential],
        "static_condition_ids": [item.condition_id for item in static],
        "closing_condition_id": closing.condition_id,
        "certificate_class": _candidate_class(candidate, active),
    }
    return problem, candidate, authoritative, audit


class FreshRecordingLeanCompiler:


    formal = True

    def __init__(self, lean_project: Path, store: RunBundleStore) -> None:
        self.delegate = DevelopmentLeanCompiler(lean_project)
        self.lean_project = self.delegate.lean_project
        self.store = store
        self._sequences: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def _next(self, candidate_hash: str, condition_id: str) -> int:
        key = (candidate_hash, condition_id)
        with self._lock:
            value = self._sequences.get(key, 0)
            self._sequences[key] = value + 1
        return value

    def compile(self, source: str, *, timeout_seconds: float) -> ExecutionResult:
        context = self.store.current_context()
        candidate_hash = context.get("candidate_hash")
        condition_id = context.get("condition_id")
        if not candidate_hash or not condition_id:
            return self.delegate.compile(source, timeout_seconds=timeout_seconds)
        sequence = self._next(candidate_hash, condition_id)
        component = f"lean/compiler_attempts/{sequence:02d}"
        self.store.write_condition_text(
            candidate_hash, condition_id, component + "/source", source, ".lean"
        )
        base = {
            "schema_version": "dynacert-lean-compile.v2",
            "source_hash": content_hash(source),
            "timeout_seconds": timeout_seconds,
            "generated_module_cache": False,
        }
        self.store.write_condition_json(
            candidate_hash,
            condition_id,
            component + "/result",
            {**base, "status": "started"},
        )
        try:
            result = self.delegate.compile(source, timeout_seconds=timeout_seconds)
        except Exception as error:
            self.store.write_condition_json(
                candidate_hash,
                condition_id,
                component + "/result",
                {**base, "status": "failed", "error": f"{type(error).__name__}: {error}"},
            )
            raise
        self.store.write_condition_json(
            candidate_hash,
            condition_id,
            component + "/result",
            {
                **base,
                "status": "completed",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_seconds": result.duration_seconds,
                "timed_out": result.timed_out,
            },
        )
        return result


class RetryingUpstreamTransport:


    def __init__(self, delegate: Any, deadline: RunDeadline) -> None:
        self.delegate = delegate
        self.deadline = deadline
        self.last_call_info: dict[str, Any] = {}

    def __call__(self, **kwargs: Any) -> Any:
        upstream_retries = 0
        for delay in (2.0, 5.0, 10.0, 20.0, 40.0, None):
            try:
                response = self.delegate(**kwargs)
            except RuntimeError as error:
                text = str(error)
                transient = "HTTP 400" in text and "Upstream request failed" in text
                if not transient or delay is None:
                    raise
                upstream_retries += 1
                remaining = self.deadline.remaining(
                    reserve_seconds=DEFAULT_FINALIZATION_RESERVE_SECONDS
                )
                if remaining <= delay:
                    raise RunDeadlineExceeded(
                        "condition proof budget exhausted during upstream retry"
                    ) from error
                print(
                    f"[{kwargs.get('schema_name', 'agent')}] upstream HTTP 400; "
                    f"retrying in {delay:g}s",
                    flush=True,
                )
                time.sleep(delay)
                continue
            info = dict(getattr(self.delegate, "last_call_info", None) or {})
            info["upstream_400_retries"] = upstream_retries
            info["attempts"] = int(info.get("attempts", 1) or 1) + upstream_retries
            self.last_call_info = info
            return response
        raise AssertionError("unreachable upstream retry loop")


def _direct_lean_router(
    condition: Condition, _capabilities: dict[str, object]
) -> VerificationRouterDecision:
    return VerificationRouterDecision(
        condition_id=condition.condition_id,
        route=VerificationRoute.DIRECT_LEAN,
        rationale="All-Lean fixed-certificate ablation",
    )


def _proof_provider(store: RunBundleStore, deadline: RunDeadline):


    def provide(problem, candidate, condition, locked, mode):
        params = {
            "thinking": THINKING,
            "reasoning_effort": REASONING_EFFORT,
            "max_tokens": MAX_TOKENS,
        }
        params.update(ROLE_PARAMS["lean"])
        http = make_http_transport(
            provider=PROVIDER,
            api_key=API_KEY,
            base_url=BASE_URL,
            model=MODEL,
            deadline=deadline,
            **params,
        )
        transport = RetryingUpstreamTransport(http, deadline)
        recorded = RecordingTransport(
            transport,
            store,
            role="lean",
            prompt_version="v1",
            model_id=MODEL,
            parameters={
                "provider": PROVIDER,
                "thinking": http.thinking,
                "reasoning_effort": REASONING_EFFORT,
                "max_tokens": http.max_tokens,
                "call_timeout_seconds": params["call_timeout_seconds"],
                "fresh_condition_transport": True,
            },
        )
        runner = StructuredAgentRunner(recorded, supports_structured_outputs=False)
        suite = PromptedAgentSuite(runner, runner, runner, contextual_local_repair=False)
        prove = suite.proof_agent(problem, candidate, condition, locked, mode)

        def scoped(round_index: int, previous: str, diagnostics: str):
            with store.scope(
                candidate_hash=condition.candidate_hash,
                condition_id=condition.condition_id,
                stage="lean",
            ):
                return prove(round_index, previous, diagnostics)

        return scoped

    return provide


class FixedAllLeanVerifier(CandidateVerifier):


    def __init__(self, *, condition_budget_seconds: float, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.condition_budget_seconds = float(condition_budget_seconds)

    def _verify_condition(
        self,
        problem: ProblemSpec,
        candidate: CandidateSpec,
        condition: Condition,
        *,
        dreal_positive_allowed: bool = True,
    ) -> FormalOutcome:


        condition_deadline = RunDeadline(
            self.condition_budget_seconds + DEFAULT_FINALIZATION_RESERVE_SECONDS
        )
        if self.lean_runner is None or not isinstance(self.store, RunBundleStore):
            raise RuntimeError("fixed All-Lean verifier is missing its Lean runtime")
        self.deadline = condition_deadline
        self.lean_runner.deadline = condition_deadline
        self.proof_agent_provider = _proof_provider(self.store, condition_deadline)
        started = time.monotonic()
        started_at = _utc_now()
        result: FormalOutcome | None = None
        error_text = None
        try:
            result = super()._verify_condition(
                problem,
                candidate,
                condition,
                dreal_positive_allowed=dreal_positive_allowed,
            )
            return result
        except Exception as error:
            error_text = f"{type(error).__name__}: {error}"
            raise
        finally:
            if isinstance(self.store, RunBundleStore):
                self.store.write_condition_json(
                    condition.candidate_hash,
                    condition.condition_id,
                    "timing",
                    {
                        "schema_version": "dynacert-fixed-condition-timing.v1",
                        "started_at_utc": started_at,
                        "wall_seconds": time.monotonic() - started,
                        "passed": None if result is None else result.passed,
                        "source": None if result is None else result.source,
                        "error": error_text,
                    },
                )

    def _verify_group(
        self,
        problem: ProblemSpec,
        candidate: CandidateSpec,
        items: tuple[Condition, ...],
        digest: str,
        outcomes: list[ConditionOutcome],
        active_formal_sources: list[str],
        *,
        allow_dreal: bool,
    ) -> CandidateVerdict | None:


        for condition in items:
            decided = super()._verify_group(
                problem,
                candidate,
                (condition,),
                digest,
                outcomes,
                active_formal_sources,
                allow_dreal=allow_dreal,
            )
            if decided is not None:
                return decided
        return None

    def verify_fixed(
        self,
        problem: ProblemSpec,
        candidate: CandidateSpec,
        conditions: tuple[Condition, ...],
    ) -> CandidateVerdict:
        digest = content_hash(candidate)
        if any(item.candidate_hash != digest for item in conditions):
            raise RuntimeError("fixed condition/candidate hash mismatch")
        if self.store:
            self.store.write_json("candidates", digest, candidate)
            if isinstance(self.store, RunBundleStore):
                for condition in conditions:
                    self.store.write_condition_json(
                        digest, condition.condition_id, "condition", condition
                    )
                self.store.write_json(
                    "fastcheck",
                    digest,
                    {
                        "status": "not_run_fixed_certificate_replay",
                        "candidate_hash": digest,
                        "reason": "authoritative RQ1 obligations are replayed directly",
                    },
                )

        plan = verify_plan(problem, conditions)
        outcomes: list[ConditionOutcome] = []
        active_formal_sources: list[str] = []

        for condition in plan.static:
            static_outcome = ConditionOutcome(
                condition_id=condition.condition_id,
                passed=True,
                source="static",
                detail="instantiated audited smooth-DSL common lemma",
            )
            outcomes.append(static_outcome)
            if isinstance(self.store, RunBundleStore):
                self.store.write_condition_json(
                    digest, condition.condition_id, "result", static_outcome
                )

        decided = self._verify_group(
            problem,
            candidate,
            plan.parallel,
            digest,
            outcomes,
            active_formal_sources,
            allow_dreal=plan.dreal_positive_allowed,
        )
        if decided is not None:
            return decided

        decided = self._verify_group(
            problem,
            candidate,
            plan.sequential,
            digest,
            outcomes,
            active_formal_sources,
            allow_dreal=plan.dreal_positive_allowed,
        )
        if decided is not None:
            return decided

        closing = plan.closing
        closing_outcome = ConditionOutcome(
            condition_id=closing.condition_id,
            passed=True,
            source="static",
            detail=(
                "applied audited generic Lean theorem "
                f"LeanBarrier.Lyapunov.{closing.lean_theorem_name}: {closing.description}"
                if closing.kind
                in {
                    ConditionKind.STABILITY_INSTANTIATION,
                    ConditionKind.ROA_INSTANTIATION,
                }
                else "applied audited generic Lean theorem "
                f"LeanBarrier.{closing.lean_theorem_name}: {closing.description}"
            ),
        )
        outcomes.append(closing_outcome)
        if isinstance(self.store, RunBundleStore):
            self.store.write_condition_json(
                digest, closing.condition_id, "result", closing_outcome
            )
        sources = set(active_formal_sources)
        if sources != {"lean"}:
            raise RuntimeError(f"All-Lean replay produced unexpected sources: {sources}")
        return self._record_verdict(
            CandidateVerdict(
                candidate_hash=digest,
                status=CandidateStatus.VERIFIED,
                certification=CertificationLevel.LEAN_CERTIFIED,
                scope=VerificationScope.PROPERTY_VERIFIED,
                backend_profile=BackendProfile.LEAN,
                outcomes=tuple(outcomes),
            )
        )


def _usage(call: dict[str, Any]) -> tuple[int, int, int, float]:
    info = call.get("call_info") or {}
    usage = info.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    output_tokens = int(
        usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
    )
    total_tokens = int(usage.get("total_tokens", 0) or 0)
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens
    return input_tokens, output_tokens, total_tokens, float(
        info.get("duration_seconds", 0) or 0
    )


def _condition_metrics(
    store: RunBundleStore, conditions: tuple[Condition, ...]
) -> list[dict[str, Any]]:
    rows = []
    for condition in conditions:
        directory = store.condition_dir(condition.candidate_hash, condition.condition_id)
        calls = [_load_json(path) for path in sorted((directory / "lean/calls").glob("*.json"))]
        compiles = [
            _load_json(path)
            for path in sorted((directory / "lean/compiler_attempts").glob("*/result.json"))
        ]
        timing_path = directory / "timing.json"
        lean_result_path = directory / "lean/result.json"
        result_path = directory / "result.json"
        input_tokens = output_tokens = total_tokens = 0
        llm_seconds = 0.0
        for call in calls:
            values = _usage(call)
            input_tokens += values[0]
            output_tokens += values[1]
            total_tokens += values[2]
            llm_seconds += values[3]
        rows.append(
            {
                "condition_id": condition.condition_id,
                "condition_kind": condition.kind.value,
                "required": condition.required,
                "active": condition.query is not None
                or condition.kind
                in {ConditionKind.RADIAL_UNBOUNDED, ConditionKind.DISCRETE_INDUCTIVE},
                "timing": _load_json(timing_path) if timing_path.exists() else None,
                "formal_result": _load_json(result_path) if result_path.exists() else None,
                "lean_result": (
                    _load_json(lean_result_path) if lean_result_path.exists() else None
                ),
                "proof_agent_calls": sum(call.get("status") == "completed" for call in calls),
                "proof_agent_failed_calls": sum(call.get("status") == "failed" for call in calls),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "llm_service_seconds_sum": llm_seconds,
                "lean_compile_calls": sum(
                    item.get("status") == "completed" for item in compiles
                ),
                "lean_compile_seconds_sum": sum(
                    float(item.get("duration_seconds", 0) or 0) for item in compiles
                ),
            }
        )
    return rows


def _problem_class(task_type: str) -> str:
    return {
        "stability": "P1_stability",
        "roa": "P2_roa",
        "invariant": "P3_invariant",
        "safety": "P4_safety",
    }[task_type]


def _run_case(
    output: Path,
    experiment: dict[str, Any],
    summary_row: dict[str, Any],
    *,
    budget_seconds: float,
) -> dict[str, Any]:
    problem, candidate, conditions, audit = _load_fixed_case(summary_row)
    run_id = "run-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    store = RunBundleStore(
        output,
        problem_class=_problem_class(problem.task_type.value),
        record_id=summary_row["record_id"],
        run_id=run_id,
    )
    strategy = experiment["strategy"]
    timeouts = experiment["timeouts"]
    store.initialize(
        experiment=experiment,
        manifest={
            "schema_version": RunBundleStore.schema_version,
            "experiment_id": experiment["experiment_id"],
            "record_id": summary_row["record_id"],
            "problem_id": problem.problem_id,
            "problem_class": _problem_class(problem.task_type.value),
            "dynamics_kind": (
                "indexed_family"
                if problem.indexed_family is not None
                else problem.system.kind.value
            ),
            "dimension": (
                {
                    "kind": "symbolic",
                    "expression": problem.indexed_family.state_dimension,
                    "parameter": problem.indexed_family.parameter.name,
                }
                if problem.indexed_family is not None
                else len(problem.system.state_vars)
            ),
            "run_id": run_id,
            "started_at_utc": _utc_now(),
            "source_path": audit["source_run_path"],
            "provider": PROVIDER,
            "model": MODEL,
            "strategy": strategy,
            "timeouts": timeouts,
            "fixed_condition_audit": audit,
            **_git_metadata(),
        },
        source_record={"source_summary_row": summary_row, "fixed_condition_audit": audit},
        problem=problem,
    )
    digest = content_hash(candidate)
    store.register_candidate(digest, 0)
    store.write_json("lineage", f"00-{digest}", {
        "candidate_hash": digest,
        "structure_index": 0,
        "parent_hash": None,
        "source": "fixed RQ1 certificate",
    })

    compiler = FreshRecordingLeanCompiler(CURRENT / "formalization" / "lean", store)
    if isinstance(candidate, FamilyCandidateSpec):
        condition_deadline = RunDeadline(
            budget_seconds + DEFAULT_FINALIZATION_RESERVE_SECONDS
        )
        lean_runner = LeanProofRunner(compiler, deadline=condition_deadline)
        standard_provider = _proof_provider(store, condition_deadline)
        premises_condition = next(
            item
            for item in conditions
            if item.condition_id == "indexed_family:lyapunov_premises"
        )

        def family_provider(family_problem, family_candidate, locked):
            return standard_provider(
                family_problem,
                family_candidate,
                premises_condition,
                locked,
                "direct_lean",
            )

        verifier: FixedAllLeanVerifier | FamilyCandidateVerifier = FamilyCandidateVerifier(
            locked_theorem_factory=(
                lambda family_problem, family_candidate, _digest: (
                    generate_family_locked_theorem(family_problem, family_candidate)
                )
            ),
            lean_runner=lean_runner,
            proof_agent_provider=family_provider,
            artifact_store=store,
            deadline=condition_deadline,
        )
    else:
        verifier = FixedAllLeanVerifier(
            solver_runner=None,
            lean_runner=LeanProofRunner(compiler, deadline=None),
            verification_router_provider=_direct_lean_router,

            proof_agent_provider=_proof_provider(
                store,
                RunDeadline(budget_seconds + DEFAULT_FINALIZATION_RESERVE_SECONDS),
            ),
            common_core_audited=True,
            kernel_first=False,
            artifact_store=store,
            deadline=None,
            condition_budget_seconds=budget_seconds,
        )

    verification_started_at = _utc_now()
    started = time.monotonic()
    verdict: CandidateVerdict | None = None
    errors: list[str] = []
    status = "unresolved"
    try:
        if isinstance(candidate, FamilyCandidateSpec):
            assert isinstance(verifier, FamilyCandidateVerifier)
            verdict = verifier.verify(problem, candidate)
        else:
            assert isinstance(verifier, FixedAllLeanVerifier)
            verdict = verifier.verify_fixed(problem, candidate, conditions)
        status = verdict.status.value
    except RunDeadlineExceeded as error:
        status = "timed_out"
        errors.append(str(error))
    except Exception as error:
        status = "infrastructure_error"
        errors.append(f"{type(error).__name__}: {error}")
    verification_wall_seconds = time.monotonic() - started


    charged_wall_seconds = verification_wall_seconds

    metrics = store.metrics()
    condition_rows = _condition_metrics(store, conditions)
    record = {
        "schema_version": "dynacert-rq2-all-lean-certificate.v1",
        "record_id": summary_row["record_id"],
        "problem_class": _problem_class(problem.task_type.value),
        "certificate_class": audit["certificate_class"],
        "candidate_hash": digest,
        "status": status,
        "verdict_status": None if verdict is None else verdict.status.value,
        "verified": status == "verified",
        "verification_started_at_utc": verification_started_at,
        "verification_wall_seconds": verification_wall_seconds,
        "charged_wall_seconds": charged_wall_seconds,
        "budget_seconds": budget_seconds,
        "budget_scope": "per_active_lean_obligation",
        "active_obligations": audit["active_obligation_count"],
        "lean_assigned_obligations": audit["active_obligation_count"],
        "lean_usage_percent": 100.0,
        "proof_agent_calls": metrics["llm"]["calls"],
        "proof_agent_failed_calls": metrics["llm"]["failed_calls"],
        "input_tokens": metrics["llm"]["input_tokens"],
        "output_tokens": metrics["llm"]["output_tokens"],
        "total_tokens": metrics["llm"]["total_tokens"],
        "llm_service_seconds_sum": metrics["llm"]["call_seconds_sum"],
        "lean_compile_calls": metrics["lean"]["compile_calls"],
        "lean_compile_seconds_sum": metrics["lean"]["compile_seconds_sum"],
        "solver_calls": metrics["solvers"]["calls"],
        "router_llm_calls": 0,
        "generated_module_cache": False,
        "saved_proof_replay": False,
        "condition_schedule": {
            "parallel": audit["parallel_condition_ids"],
            "sequential": audit["sequential_condition_ids"],
            "static": audit["static_condition_ids"],
            "closing": audit["closing_condition_id"],
        },
        "conditions": condition_rows,
        "errors": errors,
        "run_path": str(store.root),
    }
    store.write_json("fixed_replay", "metrics", record)
    store.finalize(
        status=status,
        result={
            "candidates": [candidate.model_dump(mode="json")],
            "verdict": None if verdict is None else verdict.model_dump(mode="json"),
            "fixed_replay": record,
        },
        errors=errors,
    )
    return record


def _existing_records(output: Path) -> dict[str, dict[str, Any]]:
    found = {}
    for path in output.glob("runs/*/*/*/fixed_replay/metrics.json"):
        try:
            record = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if _infrastructure_invalid(record):
            continue
        found[record["record_id"]] = record
    return found


def _infrastructure_invalid(record: dict[str, Any]) -> bool:


    if record.get("verified"):
        return False
    for condition in record.get("conditions", []):
        lean_result = condition.get("lean_result") or {}
        reason = str(lean_result.get("blocking_reason") or "").lower()
        if "lean agent call failed" in reason and any(
            marker in reason
            for marker in (
                "http 400",
                "http 429",
                "http 500",
                "http 502",
                "http 503",
                "http 504",
                "connection",
                "upstream",
            )
        ):
            return True


    run_path = record.get("run_path")
    if run_path:
        condition_root = Path(run_path) / "candidates" / "00" / "conditions"
        for directory in condition_root.glob("*"):
            timing_path = directory / "timing.json"
            if not timing_path.exists():
                continue
            try:
                timing = _load_json(timing_path)
            except (OSError, json.JSONDecodeError):
                continue
            if timing.get("passed") is not False:
                continue
            for call_path in (directory / "lean" / "calls").glob("*.json"):
                try:
                    call = _load_json(call_path)
                except (OSError, json.JSONDecodeError):
                    continue
                attempts = int((call.get("call_info") or {}).get("attempts", 1) or 1)
                if attempts > 1:
                    return True
    return False


def _group_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "certificate_count": 0,
            "verified": 0,
            "status_counts": {},
            "average_charged_wall_seconds": None,
            "proof_agent_calls": 0,
            "total_tokens": 0,
        }
    return {
        "certificate_count": len(records),
        "verified": sum(item["verified"] for item in records),
        "status_counts": dict(Counter(item["status"] for item in records)),
        "average_charged_wall_seconds": mean(
            float(item["charged_wall_seconds"]) for item in records
        ),
        "average_observed_wall_seconds": mean(
            float(item["verification_wall_seconds"]) for item in records
        ),
        "active_obligations": sum(item["active_obligations"] for item in records),
        "lean_assigned_obligations": sum(
            item["lean_assigned_obligations"] for item in records
        ),
        "lean_usage_percent": 100.0,
        "proof_agent_calls": sum(item["proof_agent_calls"] for item in records),
        "proof_agent_failed_calls": sum(
            item["proof_agent_failed_calls"] for item in records
        ),
        "input_tokens": sum(item["input_tokens"] for item in records),
        "output_tokens": sum(item["output_tokens"] for item in records),
        "total_tokens": sum(item["total_tokens"] for item in records),
        "llm_service_seconds_sum": sum(
            item["llm_service_seconds_sum"] for item in records
        ),
        "lean_compile_calls": sum(item["lean_compile_calls"] for item in records),
        "lean_compile_seconds_sum": sum(
            item["lean_compile_seconds_sum"] for item in records
        ),
    }


def _aggregate(records: list[dict[str, Any]], expected: int) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["certificate_class"]].append(record)
        groups[record["problem_class"]].append(record)
    return {
        "schema_version": "dynacert-rq2-all-lean-summary.v1",
        "strategy": "All-Lean",
        "expected_certificate_count": expected,
        "completed_certificate_count": len(records),
        "complete": len(records) == expected,
        "overall": _group_summary(records),
        "by_certificate_class": {
            name: _group_summary(groups.get(name, []))
            for name in ("polynomial", "non_polynomial")
        },
        "by_problem_class": {
            name: _group_summary(groups.get(name, []))
            for name in ("P1_stability", "P2_roa", "P3_invariant", "P4_safety")
        },
        "records": sorted(records, key=lambda item: item["record_id"]),
        "updated_at_utc": _utc_now(),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-experiment", type=Path, default=DEFAULT_SOURCE_EXPERIMENT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget-seconds", type=float, default=DEFAULT_BUDGET_SECONDS)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--record-id", action="append", default=[])
    parser.add_argument(
        "--defer-record-id",
        action="append",
        default=[],
        help="process these selected records last without changing the experiment manifest",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--expected-certificates",
        type=int,
        default=EXPECTED_CERTIFICATES,
        help="optional guard on the number of verified source certificates",
    )
    return parser


def _resume_comparable(experiment: dict[str, Any]) -> dict[str, Any]:
    comparable = {
        key: value
        for key, value in experiment.items()
        if key not in RESUME_MUTABLE_KEYS and key != "resume_history"
    }
    comparable["strategy"] = {
        key: value
        for key, value in (experiment.get("strategy") or {}).items()
        if key not in RESUME_MUTABLE_STRATEGY_KEYS
    }
    return comparable


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not API_KEY or API_KEY.startswith("<REDACTED>"):
        raise RuntimeError("API key is not configured")
    if args.budget_seconds <= 0:
        raise SystemExit("--budget-seconds must be positive")
    if args.workers <= 0:
        raise SystemExit("--workers must be positive")
    source = args.source_experiment.resolve()
    output = args.output.resolve()
    source_lean_configuration = _assert_source_lean_configuration(
        source,
        budget_seconds=float(args.budget_seconds),
    )
    source_summary = source / ("full.json" if (source / "full.json").exists() else "summary.json")
    rows = [item for item in _load_json(source_summary) if item.get("status") == "verified"]
    rows.sort(key=lambda item: item["record_id"])
    if args.record_id:
        requested = set(args.record_id)
        rows = [item for item in rows if item["record_id"] in requested]
        missing = requested - {item["record_id"] for item in rows}
        if missing:
            raise SystemExit(f"unknown verified fixed records: {sorted(missing)}")
    if args.limit is not None:
        if args.limit <= 0:
            raise SystemExit("--limit must be positive")
        rows = rows[: args.limit]
    if (
        args.expected_certificates is not None
        and not args.record_id
        and args.limit is None
        and len(rows) != args.expected_certificates
    ):
        raise RuntimeError(
            f"expected {args.expected_certificates} final RQ1 certificates, found {len(rows)}"
        )

    experiment = {
        "schema_version": "dynacert-fixed-all-lean-experiment.v1",
        "experiment_id": output.name,
        "source_experiment": str(source),
        "source_summary_sha256": _sha256(source_summary),
        "record_ids": [item["record_id"] for item in rows],
        "provider": PROVIDER,
        "model": MODEL,
        "source_rq1_lean_configuration": source_lean_configuration,
        "strategy": {
            "policy": "all_lean_fixed_certificate",
            "candidate_synthesis": False,
            "router_llm": False,
            "solver": False,
            "all_active_obligations_direct_lean": True,
            "parallel_independent_obligations": False,
            "sequential_active_obligations": True,
            "sequential_rounds_within_condition": True,
            "kernel_first": False,
            "contextual_local_repair": False,
            "saved_proof_replay": False,
            "generated_module_cache": False,
            "parallel_fixed_certificates": True,
            "fixed_certificate_workers": int(args.workers),
            "contextual_local_repair": False,
            "kernel_first": False,
            "json_format_repairs": MAX_FORMAT_REPAIRS,
            "lean_proof_rounds": MAX_PROOF_ROUNDS,
            "lean_name_repair_rounds": MAX_NAME_REPAIR_ROUNDS,
        },
        "timeouts": {
            "fixed_candidate_verification_seconds": None,
            "finalization_reserve_seconds": DEFAULT_FINALIZATION_RESERVE_SECONDS,
            "lean_llm_call_seconds": ROLE_PARAMS["lean"]["call_timeout_seconds"],
            "lean_condition_seconds": float(args.budget_seconds),
        },
        "cost_metrics": {
            "primary": "per-certificate verification wall-clock",
            "secondary": "proof-agent calls/tokens and summed service time",
        },
    }
    existing_experiment = output / "experiment.json"
    if existing_experiment.exists():
        previous = _load_json(existing_experiment)
        if _resume_comparable(previous) != _resume_comparable(experiment):
            raise SystemExit(f"experiment configuration mismatch: {existing_experiment}")
        if not args.resume:
            raise SystemExit(f"output already exists; use --resume: {output}")
        if previous != {**experiment, "resume_history": previous.get("resume_history")}:
            history = list(previous.get("resume_history") or [])
            history.append(
                {
                    "resumed_at_utc": _utc_now(),
                    "previous_record_ids": previous.get("record_ids"),
                    "previous_source_summary_sha256": previous.get(
                        "source_summary_sha256"
                    ),
                    "previous_workers": (previous.get("strategy") or {}).get(
                        "fixed_certificate_workers"
                    ),
                }
            )
            _atomic_json(existing_experiment, {**experiment, "resume_history": history})

        experiment = _load_json(existing_experiment)
    elif output.exists() and any(output.iterdir()):
        raise SystemExit(f"non-empty output has no matching experiment manifest: {output}")

    deferred = set(args.defer_record_id)
    missing_deferred = deferred - {item["record_id"] for item in rows}
    if missing_deferred:
        raise SystemExit(f"unknown deferred records: {sorted(missing_deferred)}")
    execution_rows = [item for item in rows if item["record_id"] not in deferred]
    execution_rows.extend(item for item in rows if item["record_id"] in deferred)

    completed = _existing_records(output) if args.resume else {}
    records = [completed[item["record_id"]] for item in rows if item["record_id"] in completed]
    expected = len(rows)
    _atomic_json(output / "aggregate.partial.json", _aggregate(records, expected))
    pending_rows = [
        (index, row)
        for index, row in enumerate(execution_rows, start=1)
        if row["record_id"] not in completed
    ]

    def run_record(index: int, row: dict[str, Any]) -> tuple[int, str, dict[str, Any]]:
        record_id = str(row["record_id"])
        print(f"[{index}/{expected}] {record_id} starting", flush=True)
        record = _run_case(
            output,
            experiment,
            row,
            budget_seconds=float(args.budget_seconds),
        )
        return index, record_id, record

    infrastructure_invalid = False
    with ThreadPoolExecutor(max_workers=int(args.workers)) as executor:
        futures = {
            executor.submit(run_record, index, row): (index, row)
            for index, row in pending_rows
        }
        for future in as_completed(futures):
            index, record_id, record = future.result()
            completed[record_id] = record
            records = [
                completed[item["record_id"]]
                for item in rows
                if item["record_id"] in completed
            ]
            _atomic_json(output / "aggregate.partial.json", _aggregate(records, expected))
            if _infrastructure_invalid(record):
                infrastructure_invalid = True
                print(
                    f"[{index}/{expected}] {record_id} infrastructure-invalid",
                    flush=True,
                )
            else:
                print(
                    f"[{index}/{expected}] {record_id} status={record['status']} "
                    f"wall={record['verification_wall_seconds']:.2f}s "
                    f"calls={record['proof_agent_calls']} tokens={record['total_tokens']}",
                    flush=True,
                )

    if infrastructure_invalid:
        print("one or more records were infrastructure-invalid; resume after repair", flush=True)
        return 75

    aggregate = _aggregate(
        [completed[item["record_id"]] for item in rows], expected
    )
    _atomic_json(output / "aggregate.json", aggregate)
    print(json.dumps(aggregate["overall"], ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
