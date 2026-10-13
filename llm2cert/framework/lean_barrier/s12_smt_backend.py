"""Run compatible SMT solvers on counterexample queries."""
from __future__ import annotations

from .s02_expressions import contains_transcendentals
from .s01_models import (
    AddExpr,
    AtanExpr,
    Backend,
    BoxSpec,
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
    PowExpr,
    QuerySpec,
    Relation,
    SinExpr,
    SqrtExpr,
    SubExpr,
    TanhExpr,
    VarExpr,
)


def _integer(value: int) -> str:
    return str(value) if value >= 0 else f"(- {abs(value)})"


def expr_to_smt(expr: Expr, backend: Backend) -> str:
    if isinstance(expr, ConstExpr):
        numerator = expr.value.numerator
        denominator = expr.value.denominator
        if denominator == 1:
            return _integer(numerator)
        positive = f"(/ {abs(numerator)} {denominator})"
        return positive if numerator >= 0 else f"(- {positive})"
    if isinstance(expr, PiExpr):
        if backend == Backend.CVC5:
            return "real.pi"
        if backend == Backend.DREAL:


            return "(* 4 (atan 1))"
        raise ValueError(f"{backend.value} cannot receive the exact constant pi")
    if isinstance(expr, VarExpr):
        return expr.name
    if isinstance(expr, AddExpr):
        return f"(+ {' '.join(expr_to_smt(arg, backend) for arg in expr.args)})"
    if isinstance(expr, SubExpr):
        return f"(- {expr_to_smt(expr.left, backend)} {expr_to_smt(expr.right, backend)})"
    if isinstance(expr, DivExpr):
        return f"(/ {expr_to_smt(expr.left, backend)} {expr_to_smt(expr.right, backend)})"
    if isinstance(expr, MulExpr):
        return f"(* {' '.join(expr_to_smt(arg, backend) for arg in expr.args)})"
    if isinstance(expr, NegExpr):
        return f"(- {expr_to_smt(expr.arg, backend)})"
    if isinstance(expr, PowExpr):


        if expr.exponent == 0:
            return "1"
        base = expr_to_smt(expr.base, backend)
        if expr.exponent == 1:
            return base
        return f"(* {' '.join(base for _ in range(expr.exponent))})"
    if isinstance(expr, SinExpr):
        return f"(sin {expr_to_smt(expr.arg, backend)})"
    if isinstance(expr, CosExpr):
        return f"(cos {expr_to_smt(expr.arg, backend)})"
    if isinstance(expr, ExpExpr):
        return f"(exp {expr_to_smt(expr.arg, backend)})"
    if isinstance(expr, TanhExpr):


        argument = expr_to_smt(expr.arg, backend)
        exponential = f"(exp (* 2 {argument}))"
        return f"(/ (- {exponential} 1) (+ {exponential} 1))"
    if isinstance(expr, LogExpr):
        return f"(log {expr_to_smt(expr.arg, backend)})"
    if isinstance(expr, SqrtExpr):
        return f"(sqrt {expr_to_smt(expr.arg, backend)})"
    if isinstance(expr, AtanExpr):
        name = "arctan" if backend == Backend.CVC5 else "atan"
        return f"({name} {expr_to_smt(expr.arg, backend)})"
    raise TypeError(type(expr))


_RELATION_TEXT = {
    Relation.LT: "<",
    Relation.LE: "<=",
    Relation.EQ: "=",
    Relation.GE: ">=",
    Relation.GT: ">",
}


def constraint_to_smt(constraint: Constraint, backend: Backend) -> str:
    return (
        f"({_RELATION_TEXT[constraint.relation]} "
        f"{expr_to_smt(constraint.lhs, backend)} "
        f"{expr_to_smt(constraint.rhs, backend)})"
    )


def _box_assertions(box: BoxSpec | None, backend: Backend) -> list[str]:
    if box is None:
        return []
    result: list[str] = []
    for name in sorted(box.lower):
        lower = ConstExpr(value=box.lower[name])
        upper = ConstExpr(value=box.upper[name])
        result.append(f"(>= {name} {expr_to_smt(lower, backend)})")
        result.append(f"(<= {name} {expr_to_smt(upper, backend)})")
    return result


def query_has_transcendentals(query: QuerySpec) -> bool:
    constraints = list(query.constraints)
    for group in query.any_of:
        constraints.extend(group.constraints)
    return any(
        contains_transcendentals(expression)
        for constraint in constraints
        for expression in (constraint.lhs, constraint.rhs)
    )


def query_to_smt2(query: QuerySpec, backend: Backend) -> str:
    if backend in (Backend.Z3, Backend.YICES) and query_has_transcendentals(query):
        raise ValueError(f"{backend.value} cannot receive transcendental conditions")
    if backend == Backend.DREAL and (
        query.formal_bounds is None
        or set(query.formal_bounds.lower) != set(query.variables)
    ):
        raise ValueError("dReal queries require formal finite bounds for every variable")

    transcendental = query_has_transcendentals(query)
    if transcendental and backend == Backend.CVC5:
        logic = "QF_NRAT"
    else:

        logic = "QF_NRA"
    lines = ["(set-option :produce-models true)", f"(set-logic {logic})"]
    lines.extend(f"(declare-fun {variable} () Real)" for variable in query.variables)

    conjuncts = _box_assertions(query.formal_bounds, backend)
    conjuncts.extend(constraint_to_smt(constraint, backend) for constraint in query.constraints)
    if query.any_of:
        disjuncts: list[str] = []
        for group in query.any_of:
            atoms = [constraint_to_smt(constraint, backend) for constraint in group.constraints]
            if not atoms:
                disjuncts.append("true")
            elif len(atoms) == 1:
                disjuncts.append(atoms[0])
            else:
                disjuncts.append(f"(and {' '.join(atoms)})")
        conjuncts.append(f"(or {' '.join(disjuncts)})")
    if not conjuncts:
        formula = "true"
    elif len(conjuncts) == 1:
        formula = conjuncts[0]
    else:
        formula = f"(and {' '.join(conjuncts)})"
    lines.extend((f"(assert {formula})", "(check-sat)", "(get-model)"))
    return "\n".join(lines) + "\n"


"""Fixed-timeout solver invocation and complete result parsing."""


import re
from fractions import Fraction
from typing import Any

from .s02_expressions import content_hash
from .s01_models import (
    Backend,
    IntervalValue,
    Condition,
    ReplayStatus,
    SolverResult,
    SolverStatus,
    Witness,
)
from .s13_runtime import (
    EXPECTED_SOLVER_VERSIONS,
    Executor,
    RuntimeLockError,
    RuntimeManifest,
    DEFAULT_FINALIZATION_RESERVE_SECONDS,
    RunDeadline,
    has_exact_version_token,
    runtime_for_backend,
)

SOLVER_TIMEOUT_SECONDS = 30.0
DREAL_DELTA = "0.001"


def parse_status(stdout: str, stderr: str, *, timed_out: bool, returncode: int) -> SolverStatus:
    if timed_out:
        return SolverStatus.TIMEOUT
    normalized = f"{stdout}\n{stderr}".lower()
    if re.search(r"\bdelta-sat\b|\bδ-sat\b", normalized):
        return SolverStatus.DELTA_SAT
    first = next((line.strip().lower() for line in stdout.splitlines() if line.strip()), "")

    if first == "unsat" or re.search(r"^unsat\b", first):
        return SolverStatus.UNSAT
    if first == "sat" or re.search(r"^sat\b", first):
        return SolverStatus.SAT
    if returncode != 0 or re.search(r"\b(error|exception|unsupported)\b", normalized):
        return SolverStatus.ERROR
    if first == "unknown" or re.search(r"\bunknown\b", normalized):
        return SolverStatus.UNKNOWN
    return SolverStatus.ERROR


def _tokens(text: str) -> list[str]:
    return re.findall(r"\(|\)|[^\s()]+", text)


def _sexpressions(text: str) -> list[Any]:
    tokens = _tokens(text)
    index = 0

    def parse() -> Any:
        nonlocal index
        if index >= len(tokens):
            raise ValueError("unexpected end")
        token = tokens[index]
        index += 1
        if token != "(":
            return token
        result = []
        while index < len(tokens) and tokens[index] != ")":
            result.append(parse())
        if index >= len(tokens):
            raise ValueError("unclosed list")
        index += 1
        return result

    result = []
    while index < len(tokens):
        result.append(parse())
    return result


def _as_fraction(value: Any) -> Fraction | None:
    if isinstance(value, str):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError):
            return None
    if not isinstance(value, list) or not value:
        return None
    if len(value) == 2 and value[0] == "-":
        inner = _as_fraction(value[1])
        return -inner if inner is not None else None
    if len(value) == 3 and value[0] == "/":
        numerator = _as_fraction(value[1])
        denominator = _as_fraction(value[2])
        if numerator is not None and denominator not in (None, 0):
            return numerator / denominator
    return None


def parse_model(stdout: str, variables: tuple[str, ...]) -> Witness | None:
    point: dict[str, str] = {}
    try:
        expressions = _sexpressions(stdout)
    except ValueError:
        expressions = []

    def visit(value: Any) -> None:
        if not isinstance(value, list):
            return
        if len(value) >= 5 and value[0] == "define-fun" and value[1] in variables:
            number = _as_fraction(value[-1])
            if number is not None:
                point[value[1]] = str(number)
        if len(value) == 3 and value[0] == "=" and value[1] in variables:
            number = _as_fraction(value[2])
            if number is not None:
                point[value[1]] = str(number)
        for child in value:
            visit(child)

    for expression in expressions:
        visit(expression)
    if set(point) == set(variables):
        return Witness(point=point)

    box: dict[str, IntervalValue] = {}
    pattern = re.compile(
        r"^\s*([A-Za-z_]\w*)\s*[:=]\s*\[\s*([^,\]]+)\s*,\s*([^\]]+)\s*\]",
        re.MULTILINE,
    )
    for match in pattern.finditer(stdout):
        if match.group(1) in variables:
            box[match.group(1)] = IntervalValue(
                lower=match.group(2).strip(), upper=match.group(3).strip()
            )
    if set(box) == set(variables):
        return Witness(box=box)
    return None


class SolverRunner:
    def __init__(
        self,
        lock: RuntimeManifest,
        executor: Executor,
        *,
        deadline: RunDeadline | None = None,
    ) -> None:
        self.lock = lock
        self.executor = executor
        self.formal = bool(getattr(executor, "formal", False))
        self._observed_versions: dict[Backend, str] = {}
        self.deadline = deadline

    def _version(self, backend: Backend) -> str:
        if backend in self._observed_versions:
            return self._observed_versions[backend]
        runtime = runtime_for_backend(self.lock, backend)
        timeout = (
            10.0
            if self.deadline is None
            else self.deadline.cap(
                10.0,
                reserve_seconds=DEFAULT_FINALIZATION_RESERVE_SECONDS,
            )
        )
        result = self.executor.version(runtime, timeout_seconds=timeout)
        observed_text = f"{result.stdout}\n{result.stderr}"
        expected = runtime.expected_version
        if (
            result.timed_out
            or result.returncode != 0
            or not has_exact_version_token(observed_text, expected)
        ):
            raise RuntimeLockError(
                f"{backend.value} version gate failed; expected exact token {expected}, "
                f"output={observed_text.strip()!r}"
            )
        self._observed_versions[backend] = expected
        return expected

    def run(self, condition: Condition, backend: Backend) -> SolverResult:
        if condition.query is None:
            raise ValueError("external solvers require a query condition")
        expected = EXPECTED_SOLVER_VERSIONS[backend]
        try:
            expected = runtime_for_backend(self.lock, backend).expected_version
            observed = self._version(backend)
            runtime = runtime_for_backend(self.lock, backend)
            query = query_to_smt2(condition.query, backend)
            query_hash = content_hash(query)
            timeout = (
                SOLVER_TIMEOUT_SECONDS
                if self.deadline is None
                else self.deadline.cap(
                    SOLVER_TIMEOUT_SECONDS,
                    reserve_seconds=DEFAULT_FINALIZATION_RESERVE_SECONDS,
                )
            )
            execution = self.executor.query(runtime, query, timeout_seconds=timeout)
            status = parse_status(
                execution.stdout,
                execution.stderr,
                timed_out=execution.timed_out,
                returncode=execution.returncode,
            )
            witness = (
                parse_model(execution.stdout, condition.query.variables)
                if status in (SolverStatus.SAT, SolverStatus.DELTA_SAT)
                else None
            )
            return SolverResult(
                condition_id=condition.condition_id,
                backend=backend,
                expected_version=expected,
                observed_version=observed,
                status=status,
                duration_seconds=execution.duration_seconds,
                query_hash=query_hash,
                formal_query=query,
                container_image=getattr(runtime, "image", None),
                witness=witness,
                stdout=execution.stdout,
                stderr=execution.stderr,
            )
        except (RuntimeLockError, ValueError) as error:
            query_hash = content_hash(condition.model_dump(mode="json"))
            return SolverResult(
                condition_id=condition.condition_id,
                backend=backend,
                expected_version=expected,
                status=SolverStatus.ERROR,
                duration_seconds=0,
                query_hash=query_hash,
                replay_status=ReplayStatus.NOT_APPLICABLE,
                stderr=str(error),
            )
