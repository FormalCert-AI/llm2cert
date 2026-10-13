"""Construct shared Lyapunov and attraction obligations."""
from __future__ import annotations

from fractions import Fraction

from ..s01_models import (
    CandidateSpec,
    Condition,
    ConditionKind,
    ConstExpr,
    Constraint,
    ConstraintGroup,
    DynamicsKind,
    Expr,
    NeighborhoodSpec,
    OriginPolicy,
    ProblemSpec,
    QuerySpec,
    Rational,
    Relation,
    StabilityKind,
    VarExpr,
)
from ..s02_expressions import ZERO, add, const, mul, sub
from ..s04_semantics import (
    CandidateSemantics,
    SemanticError,
    candidate_semantics,
    control_admissible_condition,
    make_condition,
    region_query,
)


_GLOBAL_KINDS = {
    StabilityKind.GLOBAL_ASYMPTOTIC,
    StabilityKind.GLOBAL_EXPONENTIAL,
}
_EXPONENTIAL_KINDS = {
    StabilityKind.LOCAL_EXPONENTIAL,
    StabilityKind.GLOBAL_EXPONENTIAL,
}
_ASYMPTOTIC_KINDS = {
    StabilityKind.LOCAL_ASYMPTOTIC,
    StabilityKind.GLOBAL_ASYMPTOTIC,
    StabilityKind.LOCAL_EXPONENTIAL,
    StabilityKind.GLOBAL_EXPONENTIAL,
}


def is_global_kind(kind: StabilityKind) -> bool:
    return kind in _GLOBAL_KINDS


def dreal_positive_allowed(kind: StabilityKind) -> bool:
    return not is_global_kind(kind)


def _as_fraction(value: Rational) -> Fraction:
    return Fraction(value.numerator, value.denominator)


def _const(value: Rational | int | Fraction | ConstExpr) -> ConstExpr:
    if isinstance(value, ConstExpr):
        return value
    if isinstance(value, Rational):
        return ConstExpr(value=value)
    return const(value)


def squared_norm(variables: tuple[str, ...]):
    from ..s02_expressions import pow_nat

    return add(*(pow_nat(VarExpr(name=name), 2) for name in variables))


def decrease_rate(
    problem: ProblemSpec, semantics: CandidateSemantics, certificate: Expr
) -> Expr:


    if problem.system.kind == DynamicsKind.CONTINUOUS:
        if semantics.lie_derivative is None:
            raise SemanticError("continuous Lyapunov conditions require a Lie derivative")
        return semantics.lie_derivative
    if semantics.next_barrier is None:
        raise SemanticError("discrete Lyapunov conditions require V(F(x))")
    return sub(semantics.next_barrier, certificate)


def origin_away_constraint(problem: ProblemSpec) -> Constraint:


    variables = problem.system.state_vars
    if problem.origin_policy == OriginPolicy.EXCLUDE_BALL:
        if problem.source_domain is None or problem.source_domain.inner_radius is None:
            raise SemanticError("exclude_ball requires source_domain.inner_radius")
        radius = _as_fraction(problem.source_domain.inner_radius)
        return Constraint(
            lhs=squared_norm(variables),
            relation=Relation.GE,
            rhs=_const(radius * radius),
        )
    return Constraint(lhs=squared_norm(variables), relation=Relation.GT, rhs=ZERO)


def domain_query(
    problem: ProblemSpec,
    neighborhood: NeighborhoodSpec | None,
    extra: tuple[Constraint, ...],
    *,
    punctured: bool,
) -> QuerySpec:
    constraints = extra

    if punctured and problem.origin_policy != OriginPolicy.INCLUDE_ORIGIN:
        constraints = (origin_away_constraint(problem),) + constraints

    if neighborhood is None or neighborhood.unbounded:
        return QuerySpec(
            variables=problem.system.state_vars,
            constraints=constraints,
            formal_bounds=None,
        )
    assert neighborhood.region is not None
    return region_query(
        neighborhood.region,
        problem.system.state_vars,
        constraints,
        analysis_box=None,
    )


def lyapunov_conditions(
    problem: ProblemSpec,
    candidate: CandidateSpec,
    *,
    domain: NeighborhoodSpec | None,
    kind: StabilityKind,
    closing_kind: ConditionKind,
    closing_description: str,
    closing_theorem: str,
    extra_front: tuple[Condition, ...] = (),
) -> tuple[Condition, ...]:
    if problem.equilibrium is None or any(
        _as_fraction(value) != 0 for value in problem.equilibrium
    ):
        raise SemanticError("first-version Lyapunov tasks require equilibrium at the origin")

    semantics = candidate_semantics(problem, candidate)
    dpi = decrease_rate(problem, semantics, candidate.certificate_ast)
    digest = semantics.candidate_hash
    v = candidate.certificate_ast
    discrete = problem.system.kind == DynamicsKind.DISCRETE
    result = list(extra_front)

    def add_condition(
        kind_name: ConditionKind,
        description: str,
        theorem: str,
        query: QuerySpec | None,
        *,
        required: bool = True,
    ) -> None:
        result.append(
            make_condition(
                digest,
                len(result),
                kind_name,
                description,
                theorem,
                query,
                required=required,
            )
        )

    if not discrete:
        add_condition(
            ConditionKind.BARRIER_C1,
            "The certificate is C¹; this is the hypothesis (hV : ContDiff ℝ 1 V).",
            "barrier_c1",
            None,
        )
    control = control_admissible_condition(
        problem,
        candidate,
        digest,
        len(result),
        domain_query(problem, domain, (), punctured=False),
        description=(
            "Given the candidate controller, there is no point of the claimed "
            "domain where pi(x) leaves U."
        ),
    )
    if control is not None:
        result.append(control)

    origin_eq = tuple(
        Constraint(lhs=VarExpr(name=name), relation=Relation.EQ, rhs=ZERO)
        for name in problem.system.state_vars
    )
    equilibrium_failure = tuple(
        ConstraintGroup(
            constraints=(Constraint(lhs=component, relation=relation, rhs=ZERO),)
        )
        for component in semantics.closed_loop
        for relation in (Relation.GT, Relation.LT)
    )
    add_condition(
        ConditionKind.EQUILIBRIUM_FIXED,
        (
            "The closed-loop vector field must vanish at the equilibrium."
            if not discrete
            else "The closed-loop one-step map must fix the equilibrium."
        ),
        "equilibrium_fixed",
        QuerySpec(
            variables=problem.system.state_vars,
            constraints=origin_eq,
            any_of=equilibrium_failure,
            formal_bounds=None,
        ),
    )
    add_condition(
        ConditionKind.V_AT_EQUILIBRIUM,
        "V must vanish at the equilibrium.",
        "v_at_equilibrium",
        QuerySpec(
            variables=problem.system.state_vars,
            constraints=origin_eq,
            any_of=(
                ConstraintGroup(
                    constraints=(Constraint(lhs=v, relation=Relation.GT, rhs=ZERO),)
                ),
                ConstraintGroup(
                    constraints=(Constraint(lhs=v, relation=Relation.LT, rhs=ZERO),)
                ),
            ),


            formal_bounds=None,
        ),
    )
    add_condition(
        ConditionKind.POSITIVE_DEFINITE,
        "V must be positive away from the equilibrium on the claimed domain.",
        "positive_definite",
        domain_query(
            problem,
            domain,
            (Constraint(lhs=v, relation=Relation.LE, rhs=ZERO),),
            punctured=True,
        ),
    )

    if kind == StabilityKind.LOCAL_LYAPUNOV:
        add_condition(
            ConditionKind.LIE_NONPOSITIVE,
            "There is no point on the claimed domain with D_pi V > 0.",
            "lie_nonpositive",
            domain_query(
                problem,
                domain,
                (Constraint(lhs=dpi, relation=Relation.GT, rhs=ZERO),),
                punctured=False,
            ),
        )
    elif kind in _ASYMPTOTIC_KINDS and kind not in _EXPONENTIAL_KINDS:
        add_condition(
            ConditionKind.LIE_NEGATIVE,
            "There is no point away from the equilibrium with D_pi V >= 0.",
            "lie_negative",
            domain_query(
                problem,
                domain,
                (Constraint(lhs=dpi, relation=Relation.GE, rhs=ZERO),),
                punctured=True,
            ),
        )

    if kind in _EXPONENTIAL_KINDS:
        c1, c2, c3 = _require_exp_constants(candidate, discrete=discrete)
        r2 = squared_norm(problem.system.state_vars)
        add_condition(
            ConditionKind.QUADRATIC_LOWER,
            "There is no point on the claimed domain with V < c1 ||x||^2.",
            "quadratic_lower",
            domain_query(
                problem,
                domain,
                (Constraint(lhs=v, relation=Relation.LT, rhs=mul(c1, r2)),),
                punctured=False,
            ),
        )
        add_condition(
            ConditionKind.QUADRATIC_UPPER,
            "There is no point on the claimed domain with V > c2 ||x||^2.",
            "quadratic_upper",
            domain_query(
                problem,
                domain,
                (Constraint(lhs=v, relation=Relation.GT, rhs=mul(c2, r2)),),
                punctured=False,
            ),
        )
        decay = add(dpi, mul(c3, v))
        add_condition(
            ConditionKind.EXPONENTIAL_DECAY,
            "There is no point on the claimed domain with D_pi V + c3 V > 0.",
            "exponential_decay",
            domain_query(
                problem,
                domain,
                (Constraint(lhs=decay, relation=Relation.GT, rhs=ZERO),),
                punctured=False,
            ),
        )

    if kind == StabilityKind.GLOBAL_ASYMPTOTIC:


        add_condition(
            ConditionKind.RADIAL_UNBOUNDED,
            "V is radially unbounded: ||x|| → ∞ implies V(x) → ∞.",
            "radial_unbounded",
            None,
        )

    add_condition(closing_kind, closing_description, closing_theorem, None)
    return tuple(result)


def _require_exp_constants(
    candidate: CandidateSpec, *, discrete: bool
) -> tuple[ConstExpr, ConstExpr, ConstExpr]:
    if candidate.exp_c1 is None or candidate.exp_c2 is None or candidate.exp_c3 is None:
        raise SemanticError("exponential stability requires candidate exp_c1, exp_c2, exp_c3")
    c1 = _as_fraction(candidate.exp_c1)
    c2 = _as_fraction(candidate.exp_c2)
    c3 = _as_fraction(candidate.exp_c3)
    if c1 <= 0 or c2 <= 0 or c3 <= 0:
        raise SemanticError("exponential constants must be positive rationals")
    if c1 > c2:
        raise SemanticError("exponential constants require 0 < c1 <= c2")
    if discrete and c3 > 1:
        raise SemanticError("discrete exponential stability requires 0 < exp_c3 <= 1")
    return _const(candidate.exp_c1), _const(candidate.exp_c2), _const(candidate.exp_c3)


def require_level_c(candidate: CandidateSpec) -> Expr:
    if candidate.level_c is None:
        raise SemanticError("region-of-attraction candidates must give an exact level_c")
    return candidate.level_c


def level_positive_query(problem: ProblemSpec, candidate: CandidateSpec) -> QuerySpec:


    level = require_level_c(candidate)
    return QuerySpec(
        variables=problem.system.state_vars,
        constraints=(Constraint(lhs=level, relation=Relation.LE, rhs=ZERO),),
        formal_bounds=None,
    )


def sublevel_contains_initial_query(problem: ProblemSpec, candidate: CandidateSpec) -> QuerySpec:
    if problem.initial_set is None:
        raise SemanticError("region-of-attraction problems require an initial set")
    level = require_level_c(candidate)
    return region_query(
        problem.initial_set,
        problem.system.state_vars,
        (Constraint(lhs=candidate.certificate_ast, relation=Relation.GT, rhs=level),),
        analysis_box=None,
    )


def sublevel_in_neighborhood_query(problem: ProblemSpec, candidate: CandidateSpec) -> QuerySpec:
    if problem.neighborhood is None or problem.neighborhood.unbounded or problem.neighborhood.region is None:
        raise SemanticError("region-of-attraction problems require a bounded neighborhood")
    if problem.neighborhood.region.any_of:
        raise SemanticError("first-version Omega_c ⊆ N does not support any_of neighborhoods")
    level = require_level_c(candidate)
    return QuerySpec(
        variables=problem.system.state_vars,
        constraints=(
            Constraint(lhs=candidate.certificate_ast, relation=Relation.LE, rhs=level),
        ),
        any_of=_region_failure_groups(problem.neighborhood.region, problem.system.state_vars),
        formal_bounds=None,
    )


def _region_failure_groups(region, state_vars: tuple[str, ...]) -> tuple[ConstraintGroup, ...]:
    groups: list[ConstraintGroup] = []
    if region.bounds is not None:
        for name in state_vars:
            variable = VarExpr(name=name)
            groups.append(
                ConstraintGroup(
                    constraints=(
                        Constraint(
                            lhs=variable,
                            relation=Relation.LT,
                            rhs=_const(region.bounds.lower[name]),
                        ),
                    )
                )
            )
            groups.append(
                ConstraintGroup(
                    constraints=(
                        Constraint(
                            lhs=variable,
                            relation=Relation.GT,
                            rhs=_const(region.bounds.upper[name]),
                        ),
                    )
                )
            )
    for constraint in region.constraints:
        groups.append(ConstraintGroup(constraints=(_negate(constraint),)))
    if not groups:
        raise SemanticError("neighborhood complement is empty; N has no constraints or bounds")
    return tuple(groups)


def _negate(constraint: Constraint) -> Constraint:
    flipped = {
        Relation.LT: Relation.GE,
        Relation.LE: Relation.GT,
        Relation.GT: Relation.LE,
        Relation.GE: Relation.LT,
        Relation.EQ: Relation.GT,
    }[constraint.relation]
    return Constraint(lhs=constraint.lhs, relation=flipped, rhs=constraint.rhs)


def roa_domain(problem: ProblemSpec, candidate: CandidateSpec) -> NeighborhoodSpec:


    from ..s01_models import RegionSpec

    level = require_level_c(candidate)
    omega = Constraint(lhs=candidate.certificate_ast, relation=Relation.LE, rhs=level)
    assert problem.neighborhood is not None
    if problem.neighborhood.unbounded:
        return NeighborhoodSpec(
            unbounded=False,
            region=RegionSpec(constraints=(omega,)),
        )
    assert problem.neighborhood.region is not None
    base = problem.neighborhood.region
    return NeighborhoodSpec(
        unbounded=False,
        region=RegionSpec(
            constraints=base.constraints + (omega,),
            any_of=base.any_of,
            bounds=base.bounds,
        ),
    )
