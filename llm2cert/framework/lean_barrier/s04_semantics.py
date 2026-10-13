"""Validate mathematical problem and candidate constraints."""
from __future__ import annotations

from dataclasses import dataclass

from .s02_expressions import (
    ZERO,
    add,
    content_hash,
    differentiate,
    mul,
    pow_nat,
    substitute,
    validate_variables,
)
from .s01_models import (
    BoxSpec,
    CandidateSpec,
    ConstExpr,
    Constraint,
    ConstraintGroup,
    DynamicsKind,
    Expr,
    Condition,
    ConditionKind,
    ProblemSpec,
    QuerySpec,
    RegionSpec,
    Relation,
    VarExpr,
)


class SemanticError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateSemantics:
    candidate_hash: str
    closed_loop: tuple[Expr, ...]
    gradient: tuple[Expr, ...]
    lie_derivative: Expr | None
    next_barrier: Expr | None


def _bound_constraints(box: BoxSpec | None) -> tuple[Constraint, ...]:
    if box is None:
        return ()
    result: list[Constraint] = []
    from .s01_models import ConstExpr

    for name in sorted(box.lower):
        variable = VarExpr(name=name)
        result.append(
            Constraint(
                lhs=variable,
                relation=Relation.GE,
                rhs=ConstExpr(value=box.lower[name]),
            )
        )
        result.append(
            Constraint(
                lhs=variable,
                relation=Relation.LE,
                rhs=ConstExpr(value=box.upper[name]),
            )
        )
    return tuple(result)


def fixed_parameter_names(problem: ProblemSpec) -> tuple[str, ...]:


    return tuple(parameter.name for parameter in problem.fixed_parameters)


def fixed_parameter_box(problem: ProblemSpec) -> BoxSpec | None:


    if not problem.fixed_parameters:
        return None
    return BoxSpec(
        lower={parameter.name: parameter.lower for parameter in problem.fixed_parameters},
        upper={parameter.name: parameter.upper for parameter in problem.fixed_parameters},
    )


def _merge_disjoint_boxes(left: BoxSpec, right: BoxSpec) -> BoxSpec:
    overlap = set(left.lower) & set(right.lower)
    if overlap:
        raise SemanticError(f"state/parameter bounds overlap: {sorted(overlap)}")
    return BoxSpec(
        lower={**left.lower, **right.lower},
        upper={**left.upper, **right.upper},
    )


def fixed_parameter_screening_box(problem: ProblemSpec) -> BoxSpec:


    parameter_box = fixed_parameter_box(problem)
    if parameter_box is None:
        return problem.analysis_box
    return _merge_disjoint_boxes(problem.analysis_box, parameter_box)


def quantify_fixed_parameters(problem: ProblemSpec, query: QuerySpec) -> QuerySpec:


    parameter_box = fixed_parameter_box(problem)
    if parameter_box is None:
        return query
    parameter_names = fixed_parameter_names(problem)
    formal_bounds = (
        None
        if query.formal_bounds is None
        else _merge_disjoint_boxes(query.formal_bounds, parameter_box)
    )
    return query.model_copy(
        update={
            "variables": query.variables + parameter_names,
            "constraints": _bound_constraints(parameter_box) + query.constraints,
            "formal_bounds": formal_bounds,
        }
    )


def region_query(
    region: RegionSpec,
    variables: tuple[str, ...],
    extra: tuple[Constraint, ...],
    *,
    analysis_box: BoxSpec | None = None,
) -> QuerySpec:
    return QuerySpec(
        variables=variables,
        constraints=(
            _bound_constraints(analysis_box)
            + _bound_constraints(region.bounds)
            + region.constraints
            + extra
        ),
        any_of=region.any_of,
        formal_bounds=region.bounds or analysis_box,
    )


def validate_problem(problem: ProblemSpec) -> None:
    if problem.indexed_family is not None:


        return
    assert problem.system is not None
    states = set(problem.system.state_vars)
    parameters = set(fixed_parameter_names(problem))
    dynamics_allowed = states | set(problem.system.control_vars) | parameters
    for expression in problem.system.dynamics:
        validate_variables(expression, dynamics_allowed)
    regions = [problem.initial_set, problem.unsafe_set]
    if problem.neighborhood is not None:
        regions.append(problem.neighborhood.region)
    for region in regions:
        if region is None:
            continue
        for constraint in region.constraints:
            validate_variables(constraint.lhs, states)
            validate_variables(constraint.rhs, states)
        for group in region.any_of:
            for constraint in group.constraints:
                validate_variables(constraint.lhs, states)
                validate_variables(constraint.rhs, states)
        if region.bounds and set(region.bounds.lower) != states:
            raise SemanticError("formal region bounds must cover every state variable")


def candidate_semantics(problem: ProblemSpec, candidate: CandidateSpec) -> CandidateSemantics:
    validate_problem(problem)
    states = set(problem.system.state_vars)
    validate_variables(candidate.certificate_ast, states)

    expected_controls = set(problem.system.control_vars)
    actual_controls = [assignment.variable for assignment in candidate.controller_ast.assignments]
    if len(set(actual_controls)) != len(actual_controls):
        raise SemanticError("controller variables must be unique")
    if set(actual_controls) != expected_controls:
        missing = expected_controls - set(actual_controls)
        extra = set(actual_controls) - expected_controls
        raise SemanticError(
            f"controller assignments mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    replacements: dict[str, Expr] = {}
    for assignment in candidate.controller_ast.assignments:
        observations = problem.system.control_observations
        allowed_states = (
            states
            if observations is None
            else set(observations[assignment.variable])
        )
        try:
            validate_variables(assignment.expression, allowed_states)
        except ValueError as error:
            raise SemanticError(
                f"controller {assignment.variable} violates its observation pattern; "
                f"allowed states={sorted(allowed_states)}"
            ) from error
        replacements[assignment.variable] = assignment.expression

    closed_loop = tuple(
        substitute(expression, replacements) for expression in problem.system.dynamics
    )
    closed_loop_allowed = states | set(fixed_parameter_names(problem))
    for expression in closed_loop:
        validate_variables(expression, closed_loop_allowed)
    gradient = tuple(
        differentiate(candidate.certificate_ast, variable) for variable in problem.system.state_vars
    )
    lie: Expr | None = None
    next_barrier: Expr | None = None
    if problem.system.kind == DynamicsKind.CONTINUOUS:
        lie = add(*(mul(gradient[index], closed_loop[index]) for index in range(len(gradient))))
    else:
        next_barrier = substitute(
            candidate.certificate_ast,
            dict(zip(problem.system.state_vars, closed_loop, strict=True)),
        )
    return CandidateSemantics(
        candidate_hash=content_hash(candidate),
        closed_loop=closed_loop,
        gradient=gradient,
        lie_derivative=lie,
        next_barrier=next_barrier,
    )


def _in_X_query(
    problem: ProblemSpec,
    variables: tuple[str, ...],
    constraints: tuple[Constraint, ...],
) -> QuerySpec:


    if problem.formal_domain_unbounded:
        return QuerySpec(
            variables=variables,
            constraints=constraints,
            formal_bounds=None,
        )
    return QuerySpec(
        variables=variables,
        constraints=_bound_constraints(problem.analysis_box) + constraints,
        formal_bounds=problem.analysis_box,
    )


def control_admissible_query(
    problem: ProblemSpec,
    candidate: CandidateSpec,
    base: QuerySpec,
) -> QuerySpec | None:


    if problem.control_set is None:
        return None
    assigned = {
        assignment.variable: assignment.expression
        for assignment in candidate.controller_ast.assignments
    }
    groups: list[ConstraintGroup] = []
    box = problem.control_set
    for name in problem.system.control_vars:
        if name not in assigned:
            raise SemanticError(f"controller does not assign {name}")
        expression = assigned[name]
        groups.append(
            ConstraintGroup(
                constraints=(
                    Constraint(
                        lhs=expression,
                        relation=Relation.LT,
                        rhs=ConstExpr(value=box.lower[name]),
                    ),
                )
            )
        )
        groups.append(
            ConstraintGroup(
                constraints=(
                    Constraint(
                        lhs=expression,
                        relation=Relation.GT,
                        rhs=ConstExpr(value=box.upper[name]),
                    ),
                )
            )
        )
    return base.model_copy(update={"any_of": base.any_of + tuple(groups)})


def control_admissible_condition(
    problem: ProblemSpec,
    candidate: CandidateSpec,
    digest: str,
    index: int,
    base: QuerySpec,
    *,
    description: str,
) -> Condition | None:
    query = control_admissible_query(problem, candidate, base)
    if query is None:
        return None
    return make_condition(
        digest,
        index,
        ConditionKind.CONTROL_ADMISSIBLE,
        description,
        "control_admissible",
        query,
    )


def closed_loop_framework_sentence(
    problem: ProblemSpec, *, claimed_domain: str = "the claimed domain"
) -> str:


    if not problem.system.control_vars:
        return ""
    parts = [
        "All certificate checks use the closed-loop dynamics after substituting "
        "the given controller."
    ]
    if problem.control_set is not None:
        parts.append(
            f"The given controller must satisfy pi(x) in U on {claimed_domain}."
        )
    return " ".join(parts)


def make_condition(
    digest: str,
    index: int,
    kind: ConditionKind,
    description: str,
    theorem: str,
    query: QuerySpec | None,
    *,
    required: bool = True,
) -> Condition:
    return Condition(
        condition_id=f"{digest[:12]}:{index:02d}:{kind.value}",
        kind=kind,
        candidate_hash=digest,
        description=description,
        query=query,
        lean_theorem_name=theorem,
        required=required,
    )


def build_conditions(problem: ProblemSpec, candidate: CandidateSpec) -> tuple[Condition, ...]:


    from .tasks import profile_for

    return profile_for(problem).build_conditions(problem, candidate)
