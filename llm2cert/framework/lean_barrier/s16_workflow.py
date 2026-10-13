"""Verify certificate obligations with SMT and Lean."""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction

from .s15_artifacts import ArtifactStore, RunBundleStore
from .s13_runtime import DEFAULT_FINALIZATION_RESERVE_SECONDS, RunDeadline
from .s08_fastcheck import run_fast_check
from .s10_lean_backend import (
    LeanProofRunner,
    LockedTheorem,
    ProofAgent,
    generate_locked_theorem,
    kernel_first_candidate,
)
from .s01_models import (
    Backend,
    BackendProfile,
    CandidateSpec,
    CandidateStatus,
    CandidateVerdict,
    CertificationLevel,
    CounterexampleEvidence,
    EvidenceLevel,
    LeanAgentOutput,
    LeanAgentStatus,
    LeanResult,
    Condition,
    ConditionKind,
    ConditionOutcome,
    ProblemSpec,
    ReplayStatus,
    RoutingDecision,
    SolverStatus,
    VerificationScope,
    VerificationRouterDecision,
    VerificationRoute,
    Witness,
)
from .tasks import verify_plan
from .s14_replay import interval_replay_witness, replay_witness
from .s09_router import (
    capability_summary,
    default_solver_order,
    resolve_verification_routing,
)
from .s04_semantics import build_conditions
from .s12_smt_backend import DREAL_DELTA, SolverRunner

VerificationRouterProvider = Callable[
    [Condition, dict[str, object]], VerificationRouterDecision | None
]
ProofAgentProvider = Callable[
    [ProblemSpec, CandidateSpec, Condition, LockedTheorem, str], ProofAgent
]


def _replayable_witness(witness: Witness | None) -> Witness | None:


    if witness is None or witness.point is not None or witness.box is None:
        return witness
    point: dict[str, str] = {}
    for name, interval in witness.box.items():
        midpoint = (Fraction(interval.lower) + Fraction(interval.upper)) / 2
        point[name] = str(midpoint)
    return Witness(point=point)


def _normalize_agent_counterexample(
    variables: tuple[str, ...], point: dict[str, str]
) -> dict[str, str]:


    if set(point) == set(variables):
        return point
    indexed: dict[int, str] = {}
    for name, value in point.items():
        match = re.fullmatch(r"x_?(\d+)", name)
        if match is None:
            return point
        indexed[int(match.group(1))] = value
    dimension = len(variables)
    if set(indexed) == set(range(dimension)):
        return {name: indexed[index] for index, name in enumerate(variables)}
    if set(indexed) == set(range(1, dimension + 1)):
        return {name: indexed[index + 1] for index, name in enumerate(variables)}
    return point


@dataclass(frozen=True)
class FormalOutcome:
    passed: bool
    source: str
    detail: str
    counterexample: CounterexampleEvidence | None = None
    unresolved: bool = False
    pause_search: bool = False


class CandidateVerifier:
    def __init__(
        self,
        *,
        solver_runner: SolverRunner | None,
        lean_runner: LeanProofRunner | None,
        verification_router_provider: VerificationRouterProvider,
        proof_agent_provider: ProofAgentProvider,
        common_core_audited: bool,
        kernel_first: bool = False,
        artifact_store: ArtifactStore | None = None,
        deadline: RunDeadline | None = None,
        smt_only: bool = False,
        lean_only: bool = False,
    ) -> None:
        if smt_only and lean_only:
            raise ValueError("smt_only and lean_only are mutually exclusive")
        self.solver_runner = solver_runner
        self.lean_runner = lean_runner
        self.verification_router_provider = verification_router_provider
        self.proof_agent_provider = proof_agent_provider
        self.common_core_audited = common_core_audited
        self.kernel_first = kernel_first
        self.store = artifact_store
        self.deadline = deadline
        self.smt_only = smt_only
        self.lean_only = lean_only

    def _try_kernel_first(
        self,
        problem: ProblemSpec,
        condition: Condition,
        locked: LockedTheorem,
    ) -> LeanResult | None:
        candidate = kernel_first_candidate(
            locked,
            condition.kind,
            len(problem.system.state_vars),


            polynomial_goal=(
                condition.query is None
                or capability_summary(condition).polynomial_nra
            ),
        )
        if candidate is None:
            return None
        tactic_name, output = candidate
        started = time.monotonic()
        result = self.lean_runner.compile_once(
            condition.condition_id,
            locked,
            output,
            note=tactic_name,
            origin="kernel-first tactic",
            timeout_seconds=20.0,
        )
        if self.store:
            payload = {
                    "schema_version": "lean-barrier.kernel-first.v1",
                    "condition_id": condition.condition_id,
                    "candidate_hash": locked.candidate_hash,
                    "statement_hash": locked.statement_hash,
                    "tactic": tactic_name,
                    "compiled_and_audited": result is not None,
                    "duration_seconds": time.monotonic() - started,
                }
            if isinstance(self.store, RunBundleStore):
                self.store.write_condition_json(
                    condition.candidate_hash,
                    condition.condition_id,
                    "lean/kernel_first",
                    payload,
                )
            else:
                self.store.write_json(
                    "lean",
                    condition.condition_id.replace(":", "_") + "-kernel-first",
                    payload,
                )
        return result

    def _lean(
        self,
        problem: ProblemSpec,
        candidate: CandidateSpec,
        condition: Condition,
        mode: str,
    ) -> FormalOutcome:
        if self.lean_runner is None:
            return FormalOutcome(False, "unresolved", "Lean runner unavailable", unresolved=True)
        locked = generate_locked_theorem(problem, candidate, condition)
        if isinstance(self.store, RunBundleStore):
            self.store.write_condition_json(
                condition.candidate_hash,
                condition.condition_id,
                "lean/status",
                {"status": "running", "started_at": time.time()},
            )
        definitions_ok, definition_diagnostics = (
            self.lean_runner.preflight_locked_definitions(locked)
        )
        if not definitions_ok:
            return FormalOutcome(
                False,
                "unresolved",
                "AST-to-Lean locked definition preflight failed:\n"
                + definition_diagnostics,
                unresolved=True,
            )
        result = (
            self._try_kernel_first(problem, condition, locked)
            if self.kernel_first
            else None
        )
        kernel_first = result is not None
        if result is None:
            agent = self.proof_agent_provider(
                problem, candidate, condition, locked, mode
            )
            checker: Callable[[dict[str, str]], tuple[bool, str]] | None = None
            if condition.query is not None:
                query = condition.query

                def confirm_counterexample(point: dict[str, str]) -> tuple[bool, str]:
                    normalized = _normalize_agent_counterexample(query.variables, point)
                    try:
                        replay = replay_witness(query, Witness(point=normalized))
                    except (KeyError, TypeError, ValueError) as error:
                        return False, f"counterexample could not be replayed: {error}"
                    detail = (
                        f"replay={replay.status.value} residual={replay.residual} "
                        f"{replay.reason}".strip()
                    )
                    return replay.status == ReplayStatus.CONFIRMED, detail

                checker = confirm_counterexample

            result = self.lean_runner.run(
                condition.condition_id, locked, agent, counterexample_checker=checker
            )
        if self.store:
            if isinstance(self.store, RunBundleStore):
                self.store.write_condition_json(
                    condition.candidate_hash, condition.condition_id, "lean/result", result
                )
                self.store.write_condition_text(
                    condition.candidate_hash,
                    condition.condition_id,
                    "lean/locked_statement",
                    locked.statement,
                    ".lean",
                )
                self.store.write_condition_text(
                    condition.candidate_hash,
                    condition.condition_id,
                    "lean/locked_source",
                    f"{locked.definitions}\n\n{locked.statement}\n",
                    ".lean",
                )
            else:
                self.store.write_json("lean", condition.condition_id.replace(":", "_"), result)
                self.store.write_text(
                    "lean",
                    condition.condition_id.replace(":", "_") + "-statement",
                    locked.statement,
                    ".lean.txt",
                )
                self.store.write_text(
                    "lean",
                    condition.condition_id.replace(":", "_") + "-locked",
                    f"{locked.definitions}\n\n{locked.statement}\n",
                    ".lean.txt",
                )
        accepted = (
            result.status == LeanAgentStatus.CANDIDATE_PROOF
            and result.compiled
            and result.audit_passed
        )
        if accepted:
            if kernel_first:
                detail = "Lean kernel proof accepted (compiler-first generic tactic)"
            else:
                detail = "Lean kernel proof accepted"
            return FormalOutcome(True, "lean", detail)
        return FormalOutcome(
            False,
            "unresolved",
            result.blocking_reason or "Lean failed",
            unresolved=True,
        )


    def _route(self, condition: Condition) -> RoutingDecision:
        capabilities = capability_summary(condition)
        try:
            decision = self.verification_router_provider(condition, capabilities.as_dict())
        except Exception:
            decision = None
        resolved = resolve_verification_routing(condition, decision)
        if self.store:
            if isinstance(self.store, RunBundleStore):
                self.store.write_condition_json(
                    condition.candidate_hash, condition.condition_id, "routing", resolved
                )
            else:
                self.store.write_json(
                    "routing", condition.condition_id.replace(":", "_"), resolved
                )
        return resolved

    def _run_solvers(
        self,
        condition: Condition,
        solver_order: tuple,
        *,
        dreal_positive_allowed: bool = True,
    ) -> FormalOutcome | None:
        runner = self.solver_runner
        if runner is None or not solver_order:
            return None
        with ThreadPoolExecutor(max_workers=len(solver_order)) as pool:
            if isinstance(self.store, RunBundleStore):
                for backend in solver_order:
                    self.store.write_condition_json(
                        condition.candidate_hash,
                        condition.condition_id,
                        f"solver/{backend.value}",
                        {"status": "running", "backend": backend.value},
                    )
            raw_results = list(
                pool.map(lambda backend: runner.run(condition, backend), solver_order)
            )
        for backend, result in zip(solver_order, raw_results, strict=True):
            if result.status in (SolverStatus.SAT, SolverStatus.DELTA_SAT):
                assert condition.query is not None
                replay_witness_value = _replayable_witness(result.witness)
                high_precision = replay_witness(condition.query, replay_witness_value)
                interval = interval_replay_witness(condition.query, replay_witness_value)
                if (
                    interval.status != ReplayStatus.CONFIRMED
                    and result.status == SolverStatus.DELTA_SAT
                ):
                    interval = interval_replay_witness(
                        condition.query,
                        replay_witness_value,
                        equality_tolerance=DREAL_DELTA,
                    )
                result = result.model_copy(
                    update={
                        "witness": replay_witness_value or result.witness,
                        "replay_status": interval.status,
                        "replay_residual": (
                            f"high_precision={high_precision.residual}; "
                            f"interval={interval.residual}"
                        ),
                    }
                )
            if self.store:
                if isinstance(self.store, RunBundleStore):
                    self.store.write_condition_json(
                        condition.candidate_hash,
                        condition.condition_id,
                        f"solver/{backend.value}",
                        result,
                    )
                else:
                    self.store.write_json(
                        "solvers",
                        f"{condition.condition_id.replace(':', '_')}-{backend.value}",
                        result,
                    )
            if result.status == SolverStatus.UNSAT and runner.formal:
                if backend == Backend.DREAL and not dreal_positive_allowed:
                    continue
                detail = f"{backend.value} returned unsat"
                if condition.query is not None and condition.query.formal_bounds is None:
                    detail = f"unbounded polynomial SMT: {detail}"
                return FormalOutcome(True, "solver", detail)
            if (
                result.status in (SolverStatus.SAT, SolverStatus.DELTA_SAT)
                and result.replay_status == ReplayStatus.CONFIRMED
                and result.witness is not None
            ):
                level = (
                    EvidenceLevel.EXACT_MODEL_REPLAY
                    if result.status == SolverStatus.SAT and result.witness.point is not None
                    else EvidenceLevel.INTERVAL_VALIDATED
                )
                evidence = CounterexampleEvidence(
                    condition_id=condition.condition_id,
                    source=backend.value,
                    level=level,
                    witness=result.witness,
                    residual=result.replay_residual or "",
                )
                return FormalOutcome(
                    False,
                    "counterexample",
                    f"{backend.value} {result.status.value} witness independently replayed",
                    counterexample=evidence,
                )
        return None


    def _verify_condition(
        self,
        problem: ProblemSpec,
        candidate: CandidateSpec,
        condition: Condition,
        *,
        dreal_positive_allowed: bool = True,
    ) -> FormalOutcome:
        started_at_utc = datetime.now(UTC).isoformat()
        started_monotonic = time.monotonic()
        status = "raised"
        try:
            outcome = self._verify_condition_untimed(
                problem,
                candidate,
                condition,
                dreal_positive_allowed=dreal_positive_allowed,
            )
            status = "passed" if outcome.passed else outcome.source
            return outcome
        finally:
            self._write_condition_timing(
                condition,
                execution_kind="formal",
                started_at_utc=started_at_utc,
                started_monotonic=started_monotonic,
                status=status,
            )

    def _verify_condition_untimed(
        self,
        problem: ProblemSpec,
        candidate: CandidateSpec,
        condition: Condition,
        *,
        dreal_positive_allowed: bool = True,
    ) -> FormalOutcome:
        if self.deadline is not None:
            self.deadline.check(
                reserve_seconds=DEFAULT_FINALIZATION_RESERVE_SECONDS
            )
        scope = (
            self.store.scope(
                candidate_hash=condition.candidate_hash,
                condition_id=condition.condition_id,
                stage="condition",
            )
            if isinstance(self.store, RunBundleStore)
            else nullcontext()
        )
        with scope:
            if isinstance(self.store, RunBundleStore):
                self.store.write_condition_json(
                    condition.candidate_hash,
                    condition.condition_id,
                    "result",
                    {"status": "running"},
                )
            if self.lean_only:
                outcome = self._lean(problem, candidate, condition, "direct")
            elif self.smt_only:
                decision = (
                    None
                    if condition.kind == ConditionKind.RADIAL_UNBOUNDED
                    else self._route(condition)
                )
                eligible = capability_summary(condition).eligible_backends
                if not eligible:
                    outcome = FormalOutcome(
                        False,
                        "unresolved",
                        "SMT-only: no eligible SMT backend",
                        unresolved=True,
                    )
                else:
                    solver_order = (
                        decision.solver_order
                        if decision is not None and decision.solver_order
                        else default_solver_order(eligible)
                    )
                    solver_out = self._run_solvers(
                        condition,
                        solver_order,
                        dreal_positive_allowed=dreal_positive_allowed,
                    )
                    outcome = solver_out or FormalOutcome(
                        False,
                        "unresolved",
                        "SMT-only: solvers inconclusive",
                        unresolved=True,
                    )
            elif condition.kind == ConditionKind.RADIAL_UNBOUNDED:
                outcome = self._lean(problem, candidate, condition, "direct")
            else:
                decision = self._route(condition)
                if decision.route == VerificationRoute.DIRECT_LEAN:
                    outcome = self._lean(problem, candidate, condition, "direct")
                else:
                    solver_out = self._run_solvers(
                        condition,
                        decision.solver_order,
                        dreal_positive_allowed=dreal_positive_allowed,
                    )
                    outcome = (
                        solver_out
                        if solver_out is not None
                        else self._lean(problem, candidate, condition, "rescue")
                    )
            if isinstance(self.store, RunBundleStore):
                self.store.write_condition_json(
                    condition.candidate_hash,
                    condition.condition_id,
                    "result",
                    outcome,
                )
            return outcome

    def _write_condition_timing(
        self,
        condition: Condition,
        *,
        execution_kind: str,
        started_at_utc: str,
        started_monotonic: float,
        status: str,
    ) -> None:
        if not isinstance(self.store, RunBundleStore):
            return
        self.store.write_condition_json(
            condition.candidate_hash,
            condition.condition_id,
            "timing",
            {
                "schema_version": "dynacert-condition-timing.v1",
                "condition_id": condition.condition_id,
                "execution_kind": execution_kind,
                "status": status,
                "started_at_utc": started_at_utc,
                "finished_at_utc": datetime.now(UTC).isoformat(),
                "duration_seconds": time.monotonic() - started_monotonic,
            },
        )

    def _human(
        self,
        problem: ProblemSpec,
        candidate_hash: str,
        outcomes: list[ConditionOutcome],
        reason: str,
    ) -> CandidateVerdict:
        unresolved = [outcome.condition_id for outcome in outcomes if not outcome.passed]
        report_path: str | None = None
        if self.store:
            report = self.store.human_review_report(
                problem_id=problem.problem_id,
                candidate_hash=candidate_hash,
                reason=reason,
                unresolved=unresolved,
            )
            report_path = str(report)
        return self._record_verdict(
            CandidateVerdict(
                candidate_hash=candidate_hash,
                status=CandidateStatus.NEEDS_HUMAN_REVIEW,
                outcomes=tuple(outcomes),
                human_report_path=report_path,
            )
        )

    def _record_verdict(self, verdict: CandidateVerdict) -> CandidateVerdict:
        if self.store:
            self.store.write_json("verdict", verdict.candidate_hash, verdict)
        return verdict


    def _apply_formal(
        self,
        problem: ProblemSpec,
        digest: str,
        outcomes: list[ConditionOutcome],
        result: FormalOutcome,
    ) -> CandidateVerdict | None:
        if result.counterexample:
            return self._record_verdict(
                CandidateVerdict(
                    candidate_hash=digest,
                    status=CandidateStatus.REJECTED,
                    outcomes=tuple(outcomes),
                    counterexample=result.counterexample,
                    counterexamples=(result.counterexample,),
                )
            )
        if result.pause_search:
            return self._human(problem, digest, outcomes, result.detail)
        if result.unresolved:
            return self._record_verdict(
                CandidateVerdict(
                    candidate_hash=digest,
                    status=CandidateStatus.UNRESOLVED,
                    outcomes=tuple(outcomes),
                )
            )
        return None

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
        if not items:
            return None
        if len(items) > 1:
            with ThreadPoolExecutor(max_workers=len(items)) as pool:
                results = list(
                    pool.map(
                        lambda item: self._verify_condition(
                            problem,
                            candidate,
                            item,
                            dreal_positive_allowed=allow_dreal,
                        ),
                        items,
                    )
                )
        else:
            results = [
                self._verify_condition(
                    problem,
                    candidate,
                    item,
                    dreal_positive_allowed=allow_dreal,
                )
                for item in items
            ]
        for condition, result in zip(items, results, strict=True):
            outcomes.append(
                ConditionOutcome(
                    condition_id=condition.condition_id,
                    passed=result.passed,
                    source=result.source,
                    detail=result.detail,
                )
            )
            decided = self._apply_formal(problem, digest, outcomes, result)
            if decided is not None:
                return decided
            active_formal_sources.append(result.source)
        return None


    def verify(self, problem: ProblemSpec, candidate: CandidateSpec) -> CandidateVerdict:
        if problem.indexed_family is not None:
            raise ValueError(
                "indexed-family problems must use BarrierPipeline's direct family Lean route"
            )
        conditions = build_conditions(problem, candidate)
        digest = conditions[0].candidate_hash
        if self.store:
            self.store.write_json("candidates", digest, candidate)
            if isinstance(self.store, RunBundleStore):
                for condition in conditions:
                    self.store.write_condition_json(
                        digest,
                        condition.condition_id,
                        "condition",
                        condition,
                    )
                self.store.write_json(
                    "fastcheck",
                    digest,
                    {"status": "running", "candidate_hash": digest},
                )
        fast = run_fast_check(problem, candidate, conditions)
        if self.store:
            self.store.write_json("fastcheck", digest, fast)
        if fast.rejected:
            return self._record_verdict(
                CandidateVerdict(
                    candidate_hash=digest,
                    status=CandidateStatus.REJECTED,
                    counterexample=fast.evidence,
                    counterexamples=fast.evidence_list,
                )
            )

        plan = verify_plan(problem, conditions)
        outcomes: list[ConditionOutcome] = []
        active_formal_sources: list[str] = []
        allow_dreal = plan.dreal_positive_allowed

        for condition in plan.static:
            static_started_at_utc = datetime.now(UTC).isoformat()
            static_started_monotonic = time.monotonic()
            if not self.common_core_audited:
                static_outcome = ConditionOutcome(
                    condition_id=condition.condition_id,
                    passed=False,
                    source="unresolved",
                    detail="common Lean DSL core has not passed its formal audit",
                )
                outcomes.append(static_outcome)
                if isinstance(self.store, RunBundleStore):
                    self.store.write_condition_json(
                        digest,
                        condition.condition_id,
                        "result",
                        static_outcome,
                    )
                self._write_condition_timing(
                    condition,
                    execution_kind="static",
                    started_at_utc=static_started_at_utc,
                    started_monotonic=static_started_monotonic,
                    status="unresolved",
                )
                return self._human(problem, digest, outcomes, "common Lean core unavailable")
            static_outcome = ConditionOutcome(
                condition_id=condition.condition_id,
                passed=True,
                source="static",
                detail="instantiated audited smooth-DSL common lemma",
            )
            outcomes.append(static_outcome)
            if isinstance(self.store, RunBundleStore):
                self.store.write_condition_json(
                    digest,
                    condition.condition_id,
                    "result",
                    static_outcome,
                )
            self._write_condition_timing(
                condition,
                execution_kind="static",
                started_at_utc=static_started_at_utc,
                started_monotonic=static_started_monotonic,
                status="passed",
            )

        if self.smt_only:
            for condition in (*plan.parallel, *plan.sequential):
                if capability_summary(condition).eligible_backends:
                    continue
                ineligible = FormalOutcome(
                    False,
                    "unresolved",
                    "SMT-only: no eligible SMT backend",
                    unresolved=True,
                )
                outcomes.append(
                    ConditionOutcome(
                        condition_id=condition.condition_id,
                        passed=False,
                        source="unresolved",
                        detail=ineligible.detail,
                    )
                )
                decided = self._apply_formal(problem, digest, outcomes, ineligible)
                if decided is not None:
                    return decided

        decided = self._verify_group(
            problem,
            candidate,
            plan.parallel,
            digest,
            outcomes,
            active_formal_sources,
            allow_dreal=allow_dreal,
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
            allow_dreal=allow_dreal,
        )
        if decided is not None:
            return decided

        closing = plan.closing
        closing_started_at_utc = datetime.now(UTC).isoformat()
        closing_started_monotonic = time.monotonic()
        sources = set(active_formal_sources)
        if not self.common_core_audited:
            closing_outcome = ConditionOutcome(
                condition_id=closing.condition_id,
                passed=False,
                source="unresolved",
                detail="generic closing theorem library has not passed its axiom audit",
            )
            outcomes.append(closing_outcome)
            if isinstance(self.store, RunBundleStore):
                self.store.write_condition_json(
                    digest,
                    closing.condition_id,
                    "result",
                    closing_outcome,
                )
            self._write_condition_timing(
                closing,
                execution_kind="static_closing",
                started_at_utc=closing_started_at_utc,
                started_monotonic=closing_started_monotonic,
                status="unresolved",
            )
            return self._human(problem, digest, outcomes, "generic closing core unavailable")
        closing_outcome = ConditionOutcome(
            condition_id=closing.condition_id,
            passed=True,
            source="static",
            detail=(
                "applied audited generic Lean theorem "
                f"LeanBarrier.Lyapunov.{closing.lean_theorem_name}: "
                f"{closing.description}"
                if closing.kind
                in {
                    ConditionKind.STABILITY_INSTANTIATION,
                    ConditionKind.ROA_INSTANTIATION,
                }
                else (
                    "applied audited generic Lean theorem "
                    f"LeanBarrier.{closing.lean_theorem_name}: {closing.description}"
                )
            ),
        )
        outcomes.append(closing_outcome)
        if isinstance(self.store, RunBundleStore):
            self.store.write_condition_json(
                digest,
                closing.condition_id,
                "result",
                closing_outcome,
            )
        self._write_condition_timing(
            closing,
            execution_kind="static_closing",
            started_at_utc=closing_started_at_utc,
            started_monotonic=closing_started_monotonic,
            status="passed",
        )
        property_closed = True
        if sources == {"solver"}:
            certification = CertificationLevel.SOLVER_VERIFIED
            backend_profile = BackendProfile.SMT
        elif sources == {"lean"}:
            certification = CertificationLevel.LEAN_CERTIFIED
            backend_profile = BackendProfile.LEAN
        else:
            certification = CertificationLevel.HYBRID_VERIFIED
            backend_profile = BackendProfile.HYBRID
        verdict = CandidateVerdict(
            candidate_hash=digest,
            status=CandidateStatus.VERIFIED,
            certification=certification,
            scope=(
                VerificationScope.PROPERTY_VERIFIED
                if property_closed
                else VerificationScope.OBLIGATIONS_VERIFIED
            ),
            backend_profile=backend_profile,
            outcomes=tuple(outcomes),
        )
        return self._record_verdict(verdict)
