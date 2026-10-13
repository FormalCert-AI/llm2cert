"""Define the stability verification task."""
from __future__ import annotations

from ..s01_models import (
    CandidateSpec,
    Condition,
    ConditionKind,
    DynamicsKind,
    ProblemSpec,
    StabilityKind,
    TaskType,
)
from ..s04_semantics import SemanticError, closed_loop_framework_sentence
from .lyapunov_common import (
    is_global_kind,
    lyapunov_conditions,
)

_IMPLEMENTED = {
    StabilityKind.LOCAL_LYAPUNOV,
    StabilityKind.LOCAL_ASYMPTOTIC,
    StabilityKind.LOCAL_EXPONENTIAL,
    StabilityKind.GLOBAL_ASYMPTOTIC,
    StabilityKind.GLOBAL_EXPONENTIAL,
}


class StabilityProfile:
    task_type = TaskType.STABILITY

    def validate(self, problem: ProblemSpec, candidate: CandidateSpec | None = None) -> None:
        if problem.task_type != TaskType.STABILITY:
            raise SemanticError("stability profile received a non-stability problem")
        if problem.stability_kind is None:
            raise SemanticError("stability problems require stability_kind")
        if problem.stability_kind not in _IMPLEMENTED:
            raise SemanticError(f"unsupported stability_kind: {problem.stability_kind}")
        if problem.neighborhood is None:
            raise SemanticError("stability problems require a neighborhood N")
        if is_global_kind(problem.stability_kind) and not problem.neighborhood.unbounded:
            raise SemanticError("global_* requires an unbounded neighborhood (R^n)")
        if not is_global_kind(problem.stability_kind) and problem.neighborhood.unbounded:
            raise SemanticError("local_* requires a bounded neighborhood N")
        if problem.unsafe_set is not None:
            raise SemanticError("stability problems must not declare an unsafe set")
        if problem.initial_set is not None:
            raise SemanticError("stability problems must not declare an initial set")
        if candidate is not None and candidate.level_c is not None:
            raise SemanticError(
                "stability candidates must not provide level_c; all stability "
                "conditions are checked on the fixed neighborhood N"
            )
        if candidate is not None and problem.stability_kind in {
            StabilityKind.LOCAL_EXPONENTIAL,
            StabilityKind.GLOBAL_EXPONENTIAL,
        }:
            if candidate.exp_c1 is None or candidate.exp_c2 is None or candidate.exp_c3 is None:
                raise SemanticError("exponential stability requires candidate exp_c1, exp_c2, exp_c3")

    def build_conditions(
        self, problem: ProblemSpec, candidate: CandidateSpec
    ) -> tuple[Condition, ...]:
        self.validate(problem, candidate)
        assert problem.stability_kind is not None
        discrete = problem.system.kind == DynamicsKind.DISCRETE
        kind = problem.stability_kind
        if kind == StabilityKind.LOCAL_LYAPUNOV:
            closing_theorem = (
                "discrete_lyapunov_implies_stable_in"
                if discrete
                else "continuous_lyapunov_implies_stable_in"
            )
            closing_description = (
                "Apply the audited domain-relative Lyapunov stability theorem; "
                "its conclusion concerns trajectory segments that remain in N."
            )
        elif kind == StabilityKind.LOCAL_ASYMPTOTIC:
            closing_theorem = (
                "discrete_strict_lyapunov_implies_asymptotic_stable_in"
                if discrete
                else "continuous_strict_lyapunov_implies_asymptotic_stable_in"
            )
            closing_description = (
                "Apply the audited domain-relative strict Lyapunov theorem for "
                "stability and attraction of trajectories that remain in N."
            )
        elif kind == StabilityKind.GLOBAL_ASYMPTOTIC:
            closing_theorem = (
                "discrete_lyapunov_implies_global_asymptotic_stability"
                if discrete
                else "continuous_lyapunov_implies_global_asymptotic_stability"
            )
            closing_description = (
                "Apply the audited global asymptotic stability theorem using "
                "positive definiteness, strict decrease, the fixed equilibrium, "
                "and radial unboundedness."
            )
        else:
            closing_theorem = (
                "discrete_lyapunov_implies_exponential_stable_in"
                if discrete
                else "continuous_lyapunov_implies_exponential_stable_in"
            )
            closing_description = (
                "Apply the audited squared-norm exponential stability theorem "
                "with the verified quadratic and decay constants."
            )
        return lyapunov_conditions(
            problem,
            candidate,
            domain=problem.neighborhood,
            kind=kind,
            closing_kind=ConditionKind.STABILITY_INSTANTIATION,
            closing_description=closing_description,
            closing_theorem=closing_theorem,
        )

    def synthesis_role(self, problem: ProblemSpec) -> str:
        extra = (
            " Propose one Lyapunov certificate V and an explicit controller."
            if problem.system.control_vars
            else " Propose one Lyapunov certificate V for the system below."
        )
        return (
            "You are a control theory expert specializing in Lyapunov functions."
            + extra
        )

    def synthesis_framework(self, problem: ProblemSpec) -> str:
        kind = problem.stability_kind
        assert kind is not None
        domain = "R^n" if is_global_kind(kind) else "the neighborhood N"
        discrete = problem.system.kind == DynamicsKind.DISCRETE
        dpi = (
            "D_pi V = V(F(x)) - V(x)"
            if discrete
            else "D_pi V = grad V · f"
        )
        lines = [
            "The certificate is a Lyapunov function V, not a barrier. This task does "
            f"not choose a level constant or a smaller certified sublevel: all claimed "
            f"conditions are on the fixed domain {domain}.",
            "V(x*) = 0 at the equilibrium, and V(x) > 0 for every other point of the domain.",
            "Exclude the equilibrium by the symbol x != x*, not by deleting a ball around it.",
            "A sublevel set may appear in a conceptual Lyapunov argument, but it must not "
            "be used to exclude a counterexample from the fixed claimed domain.",
            f"Decrease rate: {dpi}.",
        ]
        if kind == StabilityKind.LOCAL_LYAPUNOV:
            lines.append("Lyapunov stability: D_pi V <= 0 on N.")
        elif kind in {StabilityKind.LOCAL_ASYMPTOTIC, StabilityKind.GLOBAL_ASYMPTOTIC}:
            lines.append("Asymptotic stability: D_pi V < 0 on the domain minus the equilibrium.")
        if kind == StabilityKind.GLOBAL_ASYMPTOTIC:
            lines.append(
                "Global asymptotic stability also requires V radially unbounded: "
                "||x|| → ∞ implies V(x) → ∞. That condition is proved in Lean 4, not by SMT."
            )
        if kind in {StabilityKind.LOCAL_EXPONENTIAL, StabilityKind.GLOBAL_EXPONENTIAL}:
            extra = (
                " For discrete time, 0 < exp_c3 <= 1, equivalently V(F) <= (1-c3) V."
                if discrete
                else ""
            )
            lines.append(
                "Exponential stability: give positive rationals exp_c1, exp_c2, exp_c3 "
                "such that c1 ||x||^2 <= V(x) <= c2 ||x||^2 and D_pi V + c3 V <= 0 "
                f"on {domain}.{extra}"
            )
        if is_global_kind(kind):
            lines.append(
                "A finite-box dReal unsat is not a global theorem. Global positive "
                "conclusions must come from Lean 4 or unbounded polynomial SMT."
            )
        closed = closed_loop_framework_sentence(problem, claimed_domain=domain)
        if closed:
            lines.append(closed)
        return "\n".join(lines)

    def synthesis_objective(self, problem: ProblemSpec) -> str:
        del problem
        return (
            "Propose V in the certificate expression string and, only for exponential "
            "stability, the required exact decay constants. Do not introduce level_c or "
            "replace N by a candidate-chosen sublevel set. Do not "
            "change N. Never write verified, proved, certified, UNSAT, or globally "
            "valid unless that result is already in the supplied evidence."
        )

    def brief_lines(self, problem: ProblemSpec) -> list[str]:
        kind = problem.stability_kind.value if problem.stability_kind else "none"
        domain = "R^n" if problem.neighborhood and problem.neighborhood.unbounded else "bounded N"
        return [
            f"Task type: {problem.task_type.value}",
            f"Stability kind: {kind}",
            f"Claimed domain: {domain}",
            f"Origin policy: {problem.origin_policy.value}",
        ]
