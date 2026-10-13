"""Verify certificates for dimension-indexed system families."""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from pydantic import Field

from .s01_models import (
    BackendProfile,
    CandidateStatus,
    CandidateVerdict,
    CertificationLevel,
    Condition,
    ConditionKind,
    ConditionOutcome,
    LeanAgentOutput,
    LeanAgentStatus,
    LeanResult,
    ProblemSpec,
    StrictModel,
    VerificationScope,
)
from .s02_expressions import content_hash
from .s03_family_expression import FamilyCandidateSpec
from .s10_family_lean_gen import FamilyLockedTheoremBundle
from .s10_lean_backend import LockedTheorem, ProofAgent
from .s13_runtime import (
    DEFAULT_FINALIZATION_RESERVE_SECONDS,
    RunDeadline,
    RunDeadlineExceeded,
)
from .s07_search import MAX_CANDIDATES, MAX_REGENERATIONS
from .s15_artifacts import ArtifactStore, RunBundleStore

FAMILY_PREMISES_CONDITION_ID = "indexed_family:lyapunov_premises"
FAMILY_CONDITION_ID = "indexed_family:all_positive_dimensions"


class FamilyLeanRunner(Protocol):


    def preflight_locked_definitions(self, locked: LockedTheorem) -> tuple[bool, str]: ...

    def run(
        self,
        condition_id: str,
        locked: LockedTheorem,
        agent: ProofAgent,
        *,
        counterexample_checker: object | None = None,
    ) -> LeanResult: ...

    def compile_once(
        self,
        condition_id: str,
        locked: LockedTheorem,
        output: LeanAgentOutput,
        *,
        note: str = "",
        origin: str = "pre-generated proof",
        timeout_seconds: float = 900.0,
    ) -> LeanResult | None: ...


FamilySynthesisProvider = Callable[
    [ProblemSpec, "FamilySynthesisContext"], FamilyCandidateSpec
]
FamilyLockedTheoremFactory = Callable[
    [ProblemSpec, FamilyCandidateSpec, str], FamilyLockedTheoremBundle
]
FamilyProofAgentProvider = Callable[
    [ProblemSpec, FamilyCandidateSpec, LockedTheorem], ProofAgent
]


class FamilyCandidateRecord(StrictModel):
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    structure_index: int = Field(ge=0)
    candidate: FamilyCandidateSpec


@dataclass(frozen=True)
class FamilySynthesisContext:
    structure_index: int
    parent: FamilyCandidateRecord | None
    errors: tuple[str, ...]


    counterexample: None = None
    history: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class FamilySearchResult:


    status: CandidateStatus
    verdict: CandidateVerdict | None
    candidates: tuple[FamilyCandidateRecord, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class FamilyLockedAudit:
    passed: bool
    detail: str


def family_candidate_semantic_fingerprint(candidate: FamilyCandidateSpec) -> str:


    return content_hash(
        candidate.model_dump(
            mode="json",
            exclude={"construction_summary", "assumptions"},
        )
    )


def _audit_family_locked_common(
    candidate: FamilyCandidateSpec,
    candidate_hash: str,
    locked: LockedTheorem,
) -> FamilyLockedAudit:


    if locked.candidate_hash != candidate_hash:
        return FamilyLockedAudit(False, "locked theorem candidate hash mismatch")
    if not locked.definitions.strip():
        return FamilyLockedAudit(False, "locked family definitions are empty")
    if locked.definition_check_name is None:
        return FamilyLockedAudit(False, "locked family definitions lack an audit declaration")
    if not re.search(
        rf"\btheorem\s+{re.escape(locked.theorem_name)}\b",
        locked.statement,
    ):
        return FamilyLockedAudit(False, "locked statement does not declare its theorem name")
    parameter = candidate.certificate_family_ast.extent
    declares_parameter = re.search(
        rf"∀\s*{parameter}\s*:\s*ℕ",
        locked.statement,
    )
    assumes_positive = re.search(rf"0\s*<\s*{parameter}\b", locked.statement)
    if declares_parameter is None or assumes_positive is None:
        return FamilyLockedAudit(
            False,
            f"locked statement must quantify every positive natural {parameter}",
        )
    combined = locked.definitions + "\n" + locked.statement
    if candidate_hash not in locked.definitions:
        return FamilyLockedAudit(False, "locked definitions do not embed the candidate hash")
    if candidate.family_contract_hash not in locked.definitions:
        return FamilyLockedAudit(False, "locked definitions do not embed the family contract hash")
    if candidate.shared_controller_ast is not None:
        required_state = "LeanBarrier.State n"
        required_index = "Fin n"
    else:
        required_state = "LeanBarrier.State (m + m)"
        required_index = "Fin m"
    if required_state not in combined:
        return FamilyLockedAudit(
            False,
            "locked theorem does not use the symbolic family state dimension",
        )
    if required_index not in locked.definitions:
        return FamilyLockedAudit(False, "locked definitions do not retain the indexed family")
    if re.search(r"LeanBarrier\.State\s+\d+\b", combined):
        return FamilyLockedAudit(False, "locked theorem contains a fixed state dimension")
    if re.search(r"\b(?:x|y|u)\d+\b", combined):
        return FamilyLockedAudit(False, "locked theorem contains expanded coordinate names")
    if re.search(r"\b(?:sorry|admit|axiom|unsafe)\b", combined):
        return FamilyLockedAudit(False, "locked family theorem contains a forbidden token")
    return FamilyLockedAudit(True, "symbolic family quantifier and locked hash are present")


def audit_family_obligations_locked_theorem(
    candidate: FamilyCandidateSpec,
    candidate_hash: str,
    locked: LockedTheorem,
) -> FamilyLockedAudit:


    common = _audit_family_locked_common(candidate, candidate_hash, locked)
    if not common.passed:
        return common
    if "LeanBarrier.IsGradient" not in locked.statement:
        return FamilyLockedAudit(False, "family obligation theorem omits IsGradient")
    forbidden_targets = (
        "ContinuousROAOn",
        "ContinuousGloballyAsymptoticallyStable",
        "ClassicalTrajectory",
        "Tendsto",
    )
    found = next((name for name in forbidden_targets if name in locked.statement), None)
    if found is not None:
        return FamilyLockedAudit(
            False,
            f"proof-agent family obligations improperly contain final target {found}",
        )
    if candidate.shared_controller_ast is None:
        if "LeanBarrier.Lyapunov.RadiallyUnbounded" not in locked.statement:
            return FamilyLockedAudit(False, "GAS family obligations omit radial unboundedness")
    elif "familyDomain_" not in locked.statement:
        return FamilyLockedAudit(False, "ROA family obligations omit sublevel/domain inclusion")
    return FamilyLockedAudit(True, "locked proof-agent goal contains Lyapunov premises only")


def audit_family_final_locked_theorem(
    candidate: FamilyCandidateSpec,
    candidate_hash: str,
    bundle: FamilyLockedTheoremBundle,
) -> FamilyLockedAudit:


    locked = bundle.final
    common = _audit_family_locked_common(candidate, candidate_hash, locked)
    if not common.passed:
        return common
    required_property = (
        "ContinuousROAOn"
        if candidate.shared_controller_ast is not None
        else "ContinuousGloballyAsymptoticallyStable"
    )
    if required_property not in locked.statement:
        return FamilyLockedAudit(False, "final family theorem omits the requested property")
    if "LeanBarrier.IsGradient" in locked.statement:
        return FamilyLockedAudit(False, "final family theorem still exposes proof premises")
    if bundle.closing_theorem_name not in bundle.closing_proof_body:
        return FamilyLockedAudit(False, "closing proof does not call its audited theorem")
    if bundle.obligations.theorem_name not in bundle.closing_proof_body:
        return FamilyLockedAudit(False, "closing proof does not consume the proved obligations")
    if re.search(
        r"\b(?:sorry|admit|axiom|unsafe|import|namespace|section|end)\b",
        bundle.closing_proof_body,
        re.IGNORECASE,
    ):
        return FamilyLockedAudit(False, "deterministic closing proof contains a forbidden token")
    return FamilyLockedAudit(True, "positive final claim is closed by the audited Lyapunov theorem")


def audit_family_locked_theorem(
    candidate: FamilyCandidateSpec,
    candidate_hash: str,
    locked: LockedTheorem,
) -> FamilyLockedAudit:


    return audit_family_obligations_locked_theorem(candidate, candidate_hash, locked)


def _unresolved(
    candidate_hash: str,
    detail: str,
    *,
    condition_id: str = FAMILY_PREMISES_CONDITION_ID,
    prior_outcomes: tuple[ConditionOutcome, ...] = (),
) -> CandidateVerdict:
    return CandidateVerdict(
        candidate_hash=candidate_hash,
        status=CandidateStatus.UNRESOLVED,
        outcomes=prior_outcomes + (
            ConditionOutcome(
                condition_id=condition_id,
                passed=False,
                source="unresolved",
                detail=detail,
            ),
        ),
    )


def _accepted_agent_output(result: LeanResult) -> LeanAgentOutput | None:


    for attempt in reversed(result.attempts):
        if (
            attempt.compiled
            and attempt.agent_status == LeanAgentStatus.CANDIDATE_PROOF
            and attempt.proof_body.strip()
        ):
            return LeanAgentOutput(
                status=LeanAgentStatus.CANDIDATE_PROOF,
                helper_lemmas=attempt.helper_lemmas,
                proof_body=attempt.proof_body,
            )
    return None


def _final_locked_with_obligations(
    bundle: FamilyLockedTheoremBundle,
    accepted: LeanAgentOutput,
) -> LockedTheorem:


    heartbeat = "set_option maxHeartbeats 1000000 in"


    declarations = [bundle.obligations.definitions]
    declarations.extend(
        f"{heartbeat}\n{helper}" for helper in accepted.helper_lemmas
    )
    declarations.append(
        f"{heartbeat}\n{bundle.obligations.statement} := {accepted.proof_body}"
    )
    return replace(bundle.final, definitions="\n\n".join(declarations))


class FamilyCandidateVerifier:


    def __init__(
        self,
        *,
        locked_theorem_factory: FamilyLockedTheoremFactory,
        lean_runner: FamilyLeanRunner,
        proof_agent_provider: FamilyProofAgentProvider,
        artifact_store: ArtifactStore | None = None,
        deadline: RunDeadline | None = None,
    ) -> None:
        self.locked_theorem_factory = locked_theorem_factory
        self.lean_runner = lean_runner
        self.proof_agent_provider = proof_agent_provider
        self.store = artifact_store
        self.deadline = deadline

    def _record_verdict(self, verdict: CandidateVerdict) -> CandidateVerdict:
        if self.store:
            self.store.write_json("verdict", verdict.candidate_hash, verdict)
            if isinstance(self.store, RunBundleStore):
                for outcome in verdict.outcomes:
                    self.store.write_condition_json(
                        verdict.candidate_hash,
                        outcome.condition_id,
                        "result",
                        outcome,
                    )
        return verdict

    def _write_lean_status(
        self,
        candidate_hash: str,
        condition_id: str,
        status: str,
        detail: str = "",
    ) -> None:
        if isinstance(self.store, RunBundleStore):
            self.store.write_condition_json(
                candidate_hash,
                condition_id,
                "lean/status",
                {
                    "status": status,
                    "candidate_hash": candidate_hash,
                    "condition_id": condition_id,
                    "detail": detail,
                    "updated_at_utc": datetime.now(UTC).isoformat(),
                },
            )

    def _record_lean_terminal(
        self,
        verdict: CandidateVerdict,
        *,
        status: str,
        condition_id: str,
    ) -> CandidateVerdict:
        detail = next(
            (
                outcome.detail
                for outcome in verdict.outcomes
                if outcome.condition_id == condition_id
            ),
            "",
        )
        self._write_lean_status(
            verdict.candidate_hash,
            condition_id,
            status,
            detail,
        )
        return self._record_verdict(verdict)

    def _write_lean_timeout(self, candidate_hash: str, condition_id: str) -> None:
        detail = "single-problem deadline exhausted"
        self._write_lean_status(candidate_hash, condition_id, "timeout", detail)
        if isinstance(self.store, RunBundleStore):
            self.store.write_condition_json(
                candidate_hash,
                condition_id,
                "result",
                {
                    "status": "timeout",
                    "candidate_hash": candidate_hash,
                    "condition_id": condition_id,
                    "detail": detail,
                },
            )

    def _check_deadline(self) -> None:
        if self.deadline is not None:
            self.deadline.check(
                reserve_seconds=DEFAULT_FINALIZATION_RESERVE_SECONDS
            )

    def verify(
        self,
        problem: ProblemSpec,
        candidate: FamilyCandidateSpec,
    ) -> CandidateVerdict:
        digest = content_hash(candidate)
        started_at_utc = datetime.now(UTC).isoformat()
        started_monotonic = time.monotonic()
        try:
            return self._verify(problem, candidate)
        finally:
            if isinstance(self.store, RunBundleStore):
                self.store.write_condition_json(
                    digest,
                    FAMILY_CONDITION_ID,
                    "timing",
                    {
                        "schema_version": "dynacert-condition-timing.v1",
                        "condition_id": FAMILY_CONDITION_ID,
                        "execution_kind": "indexed_family_direct_lean",
                        "started_at_utc": started_at_utc,
                        "finished_at_utc": datetime.now(UTC).isoformat(),
                        "duration_seconds": time.monotonic() - started_monotonic,
                    },
                )

    def _verify(
        self,
        problem: ProblemSpec,
        candidate: FamilyCandidateSpec,
    ) -> CandidateVerdict:
        self._check_deadline()
        digest = content_hash(candidate)
        if candidate.problem_id != problem.problem_id:
            return self._record_verdict(
                _unresolved(digest, "family candidate/problem id mismatch")
            )
        try:
            bundle = self.locked_theorem_factory(problem, candidate, digest)
        except Exception as error:
            return self._record_verdict(
                _unresolved(digest, f"locked family theorem generation failed: {error}")
            )
        if not isinstance(bundle, FamilyLockedTheoremBundle):
            return self._record_verdict(
                _unresolved(
                    digest,
                    "locked family theorem generation did not return a two-stage bundle",
                )
            )
        premises = bundle.obligations
        final = bundle.final
        premises_condition = Condition(
            condition_id=FAMILY_PREMISES_CONDITION_ID,
            kind=ConditionKind.INDEXED_FAMILY,
            candidate_hash=digest,
            description=(
                "Prove the submitted certificate's Lyapunov premises for every "
                "positive value of the dimension parameter."
            ),
            query=None,
            lean_theorem_name=premises.theorem_name,
        )
        final_condition = Condition(
            condition_id=FAMILY_CONDITION_ID,
            kind=ConditionKind.INDEXED_FAMILY,
            candidate_hash=digest,
            description=(
                "Instantiate the audited Lyapunov closing theorem to obtain the "
                "requested dynamical property in every positive dimension."
            ),
            query=None,
            lean_theorem_name=final.theorem_name,
        )
        if isinstance(self.store, RunBundleStore):
            for condition in (premises_condition, final_condition):
                self.store.write_condition_json(
                    digest,
                    condition.condition_id,
                    "condition",
                    condition,
                )
            self.store.write_condition_json(
                digest,
                FAMILY_PREMISES_CONDITION_ID,
                "result",
                {"status": "running"},
            )
            self.store.write_condition_text(
                digest,
                FAMILY_PREMISES_CONDITION_ID,
                "lean/locked_statement",
                premises.statement,
                ".lean",
            )
            self.store.write_condition_text(
                digest,
                FAMILY_PREMISES_CONDITION_ID,
                "lean/locked_source",
                f"{premises.definitions}\n\n{premises.statement}\n",
                ".lean",
            )
        premises_audit = audit_family_obligations_locked_theorem(
            candidate, digest, premises
        )
        if not premises_audit.passed:
            return self._record_lean_terminal(
                _unresolved(
                    digest,
                    "locked family obligation audit failed: " + premises_audit.detail,
                ),
                status="unresolved",
                condition_id=FAMILY_PREMISES_CONDITION_ID,
            )
        final_audit = audit_family_final_locked_theorem(candidate, digest, bundle)
        if not final_audit.passed:
            return self._record_lean_terminal(
                _unresolved(
                    digest,
                    "locked family closing audit failed: " + final_audit.detail,
                    condition_id=FAMILY_CONDITION_ID,
                ),
                status="unresolved",
                condition_id=FAMILY_CONDITION_ID,
            )
        scope = (
            self.store.scope(
                candidate_hash=digest,
                condition_id=FAMILY_PREMISES_CONDITION_ID,
                stage="family_lyapunov_premises",
            )
            if isinstance(self.store, RunBundleStore)
            else nullcontext()
        )
        with scope:
            self._write_lean_status(
                digest, FAMILY_PREMISES_CONDITION_ID, "running"
            )
            try:
                self._check_deadline()
                definitions_ok, diagnostics = (
                    self.lean_runner.preflight_locked_definitions(premises)
                )
            except RunDeadlineExceeded:
                self._write_lean_timeout(digest, FAMILY_PREMISES_CONDITION_ID)
                raise
            except Exception as error:
                return self._record_lean_terminal(
                    _unresolved(
                        digest,
                        f"locked family definition preflight crashed: {error}",
                    ),
                    status="unresolved",
                    condition_id=FAMILY_PREMISES_CONDITION_ID,
                )
            if not definitions_ok:
                return self._record_lean_terminal(
                    _unresolved(
                        digest,
                        "locked family definition preflight failed: " + diagnostics,
                    ),
                    status="unresolved",
                    condition_id=FAMILY_PREMISES_CONDITION_ID,
                )
            try:
                self._check_deadline()
                agent = self.proof_agent_provider(problem, candidate, premises)
                premises_result = self.lean_runner.run(
                    FAMILY_PREMISES_CONDITION_ID,
                    premises,
                    agent,
                )
            except RunDeadlineExceeded:
                self._write_lean_timeout(digest, FAMILY_PREMISES_CONDITION_ID)
                raise
            except Exception as error:
                return self._record_lean_terminal(
                    _unresolved(
                        digest,
                        f"family Lean proof failed before an audited result: {error}",
                    ),
                    status="unresolved",
                    condition_id=FAMILY_PREMISES_CONDITION_ID,
                )
        if self.store:
            if isinstance(self.store, RunBundleStore):
                self.store.write_condition_json(
                    digest,
                    FAMILY_PREMISES_CONDITION_ID,
                    "lean/result",
                    premises_result,
                )
            else:
                self.store.write_json(
                    "family_lean", f"{digest}-premises", premises_result
                )
                self.store.write_text(
                    "family_lean",
                    f"{digest}-premises-locked-statement",
                    premises.statement,
                    ".lean",
                )
        premises_accepted = (
            premises_result.status == LeanAgentStatus.CANDIDATE_PROOF
            and premises_result.compiled
            and premises_result.audit_passed
            and premises_result.candidate_hash == digest
            and premises_result.statement_hash == premises.statement_hash
        )
        accepted_output = _accepted_agent_output(premises_result)
        if not premises_accepted or accepted_output is None:
            detail = (
                premises_result.blocking_reason
                or premises_result.diagnostics
                or "Lyapunov premise proof was not accepted"
            )
            return self._record_lean_terminal(
                _unresolved(digest, detail),
                status="unresolved",
                condition_id=FAMILY_PREMISES_CONDITION_ID,
            )
        premises_outcome = ConditionOutcome(
            condition_id=FAMILY_PREMISES_CONDITION_ID,
            passed=True,
            source="lean",
            detail=(
                "all-dimensions Lyapunov premises compiled and passed the axiom audit"
            ),
        )
        self._write_lean_status(
            digest,
            FAMILY_PREMISES_CONDITION_ID,
            "passed",
            premises_outcome.detail,
        )
        if isinstance(self.store, RunBundleStore):
            self.store.write_condition_json(
                digest,
                FAMILY_PREMISES_CONDITION_ID,
                "result",
                premises_outcome,
            )

        final_locked = _final_locked_with_obligations(bundle, accepted_output)
        if isinstance(self.store, RunBundleStore):
            self.store.write_condition_json(
                digest,
                FAMILY_CONDITION_ID,
                "result",
                {"status": "running"},
            )
            self.store.write_condition_text(
                digest,
                FAMILY_CONDITION_ID,
                "lean/locked_statement",
                final_locked.statement,
                ".lean",
            )
            self.store.write_condition_text(
                digest,
                FAMILY_CONDITION_ID,
                "lean/locked_source",
                (
                    f"{final_locked.definitions}\n\n"
                    f"{final_locked.statement} := {bundle.closing_proof_body}\n"
                ),
                ".lean",
            )
        final_scope = (
            self.store.scope(
                candidate_hash=digest,
                condition_id=FAMILY_CONDITION_ID,
                stage="family_closing",
            )
            if isinstance(self.store, RunBundleStore)
            else nullcontext()
        )
        with final_scope:
            self._write_lean_status(digest, FAMILY_CONDITION_ID, "running")
            try:
                self._check_deadline()
                final_result = self.lean_runner.compile_once(
                    FAMILY_CONDITION_ID,
                    final_locked,
                    LeanAgentOutput(
                        status=LeanAgentStatus.CANDIDATE_PROOF,
                        proof_body=bundle.closing_proof_body,
                    ),
                    note=bundle.closing_theorem_name,
                    origin="audited family Lyapunov closing theorem",
                )
            except RunDeadlineExceeded:
                self._write_lean_timeout(digest, FAMILY_CONDITION_ID)
                raise
            except Exception as error:
                final_result = None
                closing_error = str(error)
            else:
                closing_error = ""
        if final_result is not None:
            if isinstance(self.store, RunBundleStore):
                self.store.write_condition_json(
                    digest,
                    FAMILY_CONDITION_ID,
                    "lean/result",
                    final_result,
                )
            elif self.store:
                self.store.write_json("family_lean", f"{digest}-final", final_result)
                self.store.write_text(
                    "family_lean",
                    f"{digest}-final-locked-statement",
                    final_locked.statement,
                    ".lean",
                )
        final_accepted = (
            final_result is not None
            and final_result.status == LeanAgentStatus.CANDIDATE_PROOF
            and final_result.compiled
            and final_result.audit_passed
            and final_result.candidate_hash == digest
            and final_result.statement_hash == final_locked.statement_hash
        )
        if not final_accepted:
            detail = (
                "deterministic Lyapunov closing theorem failed to compile or pass its "
                "axiom/hash audit"
            )
            if closing_error:
                detail += f": {closing_error}"
            return self._record_lean_terminal(
                _unresolved(
                    digest,
                    detail,
                    condition_id=FAMILY_CONDITION_ID,
                    prior_outcomes=(premises_outcome,),
                ),
                status="unresolved",
                condition_id=FAMILY_CONDITION_ID,
            )
        final_outcome = ConditionOutcome(
            condition_id=FAMILY_CONDITION_ID,
            passed=True,
            source="lean",
            detail=(
                "the positive all-dimensions property compiled via the audited "
                f"closing theorem {bundle.closing_theorem_name}"
            ),
        )
        return self._record_lean_terminal(
            CandidateVerdict(
                candidate_hash=digest,
                status=CandidateStatus.VERIFIED,
                certification=CertificationLevel.LEAN_CERTIFIED,
                scope=VerificationScope.PROPERTY_VERIFIED,
                backend_profile=BackendProfile.LEAN,
                outcomes=(premises_outcome, final_outcome),
            ),
            status="passed",
            condition_id=FAMILY_CONDITION_ID,
        )


class FamilyCandidateSearch:


    def __init__(
        self,
        *,
        verifier: FamilyCandidateVerifier,
        synthesis_provider: FamilySynthesisProvider,
        max_candidates: int = MAX_CANDIDATES,
        artifact_store: ArtifactStore | None = None,
        deadline: RunDeadline | None = None,
    ) -> None:
        if max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        self.verifier = verifier
        self.synthesis_provider = synthesis_provider
        self.max_candidates = max_candidates
        self.store = artifact_store or verifier.store
        self.deadline = deadline

    def _finish(self, result: FamilySearchResult) -> FamilySearchResult:
        if self.store:
            category = "search" if isinstance(self.store, RunBundleStore) else "family_search"
            self.store.write_json(category, "result", result)
        return result

    def _record_candidate_timing(
        self,
        candidate_index: int,
        *,
        started_at_utc: str,
        started_monotonic: float,
        status: str,
        candidate_hash: str | None = None,
    ) -> None:
        if self.store is None:
            return
        self.store.write_candidate_timing(
            candidate_index,
            {
                "schema_version": "dynacert-candidate-timing.v1",
                "candidate_index": candidate_index,
                "candidate_hash": candidate_hash,
                "status": status,
                "started_at_utc": started_at_utc,
                "finished_at_utc": datetime.now(UTC).isoformat(),
                "duration_seconds": time.monotonic() - started_monotonic,
            },
        )

    def run(self, problem: ProblemSpec) -> FamilySearchResult:
        records: list[FamilyCandidateRecord] = []
        seen_fingerprints: dict[str, FamilyCandidateRecord] = {}
        errors: list[str] = []
        parent: FamilyCandidateRecord | None = None
        generation_batches = 0
        while len(records) < self.max_candidates and generation_batches < self.max_candidates:
            generation_batches += 1
            candidate_index = len(records)
            if self.deadline is not None and self.deadline.expired(
                reserve_seconds=DEFAULT_FINALIZATION_RESERVE_SECONDS
            ):
                errors.append("single-problem deadline exhausted")
                return self._finish(
                    FamilySearchResult(
                        CandidateStatus.UNRESOLVED,
                        None,
                        tuple(records),
                        tuple(errors),
                    )
                )
            candidate_started_at_utc = datetime.now(UTC).isoformat()
            candidate_started_monotonic = time.monotonic()
            candidate: FamilyCandidateSpec | None = None
            semantic_fingerprint: str | None = None
            for _attempt in range(1 + MAX_REGENERATIONS):
                if self.deadline is not None and self.deadline.expired(
                    reserve_seconds=DEFAULT_FINALIZATION_RESERVE_SECONDS
                ):
                    errors.append("single-problem deadline exhausted")
                    return self._finish(
                        FamilySearchResult(
                            CandidateStatus.UNRESOLVED,
                            None,
                            tuple(records),
                            tuple(errors),
                        )
                    )
                context = FamilySynthesisContext(candidate_index, parent, tuple(errors))
                try:
                    generated = self.synthesis_provider(problem, context)
                except RunDeadlineExceeded:
                    errors.append("single-problem deadline exhausted")
                    return self._finish(
                        FamilySearchResult(
                            CandidateStatus.UNRESOLVED,
                            None,
                            tuple(records),
                            tuple(errors),
                        )
                    )
                except Exception as error:
                    errors.append(f"candidate {candidate_index}: parse error: {error}")
                    continue
                fingerprint = family_candidate_semantic_fingerprint(generated)
                duplicate = seen_fingerprints.get(fingerprint)
                if duplicate is not None:
                    errors.append(
                        "semantic duplicate candidate skipped without verification: "
                        f"fingerprint={fingerprint} first_candidate="
                        f"{duplicate.candidate_hash}"
                    )
                    continue
                candidate = generated
                semantic_fingerprint = fingerprint
                break
            if candidate is None:
                continue
            digest = content_hash(candidate)
            if semantic_fingerprint is None:
                raise AssertionError("unique family candidate lacks a semantic fingerprint")
            record = FamilyCandidateRecord(
                candidate_hash=digest,
                semantic_fingerprint=semantic_fingerprint,
                parent_hash=parent.candidate_hash if parent else None,
                structure_index=candidate_index,
                candidate=candidate,
            )
            records.append(record)
            seen_fingerprints[semantic_fingerprint] = record
            if self.store:
                self.store.write_json(
                    "lineage",
                    f"{candidate_index:02d}-{digest[:12]}",
                    record,
                )
                self.store.write_json("candidates", digest, candidate)
            try:
                verdict = self.verifier.verify(problem, candidate)
            except RunDeadlineExceeded:
                self._record_candidate_timing(
                    candidate_index,
                    started_at_utc=candidate_started_at_utc,
                    started_monotonic=candidate_started_monotonic,
                    status="problem_timeout_during_verification",
                    candidate_hash=digest,
                )
                errors.append("single-problem deadline exhausted")
                return self._finish(
                    FamilySearchResult(
                        CandidateStatus.UNRESOLVED,
                        None,
                        tuple(records),
                        tuple(errors),
                    )
                )
            if verdict.status == CandidateStatus.VERIFIED:
                self._record_candidate_timing(
                    candidate_index,
                    started_at_utc=candidate_started_at_utc,
                    started_monotonic=candidate_started_monotonic,
                    status=verdict.status.value,
                    candidate_hash=digest,
                )
                return self._finish(
                    FamilySearchResult(verdict.status, verdict, tuple(records), tuple(errors))
                )
            detail = verdict.outcomes[0].detail if verdict.outcomes else "family proof unresolved"
            errors.append(f"candidate {digest}: {detail}")
            parent = record
            self._record_candidate_timing(
                candidate_index,
                started_at_utc=candidate_started_at_utc,
                started_monotonic=candidate_started_monotonic,
                status=verdict.status.value,
                candidate_hash=digest,
            )
        return self._finish(
            FamilySearchResult(
                CandidateStatus.SEARCH_EXHAUSTED,
                None,
                tuple(records),
                tuple(errors),
            )
        )
