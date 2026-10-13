"""Construct shared safety and invariance obligations."""
from __future__ import annotations

from ..s01_models import (
    CandidateSpec,
    Condition,
    ConditionKind,
    ConstExpr,
    Constraint,
    ConstraintGroup,
    DynamicsKind,
    ProblemSpec,
    QuerySpec,
    Relation,
    VarExpr,
)
from ..s02_expressions import ZERO
from ..s04_semantics import (
    SemanticError,
    _in_X_query,
    candidate_semantics,
    control_admissible_condition,
    make_condition,
    quantify_fixed_parameters,
    region_query,
)


def _ge0(expr) -> Constraint:
    return Constraint(lhs=expr, relation=Relation.GE, rhs=ZERO)


def _lt0(expr) -> Constraint:
    return Constraint(lhs=expr, relation=Relation.LT, rhs=ZERO)


def _le0(expr) -> Constraint:
    return Constraint(lhs=expr, relation=Relation.LE, rhs=ZERO)


def _eq0(expr) -> Constraint:
    return Constraint(lhs=expr, relation=Relation.EQ, rhs=ZERO)


def _outside_X_with_nonneg_barrier(problem: ProblemSpec, barrier) -> QuerySpec:
    outside: list[ConstraintGroup] = []
    box = problem.analysis_box
    for name in box.lower:
        variable = VarExpr(name=name)
        outside.append(
            ConstraintGroup(
                constraints=(
                    Constraint(
                        lhs=variable,
                        relation=Relation.LT,
                        rhs=ConstExpr(value=box.lower[name]),
                    ),
                )
            )
        )
        outside.append(
            ConstraintGroup(
                constraints=(
                    Constraint(
                        lhs=variable,
                        relation=Relation.GT,
                        rhs=ConstExpr(value=box.upper[name]),
                    ),
                )
            )
        )
    return QuerySpec(
        variables=problem.system.state_vars,
        constraints=(_ge0(barrier),),
        any_of=tuple(outside),
        formal_bounds=None,
    )


def barrier_conditions(
    problem: ProblemSpec,
    candidate: CandidateSpec,
    *,
    include_initial: bool,
    closing_kind: ConditionKind,
    closing_description: str,
    closing_theorem: str,
    require_certified_in_x: bool = False,
) -> tuple[Condition, ...]:
    if problem.unsafe_set is None:
        raise SemanticError("barrier tasks require an unsafe set")
    semantics = candidate_semantics(problem, candidate)
    digest = semantics.candidate_hash
    variables = problem.system.state_vars
    barrier = candidate.certificate_ast
    result: list[Condition] = []
    formal_box = None if problem.formal_domain_unbounded else problem.analysis_box

    def add_condition(
        kind: ConditionKind,
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
                kind,
                description,
                theorem,
                query,
                required=required,
            )
        )

    add_condition(
        ConditionKind.UNSAFE_SEPARATION,
        "No unsafe state in X may satisfy B(x) >= 0.",
        "unsafe_separation",
        region_query(
            problem.unsafe_set,
            variables,
            (_ge0(barrier),),
            analysis_box=formal_box,
        ),
    )
    if include_initial and problem.initial_set is not None:
        add_condition(
            ConditionKind.INITIAL_CONTAINMENT,
            "No initial state in X may satisfy B(x) < 0.",
            "initial_containment",
            region_query(
                problem.initial_set,
                variables,
                (_lt0(barrier),),
                analysis_box=formal_box,
            ),
        )
    if require_certified_in_x:
        add_condition(
            ConditionKind.CERTIFIED_SET_IN_X,
            "No state with B(x) >= 0 may lie outside the working domain X.",
            "certified_set_in_X",
            _outside_X_with_nonneg_barrier(problem, barrier),
        )
    add_condition(
        ConditionKind.BARRIER_C1,
        "The barrier is C¹; this is the hypothesis (hV : ContDiff ℝ 1 V).",
        "barrier_c1",
        None,
    )
    control = control_admissible_condition(
        problem,
        candidate,
        digest,
        len(result),
        _in_X_query(problem, variables, ()),
        description=(
            "Given the candidate controller, there is no point in X where pi(x) leaves U."
        ),
    )
    if control is not None:
        result.append(control)

    if problem.system.kind == DynamicsKind.CONTINUOUS:
        assert semantics.lie_derivative is not None
        add_condition(
            ConditionKind.LIE_STRICT,
            (
                "There is no point in X and no admissible fixed parameter with "
                "B=0 and L_f B <= 0."
                if problem.fixed_parameters
                else "There is no point in X with B=0 and L_f B <= 0."
            ),
            "lie_strict",
            quantify_fixed_parameters(
                problem,
                _in_X_query(
                    problem,
                    variables,
                    (_eq0(barrier), _le0(semantics.lie_derivative)),
                ),
            ),
        )
    else:
        assert semantics.next_barrier is not None
        add_condition(
            ConditionKind.DISCRETE_INDUCTIVE,
            "There is no state in X with B(x)>=0 and B(f_cl(x))<0.",
            "discrete_inductive",
            quantify_fixed_parameters(
                problem,
                _in_X_query(
                    problem,
                    variables,
                    (_ge0(barrier), _lt0(semantics.next_barrier)),
                ),
            ),
        )

    add_condition(closing_kind, closing_description, closing_theorem, None)
    return tuple(result)
