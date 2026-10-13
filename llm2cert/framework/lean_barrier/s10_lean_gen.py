"""Generate Lean definitions and proof obligations."""
from __future__ import annotations

from dataclasses import dataclass

from fractions import Fraction

from .s02_expressions import const, content_hash, mul
from .s01_models import (
    AddExpr,
    AtanExpr,
    CandidateSpec,
    ConstExpr,
    Constraint,
    CosExpr,
    DivExpr,
    ExpExpr,
    Expr,
    LogExpr,
    MulExpr,
    NegExpr,
    PiExpr,
    Condition,
    PowExpr,
    ProblemSpec,
    QuerySpec,
    Relation,
    SinExpr,
    SqrtExpr,
    SubExpr,
    TanhExpr,
    VarExpr,
    ConditionKind,
)
from .s04_semantics import candidate_semantics, region_query


@dataclass(frozen=True)
class LockedTheorem:
    candidate_hash: str
    theorem_name: str
    definitions: str
    statement: str
    definition_check_name: str | None = None

    @property
    def statement_hash(self) -> str:
        return content_hash(self.statement)


def expr_to_lean(
    expr: Expr,
    state_indices: dict[str, int],
    state_name: str = "x",
    scalar_names: frozenset[str] = frozenset(),
) -> str:
    if isinstance(expr, ConstExpr):
        numerator = expr.value.numerator
        denominator = expr.value.denominator
        if denominator == 1:
            return f"({numerator} : ℝ)"
        return f"(({numerator} : ℝ) / ({denominator} : ℝ))"
    if isinstance(expr, PiExpr):
        return "Real.pi"
    if isinstance(expr, VarExpr):
        if expr.name in state_indices:
            return f"{state_name} {state_indices[expr.name]}"
        if expr.name in scalar_names:
            return expr.name
        raise ValueError(f"unbound Lean expression variable: {expr.name}")
    if isinstance(expr, AddExpr):
        return (
            "("
            + " + ".join(
                expr_to_lean(arg, state_indices, state_name, scalar_names)
                for arg in expr.args
            )
            + ")"
        )
    if isinstance(expr, SubExpr):
        return (
            f"({expr_to_lean(expr.left, state_indices, state_name, scalar_names)} - "
            f"{expr_to_lean(expr.right, state_indices, state_name, scalar_names)})"
        )
    if isinstance(expr, DivExpr):
        return (
            f"({expr_to_lean(expr.left, state_indices, state_name, scalar_names)} / "
            f"{expr_to_lean(expr.right, state_indices, state_name, scalar_names)})"
        )
    if isinstance(expr, MulExpr):
        return (
            "("
            + " * ".join(
                expr_to_lean(arg, state_indices, state_name, scalar_names)
                for arg in expr.args
            )
            + ")"
        )
    if isinstance(expr, NegExpr):
        return f"(-{expr_to_lean(expr.arg, state_indices, state_name, scalar_names)})"
    if isinstance(expr, PowExpr):
        return (
            f"({expr_to_lean(expr.base, state_indices, state_name, scalar_names)} "
            f"^ {expr.exponent})"
        )


    if isinstance(expr, SinExpr):
        return f"Real.sin ({expr_to_lean(expr.arg, state_indices, state_name, scalar_names)})"
    if isinstance(expr, CosExpr):
        return f"Real.cos ({expr_to_lean(expr.arg, state_indices, state_name, scalar_names)})"
    if isinstance(expr, ExpExpr):
        return f"Real.exp ({expr_to_lean(expr.arg, state_indices, state_name, scalar_names)})"
    if isinstance(expr, TanhExpr):
        return f"Real.tanh ({expr_to_lean(expr.arg, state_indices, state_name, scalar_names)})"
    if isinstance(expr, LogExpr):
        return f"Real.log ({expr_to_lean(expr.arg, state_indices, state_name, scalar_names)})"
    if isinstance(expr, SqrtExpr):
        return f"Real.sqrt ({expr_to_lean(expr.arg, state_indices, state_name, scalar_names)})"
    if isinstance(expr, AtanExpr):
        return f"Real.arctan ({expr_to_lean(expr.arg, state_indices, state_name, scalar_names)})"
    raise TypeError(type(expr))


def expr_to_lean_dsl(expr: Expr, state_indices: dict[str, int]) -> str:
    if isinstance(expr, ConstExpr):
        numerator = expr.value.numerator
        denominator = expr.value.denominator
        value = (
            f"({numerator} : ℚ)"
            if denominator == 1
            else f"(({numerator} : ℚ) / ({denominator} : ℚ))"
        )
        return f".const {value}"
    if isinstance(expr, PiExpr):
        return ".pi"
    if isinstance(expr, VarExpr):
        return f".var {state_indices[expr.name]}"
    if isinstance(expr, AddExpr):
        rendered = expr_to_lean_dsl(expr.args[0], state_indices)
        for argument in expr.args[1:]:
            rendered = f".add ({rendered}) ({expr_to_lean_dsl(argument, state_indices)})"
        return rendered
    if isinstance(expr, SubExpr):
        return (
            f".sub ({expr_to_lean_dsl(expr.left, state_indices)}) "
            f"({expr_to_lean_dsl(expr.right, state_indices)})"
        )
    if isinstance(expr, DivExpr):
        if isinstance(expr.right, ConstExpr) and expr.right.value.numerator != 0:
            reciprocal = 1 / Fraction(expr.right.value.numerator, expr.right.value.denominator)
            return expr_to_lean_dsl(mul(expr.left, const(reciprocal)), state_indices)
        return (
            f".div ({expr_to_lean_dsl(expr.left, state_indices)}) "
            f"({expr_to_lean_dsl(expr.right, state_indices)})"
        )
    if isinstance(expr, MulExpr):
        rendered = expr_to_lean_dsl(expr.args[0], state_indices)
        for argument in expr.args[1:]:
            rendered = f".mul ({rendered}) ({expr_to_lean_dsl(argument, state_indices)})"
        return rendered
    if isinstance(expr, NegExpr):
        return f".neg ({expr_to_lean_dsl(expr.arg, state_indices)})"
    if isinstance(expr, PowExpr):
        return f".pow ({expr_to_lean_dsl(expr.base, state_indices)}) {expr.exponent}"
    if isinstance(expr, SinExpr):
        return f".sin ({expr_to_lean_dsl(expr.arg, state_indices)})"
    if isinstance(expr, CosExpr):
        return f".cos ({expr_to_lean_dsl(expr.arg, state_indices)})"
    if isinstance(expr, ExpExpr):
        return f".exp ({expr_to_lean_dsl(expr.arg, state_indices)})"
    if isinstance(expr, TanhExpr):
        return f".tanh ({expr_to_lean_dsl(expr.arg, state_indices)})"
    if isinstance(expr, LogExpr):
        return f".log ({expr_to_lean_dsl(expr.arg, state_indices)})"
    if isinstance(expr, SqrtExpr):
        return f".sqrt ({expr_to_lean_dsl(expr.arg, state_indices)})"
    if isinstance(expr, AtanExpr):
        return f".atan ({expr_to_lean_dsl(expr.arg, state_indices)})"
    raise TypeError(type(expr))


_RELATIONS = {
    Relation.LT: "<",
    Relation.LE: "≤",
    Relation.EQ: "=",
    Relation.GE: "≥",
    Relation.GT: ">",
}


def constraint_to_lean(
    constraint: Constraint,
    indices: dict[str, int],
    scalar_names: frozenset[str] = frozenset(),
) -> str:
    return (
        f"({expr_to_lean(constraint.lhs, indices, scalar_names=scalar_names)} "
        f"{_RELATIONS[constraint.relation]} "
        f"{expr_to_lean(constraint.rhs, indices, scalar_names=scalar_names)})"
    )


def query_formula_to_lean(
    query: QuerySpec,
    indices: dict[str, int],
    scalar_names: frozenset[str] = frozenset(),
) -> str:
    shared = [
        constraint_to_lean(constraint, indices, scalar_names)
        for constraint in query.constraints
    ]
    if query.any_of:
        branches = []
        for group in query.any_of:
            atoms = [
                constraint_to_lean(constraint, indices, scalar_names)
                for constraint in group.constraints
            ]
            branches.append("True" if not atoms else "(" + " ∧ ".join(atoms) + ")")
        shared.append("(" + " ∨ ".join(branches) + ")")
    return "True" if not shared else "(" + " ∧ ".join(shared) + ")"


def generate_locked_theorem(
    problem: ProblemSpec,
    candidate: CandidateSpec,
    condition: Condition,
) -> LockedTheorem:
    semantics = candidate_semantics(problem, candidate)
    if condition.candidate_hash != semantics.candidate_hash:
        raise ValueError("condition candidate hash does not match fixed candidate")
    if condition.kind in {
        ConditionKind.SAFETY_INSTANTIATION,
        ConditionKind.INVARIANT_INSTANTIATION,
        ConditionKind.STABILITY_INSTANTIATION,
        ConditionKind.ROA_INSTANTIATION,
    }:
        raise ValueError(
            "closing conditions use the axiom-audited generic Lean library; "
            "they are not per-candidate Proof Agent goals"
        )
    dimension = len(problem.system.state_vars)
    indices = {name: index for index, name in enumerate(problem.system.state_vars)}
    suffix = semantics.candidate_hash[:12]
    barrier_name = f"barrier_{suffix}"
    barrier_unfold_name = f"barrier_unfold_{suffix}"
    flow_name = f"closedLoop_{suffix}"
    working_name = f"workingSet_{suffix}"
    violation_name = f"violationSet_{condition.kind.value}_{suffix}"
    unsafe_name = f"unsafeSet_{suffix}"
    initial_name = f"initialSet_{suffix}"
    query_scalar_names: tuple[str, ...] = ()
    if condition.query is not None:
        query_scalar_names = tuple(
            name for name in condition.query.variables if name not in indices
        )
        declared_parameters = {parameter.name for parameter in problem.fixed_parameters}
        undeclared = set(query_scalar_names) - declared_parameters
        if undeclared:
            raise ValueError(
                "locked query contains non-state variables that are not declared fixed "
                f"parameters: {sorted(undeclared)}"
            )
    query_scalar_set = frozenset(query_scalar_names)
    definition_lines = [
        f"-- candidate-sha256: {semantics.candidate_hash}",
        f"noncomputable def {barrier_name} (x : LeanBarrier.State {dimension}) : ℝ := "
        f"{expr_to_lean(candidate.certificate_ast, indices)}",
        f"@[simp] theorem {barrier_unfold_name} (x : LeanBarrier.State {dimension}) : "
        f"{barrier_name} x = {expr_to_lean(candidate.certificate_ast, indices)} := by\n"
        f"  rfl",
    ]
    needs_flow = (
        condition.kind == ConditionKind.DISCRETE_INDUCTIVE
        and problem.system.kind.value == "discrete"
    )
    if needs_flow:
        flow_values = ", ".join(
            expr_to_lean(expression, indices) for expression in semantics.closed_loop
        )
        definition_lines.append(
            f"noncomputable def {flow_name} (x : LeanBarrier.State {dimension}) : "
            f"LeanBarrier.State {dimension} := ![{flow_values}]"
        )
        for index, expression in enumerate(semantics.closed_loop):
            definition_lines.append(
                f"@[simp] theorem closedLoop_apply_{index}_{suffix} "
                f"(x : LeanBarrier.State {dimension}) : {flow_name} x {index} = "
                f"{expr_to_lean(expression, indices)} := by\n"
                f"  simp [{flow_name}]"
            )
    if condition.kind == ConditionKind.DISCRETE_INDUCTIVE:
        if condition.query is None or len(condition.query.constraints) < 2:
            raise ValueError("discrete inductive condition is missing its locked query")
        if semantics.next_barrier is None:
            raise ValueError("discrete inductive condition requires discrete dynamics")
        expected_tail = (
            Constraint(
                lhs=candidate.certificate_ast,
                relation=Relation.GE,
                rhs=const(0),
            ),
            Constraint(
                lhs=semantics.next_barrier,
                relation=Relation.LT,
                rhs=const(0),
            ),
        )
        actual_tail = condition.query.constraints[-2:]
        if tuple(map(content_hash, actual_tail)) != tuple(map(content_hash, expected_tail)):
            raise ValueError(
                "discrete inductive query must end with locked B(x) >= 0 and "
                "B(closedLoop(x)) < 0 constraints"
            )


        domain_query = condition.query.model_copy(
            update={"constraints": condition.query.constraints[:-2]}
        )
        domain_formula = query_formula_to_lean(domain_query, indices)
        definition_lines.append(
            f"def {working_name} : Set (LeanBarrier.State {dimension}) := "
            f"{{x | {domain_formula}}}"
        )
    elif condition.query is not None:


        violation_formula = query_formula_to_lean(
            condition.query, indices, query_scalar_set
        )
        if query_scalar_names:
            scalar_binders = "".join(
                f" ({name} : ℝ)" for name in query_scalar_names
            )
            definition_lines.append(
                f"def {violation_name} (x : LeanBarrier.State {dimension})"
                f"{scalar_binders} : Prop := {violation_formula}"
            )
        else:
            definition_lines.append(
                f"def {violation_name} : Set (LeanBarrier.State {dimension}) := "
                f"{{x | {violation_formula}}}"
            )
    if problem.unsafe_set is not None:
        unsafe_formula = query_formula_to_lean(
            region_query(problem.unsafe_set, problem.system.state_vars, ()), indices
        )
        definition_lines.append(
            f"def {unsafe_name} : Set (LeanBarrier.State {dimension}) := {{x | {unsafe_formula}}}"
        )
    if problem.initial_set is not None:
        initial_formula = query_formula_to_lean(
            region_query(problem.initial_set, problem.system.state_vars, ()), indices
        )
        definition_lines.append(
            f"def {initial_name} : Set (LeanBarrier.State {dimension}) := {{x | {initial_formula}}}"
        )
    definitions = "\n".join(definition_lines)
    theorem_name = f"verify_{condition.kind.value}_{suffix}"
    if condition.kind == ConditionKind.RADIAL_UNBOUNDED:
        proposition = f"LeanBarrier.Lyapunov.RadiallyUnbounded {barrier_name}"
    elif condition.kind == ConditionKind.DISCRETE_INDUCTIVE:
        proposition = (
            f"¬ ∃ x : LeanBarrier.State {dimension}, x ∈ {working_name} ∧ "
            f"{barrier_name} x ≥ 0 ∧ {barrier_name} ({flow_name} x) < 0"
        )
    elif condition.query is not None:
        if query_scalar_names:
            scalar_exists = "".join(
                f"∃ {name} : ℝ, " for name in query_scalar_names
            )
            scalar_arguments = " ".join(query_scalar_names)
            proposition = (
                f"¬ ∃ x : LeanBarrier.State {dimension}, {scalar_exists}"
                f"{violation_name} x {scalar_arguments}"
            )
        else:
            proposition = (
                f"¬ ∃ x : LeanBarrier.State {dimension}, x ∈ {violation_name}"
            )
    else:
        proposition = "True"
    statement = (
        f"theorem {theorem_name} (hV : ContDiff ℝ 1 {barrier_name}) : {proposition}"
    )
    return LockedTheorem(
        candidate_hash=semantics.candidate_hash,
        theorem_name=theorem_name,
        definitions=definitions,
        statement=statement,
        definition_check_name=barrier_unfold_name,
    )
