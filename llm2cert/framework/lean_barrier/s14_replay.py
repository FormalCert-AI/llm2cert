"""Replay solver witnesses and classify counterexample evidence."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import mpmath as mp

from .s02_expressions import evaluator
from .s01_models import Constraint, QuerySpec, Relation, ReplayStatus, Witness


_iv: Any = mp.iv
_mpf: Any = mp.mpf
_iv_mpf: Any = _iv.mpf
_iv_exp: Any = _iv.exp
_iv_sin: Any = _iv.sin
_iv_cos: Any = _iv.cos
_iv_log: Any = _iv.log
_iv_sqrt: Any = _iv.sqrt


def _iv_atan(value: Any) -> Any:

    return _iv_mpf([mp.atan(value.a), mp.atan(value.b)])


@dataclass(frozen=True)
class ReplayResult:
    status: ReplayStatus
    residual: str
    reason: str


def _nstr(value: Any, digits: int = 50) -> str:
    text = mp.nstr(value, digits)
    return text if text is not None else "nan"


def _mp_number(value: str) -> Any:
    if "/" in value and not any(character in value for character in "[](),"):
        fraction = Fraction(value)
        return _mpf(fraction.numerator) / fraction.denominator
    return _mpf(value)


def _constraint_margin(
    constraint: Constraint, environment: Mapping[str, Any]
) -> tuple[bool, Any]:
    evaluate = evaluator(
        sin=mp.sin,
        cos=mp.cos,
        exp=mp.exp,
        tanh=mp.tanh,
        log=mp.log,
        sqrt=mp.sqrt,
        atan=mp.atan,
        pi=mp.pi,
        number=lambda numerator, denominator: _mpf(numerator) / denominator,
    )
    left = _mpf(evaluate(constraint.lhs, environment))
    right = _mpf(evaluate(constraint.rhs, environment))
    difference = left - right
    epsilon = _mpf("1e-70")
    if constraint.relation == Relation.LT:
        margin = right - left
        return margin > epsilon, margin
    if constraint.relation == Relation.LE:
        margin = right - left
        return margin >= -epsilon, margin
    if constraint.relation == Relation.EQ:
        margin = -abs(difference)
        return abs(difference) <= epsilon, margin
    if constraint.relation == Relation.GE:
        margin = left - right
        return margin >= -epsilon, margin
    if constraint.relation == Relation.GT:
        margin = left - right
        return margin > epsilon, margin
    raise TypeError(constraint.relation)


def replay_witness(query: QuerySpec, witness: Witness | None) -> ReplayResult:
    if witness is None or witness.point is None:
        return ReplayResult(ReplayStatus.NOT_CONFIRMED, "nan", "no exact point witness")
    if set(witness.point) != set(query.variables):
        return ReplayResult(ReplayStatus.NOT_CONFIRMED, "nan", "witness variables mismatch")
    with mp.workdps(100):
        try:
            environment = {name: _mp_number(value) for name, value in witness.point.items()}
            shared = [
                _constraint_margin(constraint, environment) for constraint in query.constraints
            ]
            if not all(ok for ok, _ in shared):
                residual = min((margin for _, margin in shared), default=_mpf("0"))
                return ReplayResult(
                    ReplayStatus.NOT_CONFIRMED,
                    _nstr(residual),
                    "shared query constraints did not replay",
                )
            branch_margins: list[Any] = []
            branch_ok = not query.any_of
            for group in query.any_of:
                checked = [
                    _constraint_margin(constraint, environment) for constraint in group.constraints
                ]
                margin = min((value for _, value in checked), default=mp.inf)
                branch_margins.append(margin)
                if all(ok for ok, _ in checked):
                    branch_ok = True
                    break
            all_margins = [margin for _, margin in shared]
            if branch_margins:
                all_margins.append(max(branch_margins))
            residual = min(all_margins, default=mp.inf)
            if branch_ok:
                return ReplayResult(
                    ReplayStatus.CONFIRMED,
                    _nstr(residual),
                    "all original-AST query constraints replayed at 100 decimal digits",
                )
            return ReplayResult(
                ReplayStatus.NOT_CONFIRMED,
                _nstr(residual),
                "no disjunct replayed",
            )
        except (KeyError, ValueError, ZeroDivisionError, OverflowError) as error:
            return ReplayResult(ReplayStatus.NOT_CONFIRMED, "nan", f"replay error: {error}")


def _iv_number(value: str) -> Any:
    if "/" in value and not any(character in value for character in "[](),"):
        fraction = Fraction(value)
        return _iv_mpf(fraction.numerator) / _iv_mpf(fraction.denominator)
    return _iv_mpf(value)


def _interval_constraint(
    constraint: Constraint,
    environment: Mapping[str, Any],
    *,
    equality_tolerance: Any | None = None,
) -> bool:
    def interval_tanh(value: Any) -> Any:
        exponential: Any = _iv_exp(2 * value)
        return (exponential - 1) / (exponential + 1)

    evaluate = evaluator(
        sin=_iv_sin,
        cos=_iv_cos,
        exp=_iv_exp,
        tanh=interval_tanh,
        log=_iv_log,
        sqrt=_iv_sqrt,
        atan=_iv_atan,
        pi=_iv.pi,
        number=lambda numerator, denominator: _iv_mpf(numerator) / _iv_mpf(denominator),
    )
    left: Any = evaluate(constraint.lhs, environment)
    right: Any = evaluate(constraint.rhs, environment)
    left_lower, left_upper = float(left.a), float(left.b)
    right_lower, right_upper = float(right.a), float(right.b)
    if constraint.relation == Relation.LT:
        return left_upper < right_lower
    if constraint.relation == Relation.LE:
        return left_upper <= right_lower
    if constraint.relation == Relation.EQ:
        difference = left - right
        if equality_tolerance is None:
            return float(difference.a) == 0 and float(difference.b) == 0
        tolerance = float(equality_tolerance)
        return abs(float(difference.a)) <= tolerance and abs(float(difference.b)) <= tolerance
    if constraint.relation == Relation.GE:
        return left_lower >= right_upper
    if constraint.relation == Relation.GT:
        return left_lower > right_upper
    raise TypeError(constraint.relation)


def interval_replay_witness(
    query: QuerySpec,
    witness: Witness | None,
    *,
    equality_tolerance: str | None = None,
) -> ReplayResult:


    if witness is None:
        return ReplayResult(ReplayStatus.NOT_CONFIRMED, "nan", "missing witness")
    try:
        tolerance = _iv_number(equality_tolerance) if equality_tolerance is not None else None
        if witness.point is not None:
            if set(witness.point) != set(query.variables):
                return ReplayResult(ReplayStatus.NOT_CONFIRMED, "nan", "witness variables mismatch")
            environment: dict[str, Any] = {
                name: _iv_number(value) for name, value in witness.point.items()
            }
        elif witness.box is not None:
            if set(witness.box) != set(query.variables):
                return ReplayResult(ReplayStatus.NOT_CONFIRMED, "nan", "witness variables mismatch")
            environment = {
                name: _iv_mpf([interval.lower, interval.upper])
                for name, interval in witness.box.items()
            }
        else:
            return ReplayResult(ReplayStatus.NOT_CONFIRMED, "nan", "empty witness")
        shared = all(
            _interval_constraint(constraint, environment, equality_tolerance=tolerance)
            for constraint in query.constraints
        )
        branch = not query.any_of or any(
            all(
                _interval_constraint(constraint, environment, equality_tolerance=tolerance)
                for constraint in group.constraints
            )
            for group in query.any_of
        )
        if shared and branch:
            residual = (
                f"interval-certified-delta-{equality_tolerance}"
                if equality_tolerance is not None
                else "interval-certified"
            )
            return ReplayResult(
                ReplayStatus.CONFIRMED,
                residual,
                "outward interval evaluation confirmed the original-AST query",
            )
        return ReplayResult(
            ReplayStatus.NOT_CONFIRMED,
            "interval-overlap",
            "interval evaluation could not prove every query atom",
        )
    except (ValueError, ZeroDivisionError, OverflowError, AttributeError) as error:
        return ReplayResult(ReplayStatus.NOT_CONFIRMED, "nan", f"interval replay error: {error}")
