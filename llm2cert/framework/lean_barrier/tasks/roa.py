"""Define the region-of-attraction verification task."""
from __future__ import annotations

from ..s01_models import (
    CandidateSpec,
    Condition,
    ConditionKind,
    ConstExpr,
    DynamicsKind,
    ProblemSpec,
    Rational,
    RegionSpec,
    StabilityKind,
    TaskType,
)
from ..s02_expressions import evaluate_float, variables
from ..s04_semantics import SemanticError, closed_loop_framework_sentence, make_condition
from .lyapunov_common import (
    lyapunov_conditions,
    level_positive_query,
    roa_domain,
    sublevel_contains_initial_query,
    sublevel_in_neighborhood_query,
)


class RoaProfile:
    task_type = TaskType.ROA

    def validate(self, problem: ProblemSpec, candidate: CandidateSpec | None = None) -> None:
        if problem.task_type != TaskType.ROA:
            raise SemanticError("roa profile received a non-roa problem")
        if problem.neighborhood is None:
            raise SemanticError("region-of-attraction problems require a neighborhood N")
        if problem.equilibrium is None:
            raise SemanticError("region-of-attraction problems require an equilibrium")
        if not problem.neighborhood.unbounded:
            assert problem.neighborhood.region is not None
            if not _region_contains_equilibrium(
                problem.neighborhood.region,
                problem.system.state_vars,
                problem.equilibrium,
            ):
                raise SemanticError(
                    "the exact-ROA neighborhood N must contain the equilibrium; "
                    "epsilon annuli are source provenance only"
                )
        if problem.unsafe_set is not None:
            raise SemanticError("region-of-attraction problems must not declare an unsafe set")
        if problem.stability_kind not in (None, StabilityKind.LOCAL_ASYMPTOTIC):
            raise SemanticError("region-of-attraction uses local asymptotic conditions on Omega_c")
        if candidate is not None:
            if candidate.level_c is None:
                raise SemanticError("region-of-attraction candidates must give an exact level_c")
            names = variables(candidate.level_c)
            if names:
                raise SemanticError("region-of-attraction level_c must be state-independent")
            if (
                isinstance(candidate.level_c, ConstExpr)
                and candidate.level_c.value.numerator <= 0
            ):
                raise SemanticError("region-of-attraction candidates require level_c > 0")

    def build_conditions(
        self, problem: ProblemSpec, candidate: CandidateSpec
    ) -> tuple[Condition, ...]:
        self.validate(problem, candidate)
        from ..s04_semantics import candidate_semantics

        digest = candidate_semantics(problem, candidate).candidate_hash
        extras: list[Condition] = []
        if not isinstance(candidate.level_c, ConstExpr):
            extras.append(
                make_condition(
                    digest,
                    len(extras),
                    ConditionKind.LEVEL_POSITIVE,
                    "The exact sublevel constant c must be strictly positive.",
                    "level_positive",
                    level_positive_query(problem, candidate),
                )
            )
        if problem.initial_set is not None:
            extras.append(
                make_condition(
                    digest,
                    len(extras),
                    ConditionKind.SUBLEVEL_CONTAINS_INITIAL,
                    "No supplied initial state may satisfy V(x) > c.",
                    "sublevel_contains_initial",
                    sublevel_contains_initial_query(problem, candidate),
                )
            )
        assert problem.neighborhood is not None
        if problem.neighborhood.unbounded:
            extras.append(
                make_condition(
                    digest,
                    len(extras),
                    ConditionKind.RADIAL_UNBOUNDED,
                    (
                        "V is radially unbounded, so its exact finite sublevel "
                        "Omega_c is compact even though N = R^n. This does not "
                        "make the ROA claim global."
                    ),
                    "radial_unbounded",
                    None,
                )
            )
        else:
            extras.append(
                make_condition(
                    digest,
                    len(extras),
                    ConditionKind.SUBLEVEL_IN_NEIGHBORHOOD,
                    "No state with V(x) <= c may lie outside N.",
                    "sublevel_in_neighborhood",
                    sublevel_in_neighborhood_query(problem, candidate),
                )
            )
        return lyapunov_conditions(
            problem,
            candidate,
            domain=roa_domain(problem, candidate),
            kind=StabilityKind.LOCAL_ASYMPTOTIC,
            closing_kind=ConditionKind.ROA_INSTANTIATION,
            closing_description=(
                "Apply the audited exact region-of-attraction theorem: Omega_c is "
                "forward invariant and every admitted trajectory/iterate starting "
                "in Omega_c converges to the equilibrium."
                + (
                    " The separately supplied X_I is also contained in Omega_c."
                    if problem.initial_set is not None
                    else ""
                )
            ),
            closing_theorem=(
                "discrete_lyapunov_sublevel_is_roa"
                if problem.system.kind == DynamicsKind.DISCRETE
                else "continuous_lyapunov_sublevel_is_roa"
            ),
            extra_front=tuple(extras),
        )

    def synthesis_role(self, problem: ProblemSpec) -> str:
        extra = " and an explicit controller" if problem.system.control_vars else ""
        return (
            "You are a control theory expert specializing in Lyapunov functions and "
            f"regions of attraction. Propose one V and a positive exact level_c{extra}."
        )

    def synthesis_framework(self, problem: ProblemSpec) -> str:
        dpi = (
            "D_pi V = V(F(x)) - V(x)"
            if problem.system.kind == DynamicsKind.DISCRETE
            else "D_pi V = grad V · f"
        )
        closed = closed_loop_framework_sentence(problem, claimed_domain="Omega_c")
        extra = f"\n{closed}" if closed else ""
        initial_requirement = (
            "The supplied X_I is fixed and must satisfy X_I subseteq Omega_c.\n"
            if problem.initial_set is not None
            else "No separate X_I is supplied: certify Omega_c itself, never an empty-set surrogate.\n"
        )
        assert problem.neighborhood is not None
        if problem.neighborhood.unbounded:
            neighborhood_requirement = (
                "Here N = R^n, so Omega_c subseteq N is tautological and is not a "
                "proof obligation. Choose V radially unbounded/coercive so the exact "
                "finite sublevel Omega_c is compact. The supplied analysis_box is only "
                "for numerical FastCheck sampling and is not part of the formal domain.\n"
            )
            required = (
                f"Required: V(x*) = 0, V > 0 on Omega_c minus the equilibrium, "
                f"and {dpi} < 0 on that punctured sublevel set.\n"
            )
            conclusion = (
                "The conclusion is only that Omega_c is forward invariant and every "
                "trajectory/iterate starting in Omega_c converges to the equilibrium; "
                "do not claim that R^n is an ROA or that the result is global."
            )
        else:
            neighborhood_requirement = (
                "N is fixed by the problem. You may change V and the exact "
                "level_c; do not enlarge N and do not delete a ball around the origin.\n"
            )
            required = (
                f"Required: Omega_c subseteq N, V(x*) = 0, V > 0 on Omega_c minus "
                f"the equilibrium, and {dpi} < 0 on that punctured sublevel set.\n"
            )
            conclusion = (
                "The conclusion must be that Omega_c is forward invariant and every "
                "trajectory/iterate starting in Omega_c converges to the equilibrium. "
                "If c is too large, Omega_c leaves N or the decrease condition fails."
            )
        return (
            "The certificate is a Lyapunov function V. The claimed region is the "
            "sublevel set Omega_c = {x | V(x) <= c}, not a super-level set.\n"
            f"{neighborhood_requirement}"
            f"{initial_requirement}"
            f"{required}"
            f"{conclusion}"
            f"{extra}"
        )

    def synthesis_objective(self, problem: ProblemSpec) -> str:
        del problem
        return (
            "Propose V in the certificate expression string and an exact positive "
            "state-independent level_c string. Rational values, pi, and expressions such "
            "as sqrt(2) are accepted. Never write verified, "
            "proved, certified, UNSAT, or globally valid unless that result is already "
            "in the supplied evidence."
        )

    def brief_lines(self, problem: ProblemSpec) -> list[str]:
        assert problem.neighborhood is not None
        domain = (
            "Omega_c with N = R^n; analysis_box is numerical screening only"
            if problem.neighborhood.unbounded
            else "Omega_c inside bounded N containing the equilibrium"
        )
        lines = [
            f"Task type: {problem.task_type.value}",
            "Formal target: certify Omega_c itself as a forward-invariant ROA inner estimate",
            f"Claimed domain: {domain}",
            f"Origin policy: {problem.origin_policy.value}",
        ]
        lines.append(
            "Additional input: prove X_I subseteq Omega_c"
            if problem.initial_set is not None
            else "Additional input: no separate X_I"
        )
        return lines


def _region_contains_equilibrium(
    region: RegionSpec,
    variables: tuple[str, ...],
    equilibrium: tuple[Rational, ...],
) -> bool:
    environment = {
        name: value.numerator / value.denominator
        for name, value in zip(variables, equilibrium, strict=True)
    }

    def satisfies(constraint) -> bool:
        left = evaluate_float(constraint.lhs, environment)
        right = evaluate_float(constraint.rhs, environment)
        return {
            "lt": left < right,
            "le": left <= right,
            "eq": left == right,
            "ge": left >= right,
            "gt": left > right,
        }[constraint.relation.value]

    if region.bounds is not None:
        for name, value in environment.items():
            lower = region.bounds.lower[name]
            upper = region.bounds.upper[name]
            if value < lower.numerator / lower.denominator:
                return False
            if value > upper.numerator / upper.denominator:
                return False
    if not all(satisfies(constraint) for constraint in region.constraints):
        return False
    return not region.any_of or any(
        all(satisfies(constraint) for constraint in group.constraints)
        for group in region.any_of
    )
