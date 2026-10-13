"""Determine compatible solvers and verification routes."""
from __future__ import annotations

from dataclasses import dataclass

from .s02_expressions import contains_transcendentals, is_polynomial
from .s01_models import (
    Backend,
    Condition,
    RoutingDecision,
    VerificationRouterDecision,
    VerificationRoute,
)

DEFAULT_BACKEND_ORDER = (Backend.Z3, Backend.CVC5, Backend.YICES, Backend.DREAL)


@dataclass(frozen=True)
class CapabilitySummary:
    polynomial_nra: bool
    transcendental: bool
    formally_bounded: bool
    eligible_backends: tuple[Backend, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "polynomial_nra": self.polynomial_nra,
            "transcendental": self.transcendental,
            "formally_bounded": self.formally_bounded,
            "eligible_backends": [backend.value for backend in self.eligible_backends],
        }


def capability_summary(condition: Condition) -> CapabilitySummary:
    query = condition.query
    if query is None:
        return CapabilitySummary(False, False, False, ())
    expressions = []
    for constraint in query.constraints:
        expressions.extend((constraint.lhs, constraint.rhs))
    for group in query.any_of:
        for constraint in group.constraints:
            expressions.extend((constraint.lhs, constraint.rhs))
    transcendental = any(contains_transcendentals(expression) for expression in expressions)
    polynomial = all(is_polynomial(expression) for expression in expressions)
    bounded = query.formal_bounds is not None and set(query.formal_bounds.lower) == set(
        query.variables
    )
    if transcendental:
        eligible = [Backend.CVC5]
    else:
        eligible = [Backend.Z3, Backend.CVC5, Backend.YICES]
    if bounded:
        eligible.append(Backend.DREAL)
    return CapabilitySummary(polynomial, transcendental, bounded, tuple(eligible))


def default_solver_order(eligible: tuple[Backend, ...]) -> tuple[Backend, ...]:
    allowed = set(eligible)
    return tuple(backend for backend in DEFAULT_BACKEND_ORDER if backend in allowed)


def resolve_verification_routing(
    condition: Condition,
    agent_decision: VerificationRouterDecision | None,
) -> RoutingDecision:


    capabilities = capability_summary(condition)
    fallback_route = (
        VerificationRoute.SMT
        if capabilities.eligible_backends
        else VerificationRoute.DIRECT_LEAN
    )
    if agent_decision is None or agent_decision.condition_id != condition.condition_id:
        route = fallback_route
        rationale = "invalid or missing verification router output; deterministic fallback used"
        used_fallback = True
        proposed = ()
    else:
        route = agent_decision.route
        rationale = agent_decision.rationale
        used_fallback = False
        proposed = agent_decision.solver_order

    if route == VerificationRoute.DIRECT_LEAN:
        return RoutingDecision(
            condition_id=condition.condition_id,
            route=VerificationRoute.DIRECT_LEAN,
            used_fallback=used_fallback,
            rationale=rationale,
        )

    eligible = capabilities.eligible_backends
    valid_order = (
        len(proposed) == len(eligible)
        and len(set(proposed)) == len(proposed)
        and set(proposed) == set(eligible)
    )
    if not valid_order:
        proposed = default_solver_order(eligible)
        used_fallback = True
        rationale = f"{rationale}; invalid solver_order; deterministic complete order used"
    if not proposed:
        return RoutingDecision(
            condition_id=condition.condition_id,
            route=VerificationRoute.DIRECT_LEAN,
            used_fallback=True,
            rationale=f"{rationale}; no compatible SMT backend; Direct Lean required",
        )
    return RoutingDecision(
        condition_id=condition.condition_id,
        route=VerificationRoute.SMT,
        solver_order=tuple(proposed),
        used_fallback=used_fallback,
        rationale=rationale,
    )
