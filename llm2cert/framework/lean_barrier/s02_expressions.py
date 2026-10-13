"""Parse and manipulate exact symbolic expressions."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from fractions import Fraction
from typing import TYPE_CHECKING, Any, overload

if TYPE_CHECKING:
    import numpy as np

from .s01_models import (
    AddExpr,
    AtanExpr,
    ConstExpr,
    CosExpr,
    DivExpr,
    EXPR_ADAPTER,
    ExpExpr,
    Expr,
    LogExpr,
    MulExpr,
    NegExpr,
    PiExpr,
    PowExpr,
    Rational,
    SinExpr,
    SqrtExpr,
    SubExpr,
    TanhExpr,
    VarExpr,
)


def rational(value: int | Fraction, denominator: int = 1) -> Rational:
    fraction = value if isinstance(value, Fraction) else Fraction(value, denominator)
    return Rational(numerator=fraction.numerator, denominator=fraction.denominator)


def const(value: int | Fraction, denominator: int = 1) -> ConstExpr:
    return ConstExpr(value=rational(value, denominator))


ZERO = const(0)
ONE = const(1)
PI = PiExpr()


def canonical_json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _fraction(node: ConstExpr) -> Fraction:
    return Fraction(node.value.numerator, node.value.denominator)


def is_const(node: Expr, value: int | None = None) -> bool:
    if not isinstance(node, ConstExpr):
        return False
    return value is None or _fraction(node) == value


def add(*args: Expr) -> Expr:
    flat: list[Expr] = []
    total = Fraction(0)
    for arg in args:
        if isinstance(arg, AddExpr):
            nested = arg.args
        else:
            nested = (arg,)
        for item in nested:
            if isinstance(item, ConstExpr):
                total += _fraction(item)
            elif not is_const(item, 0):
                flat.append(item)
    if total:
        flat.append(const(total))
    if not flat:
        return ZERO
    if len(flat) == 1:
        return flat[0]
    return AddExpr(args=tuple(flat))


def neg(arg: Expr) -> Expr:
    if isinstance(arg, ConstExpr):
        return const(-_fraction(arg))
    if isinstance(arg, NegExpr):
        return arg.arg
    return NegExpr(arg=arg)


def sub(left: Expr, right: Expr) -> Expr:
    if is_const(right, 0):
        return left
    if is_const(left, 0):
        return neg(right)
    if isinstance(left, ConstExpr) and isinstance(right, ConstExpr):
        return const(_fraction(left) - _fraction(right))
    return SubExpr(left=left, right=right)


def mul(*args: Expr) -> Expr:
    flat: list[Expr] = []
    total = Fraction(1)
    for arg in args:
        if isinstance(arg, MulExpr):
            nested = arg.args
        else:
            nested = (arg,)
        for item in nested:
            if is_const(item, 0):
                return ZERO
            if isinstance(item, ConstExpr):
                total *= _fraction(item)
            elif not is_const(item, 1):
                flat.append(item)
    if total == 0:
        return ZERO
    if total != 1 or not flat:
        flat.insert(0, const(total))
    if len(flat) == 1:
        return flat[0]
    return MulExpr(args=tuple(flat))


def div(left: Expr, right: Expr) -> Expr:
    if isinstance(right, ConstExpr) and right.value.numerator == 0:
        raise ValueError("division by zero")
    if isinstance(left, ConstExpr) and isinstance(right, ConstExpr):
        return const(_fraction(left) / _fraction(right))
    if is_const(right, 1):
        return left
    if is_const(left, 0):
        return ZERO
    if isinstance(right, ConstExpr):
        return mul(left, const(1 / _fraction(right)))
    return DivExpr(left=left, right=right)


CORE_UNARY_FUNCTIONS = ("sin", "cos", "exp", "tanh", "log", "sqrt", "atan")
SUGAR_UNARY_FUNCTIONS = (
    "ln",
    "tan",
    "sec",
    "csc",
    "cot",
    "sinh",
    "cosh",
    "sech",
    "csch",
    "coth",
    "arctan",
    "atanh",
)


def _core_unary(name: str) -> Callable[[Expr], Expr]:
    constructors = {
        "sin": SinExpr,
        "cos": CosExpr,
        "exp": ExpExpr,
        "tanh": TanhExpr,
        "log": LogExpr,
        "sqrt": SqrtExpr,
        "atan": AtanExpr,
    }
    constructor = constructors[name]
    return lambda argument: constructor(arg=argument)


def expand_call(name: str, argument: Expr) -> Expr:


    key = name.lower()
    if key in CORE_UNARY_FUNCTIONS:
        return _core_unary(key)(argument)
    sugars: dict[str, Callable[[Expr], Expr]] = {
        "ln": lambda arg: LogExpr(arg=arg),
        "arctan": lambda arg: AtanExpr(arg=arg),
        "atanh": lambda arg: div(
            sub(LogExpr(arg=add(ONE, arg)), LogExpr(arg=sub(ONE, arg))),
            const(2),
        ),
        "tan": lambda arg: div(SinExpr(arg=arg), CosExpr(arg=arg)),
        "sec": lambda arg: div(ONE, CosExpr(arg=arg)),
        "csc": lambda arg: div(ONE, SinExpr(arg=arg)),
        "cot": lambda arg: div(CosExpr(arg=arg), SinExpr(arg=arg)),
        "sinh": lambda arg: div(sub(ExpExpr(arg=arg), ExpExpr(arg=neg(arg))), const(2)),
        "cosh": lambda arg: div(add(ExpExpr(arg=arg), ExpExpr(arg=neg(arg))), const(2)),
        "sech": lambda arg: div(const(2), add(ExpExpr(arg=arg), ExpExpr(arg=neg(arg)))),
        "csch": lambda arg: div(const(2), sub(ExpExpr(arg=arg), ExpExpr(arg=neg(arg)))),
        "coth": lambda arg: div(
            add(ExpExpr(arg=arg), ExpExpr(arg=neg(arg))),
            sub(ExpExpr(arg=arg), ExpExpr(arg=neg(arg))),
        ),
    }
    expander = sugars.get(key)
    if expander is None:
        raise ValueError(
            f"unsupported function {name!r}; core={CORE_UNARY_FUNCTIONS} "
            f"sugar={SUGAR_UNARY_FUNCTIONS}"
        )
    return expander(argument)


def desugar_json(value: Any) -> Any:


    if isinstance(value, list):
        return [desugar_json(item) for item in value]
    if not isinstance(value, dict):
        return value
    kind = value.get("kind")
    if isinstance(kind, str) and kind.lower() in SUGAR_UNARY_FUNCTIONS and "arg" in value:
        argument = EXPR_ADAPTER.validate_python(desugar_json(value["arg"]))
        return expand_call(kind, argument).model_dump(mode="json", exclude_none=True)
    return {key: desugar_json(item) for key, item in value.items()}


def pow_nat(base: Expr, exponent: int) -> Expr:
    if exponent < 0:
        raise ValueError("only natural powers are allowed")
    if exponent == 0:
        return ONE
    if exponent == 1:
        return base
    if isinstance(base, ConstExpr):
        return const(_fraction(base) ** exponent)
    return PowExpr(base=base, exponent=exponent)


def variables(expr: Expr) -> frozenset[str]:
    if isinstance(expr, VarExpr):
        return frozenset((expr.name,))
    if isinstance(expr, (ConstExpr, PiExpr)):
        return frozenset()
    if isinstance(expr, (AddExpr, MulExpr)):
        return frozenset().union(*(variables(arg) for arg in expr.args))
    if isinstance(expr, (SubExpr, DivExpr)):
        return variables(expr.left) | variables(expr.right)
    if isinstance(
        expr, (NegExpr, SinExpr, CosExpr, ExpExpr, TanhExpr, LogExpr, SqrtExpr, AtanExpr)
    ):
        return variables(expr.arg)
    if isinstance(expr, PowExpr):
        return variables(expr.base)
    raise TypeError(type(expr))


def validate_variables(expr: Expr, allowed: set[str] | frozenset[str]) -> None:
    unknown = variables(expr) - set(allowed)
    if unknown:
        raise ValueError(f"undeclared variables: {', '.join(sorted(unknown))}")


def contains_transcendentals(expr: Expr) -> bool:
    if isinstance(expr, PiExpr):
        return True
    if isinstance(expr, (SinExpr, CosExpr, ExpExpr, TanhExpr, LogExpr, SqrtExpr, AtanExpr)):
        return True
    if isinstance(expr, (AddExpr, MulExpr)):
        return any(contains_transcendentals(arg) for arg in expr.args)
    if isinstance(expr, (SubExpr, DivExpr)):
        return contains_transcendentals(expr.left) or contains_transcendentals(expr.right)
    if isinstance(expr, NegExpr):
        return contains_transcendentals(expr.arg)
    if isinstance(expr, PowExpr):
        return contains_transcendentals(expr.base)
    return False


def is_polynomial(expr: Expr) -> bool:


    if isinstance(expr, (ConstExpr, VarExpr)):
        return True
    if isinstance(expr, (AddExpr, MulExpr)):
        return all(is_polynomial(arg) for arg in expr.args)
    if isinstance(expr, SubExpr):
        return is_polynomial(expr.left) and is_polynomial(expr.right)
    if isinstance(expr, DivExpr):
        return (
            is_polynomial(expr.left)
            and isinstance(expr.right, ConstExpr)
            and expr.right.value.numerator != 0
        )
    if isinstance(expr, NegExpr):
        return is_polynomial(expr.arg)
    if isinstance(expr, PowExpr):
        return is_polynomial(expr.base)
    return False


def differentiate(expr: Expr, variable: str) -> Expr:
    if isinstance(expr, (ConstExpr, PiExpr)):
        return ZERO
    if isinstance(expr, VarExpr):
        return ONE if expr.name == variable else ZERO
    if isinstance(expr, AddExpr):
        return add(*(differentiate(arg, variable) for arg in expr.args))
    if isinstance(expr, SubExpr):
        return sub(differentiate(expr.left, variable), differentiate(expr.right, variable))
    if isinstance(expr, DivExpr):
        return div(
            sub(
                mul(differentiate(expr.left, variable), expr.right),
                mul(expr.left, differentiate(expr.right, variable)),
            ),
            pow_nat(expr.right, 2),
        )
    if isinstance(expr, MulExpr):
        terms: list[Expr] = []
        for index, arg in enumerate(expr.args):
            derivative = differentiate(arg, variable)
            if not is_const(derivative, 0):
                terms.append(mul(*(expr.args[:index] + (derivative,) + expr.args[index + 1 :])))
        return add(*terms)
    if isinstance(expr, NegExpr):
        return neg(differentiate(expr.arg, variable))
    if isinstance(expr, PowExpr):
        if expr.exponent == 0:
            return ZERO
        return mul(
            const(expr.exponent),
            pow_nat(expr.base, expr.exponent - 1),
            differentiate(expr.base, variable),
        )
    derivative = differentiate(expr.arg, variable)
    if isinstance(expr, SinExpr):
        return mul(CosExpr(arg=expr.arg), derivative)
    if isinstance(expr, CosExpr):
        return mul(neg(SinExpr(arg=expr.arg)), derivative)
    if isinstance(expr, ExpExpr):
        return mul(ExpExpr(arg=expr.arg), derivative)
    if isinstance(expr, TanhExpr):
        return mul(sub(ONE, pow_nat(TanhExpr(arg=expr.arg), 2)), derivative)
    if isinstance(expr, LogExpr):
        return div(derivative, expr.arg)
    if isinstance(expr, SqrtExpr):
        return div(derivative, mul(const(2), SqrtExpr(arg=expr.arg)))
    if isinstance(expr, AtanExpr):
        return div(derivative, add(ONE, pow_nat(expr.arg, 2)))
    raise TypeError(type(expr))


def substitute(expr: Expr, replacements: Mapping[str, Expr]) -> Expr:
    if isinstance(expr, VarExpr):
        return replacements.get(expr.name, expr)
    if isinstance(expr, (ConstExpr, PiExpr)):
        return expr
    if isinstance(expr, AddExpr):
        return add(*(substitute(arg, replacements) for arg in expr.args))
    if isinstance(expr, SubExpr):
        return sub(substitute(expr.left, replacements), substitute(expr.right, replacements))
    if isinstance(expr, DivExpr):
        return div(substitute(expr.left, replacements), substitute(expr.right, replacements))
    if isinstance(expr, MulExpr):
        return mul(*(substitute(arg, replacements) for arg in expr.args))
    if isinstance(expr, NegExpr):
        return neg(substitute(expr.arg, replacements))
    if isinstance(expr, PowExpr):
        return pow_nat(substitute(expr.base, replacements), expr.exponent)
    if isinstance(expr, SinExpr):
        return SinExpr(arg=substitute(expr.arg, replacements))
    if isinstance(expr, CosExpr):
        return CosExpr(arg=substitute(expr.arg, replacements))
    if isinstance(expr, ExpExpr):
        return ExpExpr(arg=substitute(expr.arg, replacements))
    if isinstance(expr, TanhExpr):
        return TanhExpr(arg=substitute(expr.arg, replacements))
    if isinstance(expr, LogExpr):
        return LogExpr(arg=substitute(expr.arg, replacements))
    if isinstance(expr, SqrtExpr):
        return SqrtExpr(arg=substitute(expr.arg, replacements))
    if isinstance(expr, AtanExpr):
        return AtanExpr(arg=substitute(expr.arg, replacements))
    raise TypeError(type(expr))


@overload
def evaluator() -> Callable[[Expr, Mapping[str, float]], float]: ...


@overload
def evaluator(
    *,
    sin: Callable[..., Any],
    cos: Callable[..., Any],
    exp: Callable[..., Any],
    tanh: Callable[..., Any],
    log: Callable[..., Any] = ...,
    sqrt: Callable[..., Any] = ...,
    atan: Callable[..., Any] = ...,
    pi: Any = ...,
    number: Callable[[int, int], Any] = ...,
) -> Callable[[Expr, Mapping[str, Any]], Any]: ...


def evaluator(
    *,
    sin: Callable[..., Any] = math.sin,
    cos: Callable[..., Any] = math.cos,
    exp: Callable[..., Any] = math.exp,
    tanh: Callable[..., Any] = math.tanh,
    log: Callable[..., Any] = math.log,
    sqrt: Callable[..., Any] = math.sqrt,
    atan: Callable[..., Any] = math.atan,
    pi: Any = math.pi,
    number: Callable[[int, int], Any] = lambda numerator, denominator: numerator / denominator,
) -> Callable[[Expr, Mapping[str, Any]], Any]:
    def evaluate(expr: Expr, environment: Mapping[str, Any]) -> Any:
        if isinstance(expr, ConstExpr):
            return number(expr.value.numerator, expr.value.denominator)
        if isinstance(expr, PiExpr):
            return pi
        if isinstance(expr, VarExpr):
            return environment[expr.name]
        if isinstance(expr, AddExpr):
            return sum(evaluate(arg, environment) for arg in expr.args)
        if isinstance(expr, SubExpr):
            return evaluate(expr.left, environment) - evaluate(expr.right, environment)
        if isinstance(expr, DivExpr):
            return evaluate(expr.left, environment) / evaluate(expr.right, environment)
        if isinstance(expr, MulExpr):
            result: Any = 1
            for arg in expr.args:
                result = result * evaluate(arg, environment)
            return result
        if isinstance(expr, NegExpr):
            return -evaluate(expr.arg, environment)
        if isinstance(expr, PowExpr):
            return evaluate(expr.base, environment) ** expr.exponent
        if isinstance(expr, SinExpr):
            return sin(evaluate(expr.arg, environment))
        if isinstance(expr, CosExpr):
            return cos(evaluate(expr.arg, environment))
        if isinstance(expr, ExpExpr):
            return exp(evaluate(expr.arg, environment))
        if isinstance(expr, TanhExpr):
            return tanh(evaluate(expr.arg, environment))
        if isinstance(expr, LogExpr):
            return log(evaluate(expr.arg, environment))
        if isinstance(expr, SqrtExpr):
            return sqrt(evaluate(expr.arg, environment))
        if isinstance(expr, AtanExpr):
            return atan(evaluate(expr.arg, environment))
        raise TypeError(type(expr))

    return evaluate


evaluate_float = evaluator()


def evaluate_vector(expr: Expr, variable_order: tuple[str, ...], points: np.ndarray) -> np.ndarray:


    import numpy as np

    array = np.asarray(points)
    environment = {name: array[:, index] for index, name in enumerate(variable_order)}
    evaluate_numpy = evaluator(
        sin=np.sin,
        cos=np.cos,
        exp=np.exp,
        tanh=np.tanh,
        log=np.log,
        sqrt=np.sqrt,
        atan=np.arctan,
    )
    value = np.asarray(evaluate_numpy(expr, environment), dtype=float)
    if value.ndim == 0:
        return np.full(array.shape[0], value)
    return value
