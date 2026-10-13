"""Connect model agents to synthesis and verification tasks."""
from __future__ import annotations

from dataclasses import dataclass

from .s06_agents import StructuredAgentRunner
from .s10_lean_backend import LockedTheorem, ProofAgent
from .s01_models import (
    Backend,
    CandidateSpec,
    LeanAgentOutput,
    LeanLocalPatch,
    Condition,
    ProblemSpec,
    VerificationRoute,
    VerificationRouterDecision,
)
from .s05_prompts import (
    candidate_prompt_view,
    is_indexed_family_problem,
    lean_followup,
    lean_local_repair_prompt,
    lean_proof_prompt,
    synthesis_followup,
    synthesis_prompt,
    synthesis_proposal_model,
    verification_router_prompt,
)
from .s03_case_io import candidate_from_proposal
from .s03_family_expression import (
    FamilyCandidateSpec,
    family_candidate_from_proposal,
    family_candidate_prompt_view,
)
from .s09_router import default_solver_order
from .s07_search import SynthesisContext
from .s10_local_repair import (
    LocalRepairRequest,
    apply_local_patch,
    localize_lean_error,
    targets_replacement_span,
)

DEFAULT_PUBLIC_LEMMAS = (
    "LeanBarrier.discrete_superlevel_invariant",
    "LeanBarrier.discrete_barrier_implies_safety",
    "LeanBarrier.superlevel_avoids_unsafe",
    "LeanBarrier.continuous_strict_boundary_barrier_safety",
    "LeanBarrier.fixed_parameter_continuous_strict_boundary_barrier_safety",
)


FAMILY_PUBLIC_LEMMAS = (
    "LeanBarrier.gradientCLM_apply",
    "LeanBarrier.Lyapunov.coordinate_sq_le_sqNorm",
    "LeanBarrier.Lyapunov.radiallyUnbounded_compact_sublevel",
    "LeanBarrier.Lyapunov.compact_sublevel_of_continuous_bounded_superset",
)


@dataclass(frozen=True)
class PromptedAgentSuite:
    synthesis_runner: StructuredAgentRunner
    verification_router_runner: StructuredAgentRunner
    lean_runner: StructuredAgentRunner
    public_lemmas: tuple[str, ...] = DEFAULT_PUBLIC_LEMMAS
    contextual_local_repair: bool = False

    def synthesize(
        self, problem: ProblemSpec, context: SynthesisContext
    ) -> CandidateSpec | FamilyCandidateSpec:

        counterexamples: list[dict[str, object]] = [dict(entry) for entry in context.history]
        if not counterexamples and context.counterexample is not None:
            counterexamples = [context.counterexample.model_dump(mode="json")]
        if self.synthesis_runner.system_prompt is None:
            prompt = synthesis_prompt(
                problem,
                structure_index=context.structure_index,
            )
        else:
            verified_counterexample = None
            if context.counterexample is not None:
                verified_counterexample = {
                    "checked_condition_id": context.counterexample.condition_id,
                    "original_witness_or_box": context.counterexample.witness.model_dump(
                        mode="json"
                    ),
                    "independent_residual": context.counterexample.residual,
                    "evidence_level": context.counterexample.level.value,
                    "source": context.counterexample.source,
                }
            prompt = synthesis_followup(
                problem=problem,
                structure_index=context.structure_index,
                failed_candidate=(
                    None
                    if context.parent is None
                    else (
                        family_candidate_prompt_view(problem, context.parent.candidate)
                        if isinstance(context.parent.candidate, FamilyCandidateSpec)
                        else candidate_prompt_view(problem, context.parent.candidate)
                    )
                ),
                verified_counterexample=verified_counterexample,
                rejected_history=counterexamples,
                errors=list(context.errors),
            )
        proposal = self.synthesis_runner.run(prompt, synthesis_proposal_model(problem))
        if is_indexed_family_problem(problem):
            return family_candidate_from_proposal(problem, proposal)
        return candidate_from_proposal(proposal)

    def verification_route(
        self,
        condition: Condition,
        capabilities: dict[str, object],
    ) -> VerificationRouterDecision:
        raw = capabilities.get("eligible_backends") or ()
        eligible = tuple(Backend(item) for item in raw)
        if capabilities.get("polynomial_nra") and eligible:
            return VerificationRouterDecision(
                condition_id=condition.condition_id,
                route=VerificationRoute.SMT,
                solver_order=default_solver_order(eligible),
                rationale="polynomial SMT: use capability_summary order, skip the router model",
            )
        runner = self.verification_router_runner.fresh()
        prompt = verification_router_prompt(condition, capabilities)
        return runner.run(prompt, VerificationRouterDecision)

    def proof_agent(
        self,
        problem: ProblemSpec,
        candidate: CandidateSpec | FamilyCandidateSpec,
        condition: Condition,
        locked: LockedTheorem,
        mode: str,
    ) -> ProofAgent:
        runner = self.lean_runner.fresh()
        last_output: LeanAgentOutput | None = None
        patch_base: LeanAgentOutput | None = None
        patch_request: LocalRepairRequest | None = None
        patch_line_count = 0
        patch_pending = False
        local_patch_calls = 0
        def prove(round_index: int, previous: str, diagnostics: str) -> LeanAgentOutput:
            nonlocal last_output, patch_base, patch_request, patch_line_count
            nonlocal patch_pending, local_patch_calls
            if runner.system_prompt is None:
                prompt = lean_proof_prompt(
                    candidate=candidate,
                    candidate_hash=locked.candidate_hash,
                    condition=condition,
                    locked_definitions=locked.definitions,
                    locked_statement=locked.statement,
                    public_lemmas=(
                        FAMILY_PUBLIC_LEMMAS
                        if isinstance(candidate, FamilyCandidateSpec)
                        else self.public_lemmas
                    ),
                    previous_proof_body=previous,
                    compiler_diagnostics=diagnostics,
                    mode=mode,
                    indexed_family=isinstance(candidate, FamilyCandidateSpec),
                )
            else:
                fallback_note = ""
                allow_another_patch = True
                if patch_pending:


                    next_request = (
                        None
                        if last_output is None
                        else localize_lean_error(last_output, diagnostics, locked.statement)
                    )
                    same_target = bool(
                        patch_request is not None
                        and targets_replacement_span(
                            patch_request, next_request, patch_line_count
                        )
                    )
                    if same_target:
                        if patch_base is not None:
                            last_output = patch_base
                        fallback_note = (
                            "\n\nThe transactional patch did not remove the selected "
                            "source error. The framework rolled back to the pre-patch proof."
                        )
                        allow_another_patch = False
                    else:
                        fallback_note = (
                            "\n\nLean no longer reports the selected source error, so the "
                            "transactional patch was committed. The diagnostics below are "
                            "from a later independent error in the patched proof."
                        )
                    patch_base = None
                    patch_request = None
                    patch_line_count = 0
                    patch_pending = False
                if (
                    self.contextual_local_repair
                    and last_output is not None
                    and local_patch_calls < 2
                    and allow_another_patch
                ):
                    request = localize_lean_error(
                        last_output, diagnostics, locked.statement
                    )
                    if request is not None:
                        local_patch_calls += 1
                        patch = runner.run(
                            lean_local_repair_prompt(request), LeanLocalPatch
                        )
                        patched = apply_local_patch(last_output, request, patch)
                        if patched is not None:
                            patch_base = last_output
                            patch_request = request
                            patch_line_count = len(patch.replacement_code.splitlines())
                            last_output = patched
                            patch_pending = True
                            return patched
                        fallback_note += (
                            "\n\nThe constrained local-repair response was declined or "
                            "failed validation, so use the existing full-proof repair path."
                        )
                prompt = lean_followup(
                    candidate_hash=locked.candidate_hash,
                    condition=condition,
                    locked_definitions=locked.definitions,
                    locked_statement=locked.statement,
                    previous_proof_body=(
                        last_output.proof_body if last_output is not None else previous
                    ),
                    compiler_diagnostics=diagnostics + fallback_note,
                    mode=mode,
                )
            last_output = runner.run(prompt, LeanAgentOutput)
            return last_output

        return prove
