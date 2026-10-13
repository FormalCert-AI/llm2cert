"""Define the safety verification task."""
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


class SafetyProfile:
    task_type = TaskType.SAFETY

    def validate(self, problem: ProblemSpec, candidate: CandidateSpec | None = None) -> None:
        del candidate
        if problem.task_type != TaskType.SAFETY:
            raise SemanticError("safety profile received a non-safety problem")
        if problem.unsafe_set is None:
            raise SemanticError("safety problems require an unsafe set")
        if problem.safety_interpretation == SafetyInterpretation.OUTSIDE_X_IS_UNSAFE:
            raise SemanticError(
                "outside_X_is_unsafe is only allowed on invariant problems, not safety"
            )
        if problem.safety_interpretation == SafetyInterpretation.SEPARATE_SAFE_UNSAFE:
            raise SemanticError("separate_safe_unsafe is not implemented")
        if problem.safety_interpretation != SafetyInterpretation.CONDITIONAL_IN_X:
            raise SemanticError("safety problems require safety_interpretation=conditional_in_X")

    def build_conditions(
        self, problem: ProblemSpec, candidate: CandidateSpec
    ) -> tuple[Condition, ...]:
        self.validate(problem, candidate)
        fixed_parameter = bool(problem.fixed_parameters)
        return barrier_conditions(
            problem,
            candidate,
            include_initial=True,
            closing_kind=ConditionKind.SAFETY_INSTANTIATION,
            closing_description=(
                "Apply the audited fixed-parameter conditional safety theorem "
                "uniformly for every admissible fixed parameter and for trajectory "
                "segments that remain in X."
                if fixed_parameter
                else "Apply the audited conditional safety theorem for trajectory "
                "segments that remain in X."
                if problem.system.kind == DynamicsKind.CONTINUOUS
                else "Apply the audited discrete super-level invariance and safety theorem."
            ),
            closing_theorem=(
                "fixed_parameter_continuous_strict_boundary_barrier_safety"
                if fixed_parameter
                else "continuous_strict_boundary_barrier_safety"
                if problem.system.kind == DynamicsKind.CONTINUOUS
                else "discrete_barrier_implies_safety"
            ),
        )

    def synthesis_role(self, problem: ProblemSpec) -> str:
        extra = " and an explicit controller" if problem.system.control_vars else ""
        return (
            "You are a control theory expert specializing in barrier functions and "
            f"invariant sets. Propose one barrier{extra} for the system below."
        )

    def synthesis_framework(self, problem: ProblemSpec) -> str:
        closed = closed_loop_framework_sentence(problem, claimed_domain="X")
        extra = f"\n{closed}" if closed else ""
        domain = (
            "the full space X = R^n. The finite screening box is only for FastCheck "
            "and must not be used to justify a global claim"
            if problem.formal_domain_unbounded
            else "the bounded working domain X"
        )
        scope_sentence = (
            "All formal checks are on X = R^n; the screening box is not a theorem bound."
            if problem.formal_domain_unbounded
            else (
                "All checks are only on X: the claim is conditional on the trajectory "
                "remaining in X, not that X is invariant."
            )
        )
        if problem.system.kind == DynamicsKind.CONTINUOUS:
            strict_boundary_condition = (
                "Condition 2 (strict boundary): for every x in X with B(x) = 0 "
                "and every admissible fixed w in W, "
                "L_{f_w} B(x) = ∇B(x) · f(x,w) > 0.\n"
                if problem.fixed_parameters
                else "Condition 2 (strict boundary): for every x in X with B(x) = 0, "
                "L_f B(x) = ∇B(x) · f(x) > 0.\n"
            )
            return (
                f"Find a C1 barrier B on {domain} such that "
                "C = {x in X | B(x) >= 0} is a super-level invariant (B >= 0, not B <= 0).\n"
                "Condition 1: B(x) < 0 for every unsafe state x in X_u ∩ X. "
                "If an initial set X_i is present, every x in X_i ∩ X must satisfy B(x) >= 0.\n"
                f"{strict_boundary_condition}"
                "Compute ∇B and L_f B yourself before proposing B. Prefer an analytic "
                "expression that a solver can check. Do not use trajectories or the vector "
                f"field itself as the certificate. {scope_sentence}"
                f"{extra}"
            )
        return (
            f"Find a barrier B on {domain} such that C = {{x in X | B(x) >= 0}}.\n"
            "Condition 1: B(x) < 0 for every unsafe state x in X_u ∩ X. "
            "If an initial set X_i is present, every x in X_i ∩ X must satisfy B(x) >= 0.\n"
            "Condition 2: for every x in X, B(x) >= 0 must imply B(f_cl(x)) >= 0.\n"
            f"{scope_sentence}"
            f"{extra}"
        )

    def synthesis_objective(self, problem: ProblemSpec) -> str:
        analytic_preference = (
            "It may be built so that the Lie derivative has "
            "a controllable sign, including transcendental terms that cancel or "
            "dominate those in f."
            if problem.system.kind == DynamicsKind.CONTINUOUS
            else (
                "It may be built so that the one-step "
                "difference B(F_cl(x)) - B(x) has a controllable sign, including "
                "transcendental terms that cancel under the map F_cl."
            )
        )
        return (
            "First satisfy Condition 1 and Condition 2 on X. Cover X_i and exclude "
            "X_u. Only after those conditions look plausible, prefer a larger "
            "invariant set C; there is no volume score to optimize. B need not be "
            f"polynomial. {analytic_preference} "
            "In construction_summary, separate (1) algebraically guaranteed facts, "
            "(2) heuristic expectations that still need the pipeline, and (3) "
            "independently supplied verifier evidence. Never write verified, proved, "
            "certified, UNSAT, or globally valid unless that result is already in the "
            "supplied evidence. Do not invent numerical minima, margins, solver "
            "outputs, interval bounds, or counterexamples. Later turns will add the "
            "failed candidate and independently verified counterexamples; diagnose that "
            "evidence directly and change the expression as needed. Coefficients-only "
            "edits are allowed but not required."
        )

    def brief_lines(self, problem: ProblemSpec) -> list[str]:
        del problem
        return []
