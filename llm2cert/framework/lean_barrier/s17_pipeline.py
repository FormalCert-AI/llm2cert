"""Coordinate certificate proposal, screening, and verification."""
from __future__ import annotations

from dataclasses import dataclass

from .s06_agent_suite import PromptedAgentSuite
from .s05_prompts import is_indexed_family_problem
from .s15_artifacts import ArtifactStore
from .s10_lean_backend import DevelopmentLeanCompiler, LeanProofRunner
from .s01_models import CandidateStatus, Condition, ConditionKind, ProblemSpec
from .s03_family_expression import FamilyCandidateSpec
from .s10_family_lean_gen import generate_family_locked_theorem
from .s07_search import (
    CandidateSearch,
    MAX_CANDIDATES,
    SearchResult,
    SynthesisProvider,
)
from .s12_smt_backend import SolverRunner
from .s16_workflow import (
    CandidateVerifier,
    ProofAgentProvider,
    VerificationRouterProvider,
)
from .s18_family_workflow import (
    FAMILY_PREMISES_CONDITION_ID,
    FamilyCandidateSearch,
    FamilyCandidateVerifier,
    FamilySearchResult,
)
from .s13_runtime import RunDeadline


@dataclass(frozen=True)
class AgentRoles:


    synthesizer: SynthesisProvider
    verification_router: VerificationRouterProvider
    lean_prover: ProofAgentProvider

    @classmethod
    def from_suite(cls, suite: PromptedAgentSuite) -> AgentRoles:
        return cls(
            synthesizer=suite.synthesize,
            verification_router=suite.verification_route,
            lean_prover=suite.proof_agent,
        )


@dataclass(frozen=True)
class PipelineConfig:


    max_candidates: int = MAX_CANDIDATES
    common_core_audited: bool = True
    kernel_first: bool = False
    smt_only: bool = False
    lean_only: bool = False
    lean_repair_feedback: str = "processed"


class BarrierPipeline:


    def __init__(
        self,
        *,
        roles: AgentRoles,
        compiler: DevelopmentLeanCompiler,
        store: ArtifactStore,
        solver_runner: SolverRunner | None = None,
        config: PipelineConfig | None = None,
        deadline: RunDeadline | None = None,
    ) -> None:
        self.roles = roles
        self.compiler = compiler
        self.store = store
        self.solver_runner = solver_runner
        self.config = config or PipelineConfig()
        if self.config.smt_only and self.config.lean_only:
            raise ValueError("smt_only and lean_only are mutually exclusive")
        self.deadline = deadline

    def run(self, problem: ProblemSpec) -> SearchResult | FamilySearchResult:
        if self.config.smt_only and is_indexed_family_problem(problem):
            result = FamilySearchResult(
                status=CandidateStatus.UNRESOLVED,
                verdict=None,
                candidates=(),
                errors=("SMT-only mode: indexed family has no SMT encoding",),
            )
            self.store.write_json("search", "result", result)
            return result
        if is_indexed_family_problem(problem):
            lean_runner = LeanProofRunner(
                self.compiler,
                deadline=self.deadline,
                repair_feedback=self.config.lean_repair_feedback,
            )

            def synthesize_family(problem_spec, context):
                candidate = self.roles.synthesizer(problem_spec, context)
                if not isinstance(candidate, FamilyCandidateSpec):
                    raise TypeError("indexed family synthesis must return FamilyCandidateSpec")
                return candidate

            def prove_family(problem_spec, candidate, locked):
                condition = Condition(
                    condition_id=FAMILY_PREMISES_CONDITION_ID,
                    kind=ConditionKind.INDEXED_FAMILY,
                    candidate_hash=locked.candidate_hash,
                    description=(
                        "Prove the candidate-specific Lyapunov premises for every "
                        "positive value of the symbolic dimension parameter. The "
                        "framework separately applies the audited closing theorem."
                    ),
                    query=None,
                    lean_theorem_name=locked.theorem_name,
                )
                return self.roles.lean_prover(
                    problem_spec, candidate, condition, locked, "direct"
                )

            verifier = FamilyCandidateVerifier(
                locked_theorem_factory=(
                    lambda problem_spec, candidate, _digest: (
                        generate_family_locked_theorem(problem_spec, candidate)
                    )
                ),
                lean_runner=lean_runner,
                proof_agent_provider=prove_family,
                artifact_store=self.store,
                deadline=self.deadline,
            )
            return FamilyCandidateSearch(
                verifier=verifier,
                synthesis_provider=synthesize_family,
                artifact_store=self.store,
                max_candidates=self.config.max_candidates,
                deadline=self.deadline,
            ).run(problem)

        verifier = CandidateVerifier(
            solver_runner=self.solver_runner,
            lean_runner=(
                None
                if self.config.smt_only
                else LeanProofRunner(
                    self.compiler,
                    deadline=self.deadline,
                    repair_feedback=self.config.lean_repair_feedback,
                )
            ),
            verification_router_provider=self.roles.verification_router,
            proof_agent_provider=self.roles.lean_prover,
            common_core_audited=self.config.common_core_audited,
            kernel_first=self.config.kernel_first,
            artifact_store=self.store,
            deadline=self.deadline,
            smt_only=self.config.smt_only,
            lean_only=self.config.lean_only,
        )
        search = CandidateSearch(
            verifier=verifier,
            synthesis_provider=self.roles.synthesizer,
            artifact_store=self.store,
            max_candidates=self.config.max_candidates,
            deadline=self.deadline,
        )
        return search.run(problem)


__all__ = ["AgentRoles", "BarrierPipeline", "PipelineConfig"]
