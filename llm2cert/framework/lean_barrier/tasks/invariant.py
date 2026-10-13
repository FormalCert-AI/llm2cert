"""Define the forward-invariance verification task."""
from __future__ import annotations

from ..s01_models import (
    CandidateSpec,
    Condition,
    ConditionKind,
    DynamicsKind,
    ProblemSpec,
    SafetyInterpretation,
    TaskType,
)
from ..s04_semantics import SemanticError, closed_loop_framework_sentence
from .barrier_common import barrier_conditions


class InvariantProfile:
    task_type = TaskType.INVARIANT

    def validate(self, problem: ProblemSpec, candidate: CandidateSpec | None = None) -> None:
        del candidate
        if problem.task_type != TaskType.INVARIANT:
            raise SemanticError("invariant profile received a non-invariant problem")
        if problem.safety_interpretation == SafetyInterpretation.SEPARATE_SAFE_UNSAFE:
            raise SemanticError("separate_safe_unsafe is not implemented")
        if problem.unsafe_set is None:
            raise SemanticError("invariant problems require an unsafe set")
        if (
            problem.safety_interpretation == SafetyInterpretation.OUTSIDE_X_IS_UNSAFE
            and problem.task_type != TaskType.INVARIANT
        ):
            raise SemanticError("outside_X_is_unsafe is only allowed on invariant problems")

    def _require_certified_in_x(self, problem: ProblemSpec) -> bool:
        return problem.safety_interpretation == SafetyInterpretation.OUTSIDE_X_IS_UNSAFE

    def build_conditions(
        self, problem: ProblemSpec, candidate: CandidateSpec
    ) -> tuple[Condition, ...]:
        self.validate(problem, candidate)
        return barrier_conditions(
            problem,
            candidate,


            include_initial=True,
            closing_kind=ConditionKind.INVARIANT_INSTANTIATION,
            closing_description=(
                "Apply the audited strict-boundary theorem for trajectory segments "
                "that remain in X."
                if problem.system.kind == DynamicsKind.CONTINUOUS
                else "Apply the audited discrete super-level invariance theorem."
            ),
            closing_theorem=(
                "continuous_strict_boundary_barrier_safety"
                if problem.system.kind == DynamicsKind.CONTINUOUS
                else "discrete_superlevel_invariant"
            ),
            require_certified_in_x=self._require_certified_in_x(problem),
        )

    def synthesis_role(self, problem: ProblemSpec) -> str:
        extra = " and an explicit controller" if problem.system.control_vars else ""
        return (
            "You are a control theory expert specializing in barrier functions and "
            f"forward-invariant sets. Propose one barrier{extra} for the system below."
        )

    def synthesis_framework(self, problem: ProblemSpec) -> str:
        stay = (
            "The certified set is C_B = {x | B(x) >= 0}. It must stay inside X and be "
            "forward invariant. States outside X are unsafe."
            if self._require_certified_in_x(problem)
            else (
                "The claim is only on the working domain X: C_B = {x in X | B(x) >= 0} "
                "must stay out of X_u while the trajectory remains in X. X itself need "
                "not be forward invariant."
            )
        )
        extra = ""
        closed = closed_loop_framework_sentence(problem, claimed_domain="X")
        if closed:
            extra = f"\n{closed}"
        seed = (
            "The required seed set X_seed shown above must satisfy "
            "X_seed ⊆ C_B; it exists only to prevent a vacuous singleton certified set.\n"
            if problem.initial_set is not None
            else "No nontrivial seed set is required.\n"
        )
        if problem.system.kind == DynamicsKind.CONTINUOUS:
            return (
                f"{stay}\n"
                f"{seed}"
                "B(x) < 0 for every unsafe state in the query.\n"
                "On {x in X | B(x) = 0}, require the strict boundary condition "
                "L_f B > 0. All flow checks are only on X."
                f"{extra}"
            )
        return (
            f"{stay}\n"
            f"{seed}"
            "B(x) < 0 for every unsafe state in the query.\n"
            "For every x in X, B(x) >= 0 must imply B(f_cl(x)) >= 0."
            f"{extra}"
        )

    def synthesis_objective(self, problem: ProblemSpec) -> str:
        seed = (
            " The proposed certified set must cover the supplied X_seed."
            if problem.initial_set is not None
            else ""
        )
        return (
            "Propose a C1 barrier whose super-level set is forward invariant and "
            f"separated from the unsafe set.{seed} Do not alter or invent a seed set. "
            "Among candidates satisfying every required condition, make the volume "
            "of the certified invariant set as large as possible. "
            "Never write "
            "verified, proved, certified, UNSAT, or globally valid unless that result "
            "is already in the supplied evidence."
        )

    def brief_lines(self, problem: ProblemSpec) -> list[str]:
        return [
            f"Task type: {problem.task_type.value}",
            f"Safety interpretation: {problem.safety_interpretation.value}",
        ]
