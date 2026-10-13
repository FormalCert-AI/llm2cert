"""Screen candidates using numerical samples and counterexamples."""
from __future__ import annotations

import warnings
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from fractions import Fraction

import numpy as np
from scipy.optimize import minimize
from scipy.stats import qmc

from .s02_expressions import content_hash, differentiate, evaluate_float, evaluate_vector, rational
from .s01_models import (
    BoxSpec,
    CandidateSpec,
    Constraint,
    CounterexampleEvidence,
    EvidenceLevel,
    Condition,
    ConditionKind,
    ProblemSpec,
    QuerySpec,
    Rational,
    ReplayStatus,
    Witness,
)
from .s14_replay import interval_replay_witness
from .s04_semantics import (
    build_conditions,
    fixed_parameter_names,
    fixed_parameter_screening_box,
)

XI_SAMPLES = 1500
XU_SAMPLES = 1500
ANALYSIS_AND_BOUNDARY_SAMPLES = 2000
TOTAL_SAMPLES = XI_SAMPLES + XU_SAMPLES + ANALYSIS_AND_BOUNDARY_SAMPLES


MAX_COUNTEREXAMPLES = 5


@dataclass(frozen=True)
class FastCheckResult:
    rejected: bool
    evidence: CounterexampleEvidence | None
    hints: tuple[str, ...]
    counts: dict[str, int]
    evidence_list: tuple[CounterexampleEvidence, ...] = ()
    started_at_utc: str | None = None
    finished_at_utc: str | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True)
class ScreeningCondition:


    condition_id: str
    query: QuerySpec


def _fraction_float(value: Rational) -> float:
    numerator = value.numerator
    denominator = value.denominator
    return numerator / denominator


def _expand_box(box: BoxSpec, pad_ratio: Fraction = Fraction(1)) -> BoxSpec:


    lower: dict[str, Rational] = {}
    upper: dict[str, Rational] = {}
    for name in box.lower:
        lo = Fraction(box.lower[name].numerator, box.lower[name].denominator)
        hi = Fraction(box.upper[name].numerator, box.upper[name].denominator)
        width = hi - lo
        pad = width * pad_ratio if width > 0 else Fraction(1)
        lower[name] = rational(lo - pad)
        upper[name] = rational(hi + pad)
    return BoxSpec(lower=lower, upper=upper)


def _sample_exterior_collar(
    box: BoxSpec,
    variables: tuple[str, ...],
    count: int,
    offset: int,
) -> np.ndarray:


    expanded = _expand_box(box)
    collected: list[np.ndarray] = []
    total = 0
    cursor = offset
    batch_size = max(4096, count * 2)
    lower = np.array([_fraction_float(box.lower[name]) for name in variables], dtype=float)
    upper = np.array([_fraction_float(box.upper[name]) for name in variables], dtype=float)
    while total < count and cursor - offset < 131072:
        points = _sample_box(expanded, variables, batch_size, cursor)
        outside = np.any(points < lower, axis=1) | np.any(points > upper, axis=1)
        selected = points[outside]
        if selected.size:
            collected.append(selected)
            total += selected.shape[0]
        cursor += batch_size
    if not collected:
        return np.empty((0, len(variables)))
    return np.concatenate(collected, axis=0)[:count]


def _neighborhood_box(problem: ProblemSpec) -> BoxSpec:
    if (
        problem.neighborhood is not None
        and problem.neighborhood.region is not None
        and problem.neighborhood.region.bounds is not None
    ):
        return problem.neighborhood.region.bounds
    return problem.analysis_box


def _sample_box(box: BoxSpec, variables: tuple[str, ...], count: int, offset: int) -> np.ndarray:
    engine = qmc.Sobol(d=len(variables), scramble=False)
    if offset:
        engine.fast_forward(offset)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        unit = engine.random(count)
    lower = np.array([_fraction_float(box.lower[name]) for name in variables], dtype=float)
    upper = np.array([_fraction_float(box.upper[name]) for name in variables], dtype=float)
    return qmc.scale(unit, lower, upper)


def _constraint_mask(
    constraint: Constraint, variables: tuple[str, ...], points: np.ndarray
) -> np.ndarray:
    from .s01_models import Relation

    left = np.asarray(evaluate_vector(constraint.lhs, variables, points))
    right = np.asarray(evaluate_vector(constraint.rhs, variables, points))
    if constraint.relation == Relation.LT:
        return left < right
    if constraint.relation == Relation.LE:
        return left <= right
    if constraint.relation == Relation.EQ:
        return np.isclose(left, right, atol=1e-10, rtol=0)
    if constraint.relation == Relation.GE:
        return left >= right
    if constraint.relation == Relation.GT:
        return left > right
    raise TypeError(constraint.relation)


def _query_mask(condition: ScreeningCondition, points: np.ndarray) -> np.ndarray:
    assert condition.query is not None
    variables = condition.query.variables
    shared = np.ones(points.shape[0], dtype=bool)
    for constraint in condition.query.constraints:
        shared &= _constraint_mask(constraint, variables, points)
    if condition.query.any_of:
        disjunction = np.zeros(points.shape[0], dtype=bool)
        for group in condition.query.any_of:
            branch = np.ones(points.shape[0], dtype=bool)
            for constraint in group.constraints:
                branch &= _constraint_mask(constraint, variables, points)
            disjunction |= branch
        shared &= disjunction
    return shared


def _region_points(
    problem: ProblemSpec,
    condition: ScreeningCondition,
    count: int,
    offset: int,
) -> np.ndarray:
    assert condition.query is not None
    variables = condition.query.variables
    box = condition.query.formal_bounds or fixed_parameter_screening_box(problem)
    collected: list[np.ndarray] = []
    total = 0
    cursor = offset
    batch_size = max(4096, count * 2)
    while total < count and cursor - offset < 131072:
        points = _sample_box(box, variables, batch_size, cursor)

        region_constraints = condition.query.constraints[:-1]
        mask = np.ones(points.shape[0], dtype=bool)
        for constraint in region_constraints:
            mask &= _constraint_mask(constraint, variables, points)
        if condition.query.any_of:
            disjunction = np.zeros(points.shape[0], dtype=bool)
            for group in condition.query.any_of:
                branch = np.ones(points.shape[0], dtype=bool)
                for constraint in group.constraints:
                    branch &= _constraint_mask(constraint, variables, points)
                disjunction |= branch
            mask &= disjunction
        selected = points[mask]
        if selected.size:
            collected.append(selected)
            total += selected.shape[0]
        cursor += batch_size
    if not collected:
        return np.empty((0, len(variables)))
    return np.concatenate(collected, axis=0)[:count]


def _snap_point(point: np.ndarray) -> np.ndarray:
    snapped = point.copy()
    snapped[np.abs(snapped) < 1e-10] = 0
    for index, value in enumerate(snapped):
        candidate = Fraction(float(value)).limit_denominator(1000)
        if abs(float(candidate) - value) < 1e-12:
            snapped[index] = float(candidate)
    return snapped


def _witness(point: np.ndarray, variables: tuple[str, ...]) -> Witness:
    snapped = _snap_point(point)
    return Witness(
        point={name: format(float(snapped[index]), ".17g") for index, name in enumerate(variables)}
    )


def _find_confirmed(
    condition: ScreeningCondition,
    points: np.ndarray,
    limit: int = MAX_COUNTEREXAMPLES,
) -> tuple[CounterexampleEvidence, ...]:
    if condition.query is None or points.size == 0:
        return ()
    mask = _query_mask(condition, points)
    found: list[CounterexampleEvidence] = []
    for point in points[mask][:32]:
        witness = _witness(point, condition.query.variables)
        replay = interval_replay_witness(condition.query, witness)
        if replay.status == ReplayStatus.CONFIRMED:
            found.append(
                CounterexampleEvidence(
                    condition_id=condition.condition_id,
                    source="deterministic_sobol_fastcheck",
                    level=EvidenceLevel.INTERVAL_VALIDATED,
                    witness=witness,
                    residual=replay.residual,
                )
            )
            if len(found) >= limit:
                break
    return tuple(found)


def _boundary_candidates(
    problem: ProblemSpec,
    candidate: CandidateSpec,
    analysis_points: np.ndarray,
) -> np.ndarray:
    variables = problem.system.state_vars
    parameter_names = fixed_parameter_names(problem)
    state_dimension = len(variables)
    state_points = analysis_points[:, :state_dimension]
    parameter_points = analysis_points[:, state_dimension:]
    barrier = candidate.certificate_ast
    gradient = tuple(differentiate(barrier, name) for name in variables)
    lower = np.array([_fraction_float(problem.analysis_box.lower[name]) for name in variables])
    upper = np.array([_fraction_float(problem.analysis_box.upper[name]) for name in variables])
    projected = state_points.copy()
    for _ in range(16):
        values = np.asarray(evaluate_vector(barrier, variables, projected))
        gradients = np.column_stack(
            [evaluate_vector(component, variables, projected) for component in gradient]
        )
        norm_squared = np.sum(gradients * gradients, axis=1)
        active = norm_squared > 1e-18
        projected[active] -= values[active, None] * gradients[active] / norm_squared[active, None]
        projected = np.clip(projected, lower, upper)

    initial_values = np.abs(np.asarray(evaluate_vector(barrier, variables, state_points)))
    optimized: list[np.ndarray] = []
    optimized_parameters: list[np.ndarray] = []
    bounds = list(zip(lower, upper, strict=True))

    def objective(point: np.ndarray) -> tuple[float, np.ndarray]:
        environment = dict(zip(variables, point, strict=True))
        value = float(evaluate_float(barrier, environment))
        grad = np.array([float(evaluate_float(component, environment)) for component in gradient])
        return value * value, 2 * value * grad

    for seed_index in np.argsort(initial_values)[:16]:
        result = minimize(
            lambda point: objective(point)[0],
            state_points[seed_index],
            jac=lambda point: objective(point)[1],
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 100, "ftol": 1e-18, "gtol": 1e-12},
        )
        optimized.append(result.x)
        if parameter_names:
            optimized_parameters.append(parameter_points[seed_index])
    deterministic_specials = [np.zeros(len(variables)), (lower + upper) / 2]
    combined_states = np.vstack(
        (np.asarray(deterministic_specials), np.asarray(optimized), projected)
    )
    if parameter_names:
        parameter_midpoint = np.array(
            [
                (
                    _fraction_float(parameter.lower)
                    + _fraction_float(parameter.upper)
                )
                / 2
                for parameter in problem.fixed_parameters
            ],
            dtype=float,
        )
        special_parameters = np.tile(parameter_midpoint, (len(deterministic_specials), 1))
        combined_parameters = np.vstack(
            (special_parameters, np.asarray(optimized_parameters), parameter_points)
        )
        combined_parts = [np.hstack((combined_states, combined_parameters))]


        for index, parameter in enumerate(problem.fixed_parameters):
            for endpoint in (parameter.lower, parameter.upper):
                face_point = parameter_midpoint.copy()
                face_point[index] = _fraction_float(endpoint)
                face_parameters = np.tile(face_point, (combined_states.shape[0], 1))
                combined_parts.append(np.hstack((combined_states, face_parameters)))
        combined = np.vstack(combined_parts)
        residual_states = np.vstack(
            [combined_states for _ in range(len(combined_parts))]
        )
    else:
        combined = combined_states
        residual_states = combined_states
    residual = np.abs(np.asarray(evaluate_vector(barrier, variables, residual_states)))
    return combined[residual <= 1e-7]


def run_fast_check(
    problem: ProblemSpec,
    candidate: CandidateSpec,
    conditions: tuple[Condition, ...] | None = None,
) -> FastCheckResult:
    started_at_utc = datetime.now(UTC).isoformat()
    started_monotonic = time.monotonic()

    def timed(result: FastCheckResult) -> FastCheckResult:
        return replace(
            result,
            started_at_utc=started_at_utc,
            finished_at_utc=datetime.now(UTC).isoformat(),
            duration_seconds=time.monotonic() - started_monotonic,
        )

    if conditions is None:
        conditions = build_conditions(problem, candidate)
    screening_variables = problem.system.state_vars + fixed_parameter_names(problem)
    screening_box = fixed_parameter_screening_box(problem)
    query_specs = {
        item.kind: item.query for item in conditions if item.query is not None
    }
    digest = content_hash(candidate)

    def screening(kind: ConditionKind) -> ScreeningCondition:
        return ScreeningCondition(
            condition_id=f"{digest[:12]}:fast:{kind.value}",
            query=query_specs[kind],
        )

    hints: list[str] = []
    counts = {
        "initial": 0,
        "unsafe": 0,
        "analysis_boundary": ANALYSIS_AND_BOUNDARY_SAMPLES,
        "total_budget": TOTAL_SAMPLES,
    }

    evidence: list[CounterexampleEvidence] = []
    if ConditionKind.UNSAFE_SEPARATION not in query_specs:
        return timed(
            _run_lyapunov_fast_check(problem, query_specs, digest, hints, counts)
        )

    unsafe = screening(ConditionKind.UNSAFE_SEPARATION)
    unsafe_points = _region_points(problem, unsafe, XU_SAMPLES, 8192)
    counts["unsafe"] = unsafe_points.shape[0]
    evidence.extend(_find_confirmed(unsafe, unsafe_points))
    if unsafe_points.shape[0] < XU_SAMPLES:
        hints.append("unsafe region yielded fewer than 1500 deterministic samples")

    initial = (
        screening(ConditionKind.INITIAL_CONTAINMENT)
        if ConditionKind.INITIAL_CONTAINMENT in query_specs
        else None
    )
    initial_points = np.empty((0, len(screening_variables)))
    if initial is not None:
        initial_points = _region_points(problem, initial, XI_SAMPLES, 16384)
        counts["initial"] = initial_points.shape[0]
        evidence.extend(_find_confirmed(initial, initial_points))
        if initial_points.shape[0] < XI_SAMPLES:
            hints.append("initial region yielded fewer than 1500 deterministic samples")
    else:

        _sample_box(screening_box, screening_variables, XI_SAMPLES, 16384)
        counts["initial"] = XI_SAMPLES

    if ConditionKind.CERTIFIED_SET_IN_X in query_specs:
        certified = screening(ConditionKind.CERTIFIED_SET_IN_X)
        exterior = _sample_exterior_collar(
            problem.analysis_box,
            problem.system.state_vars,
            XI_SAMPLES,
            32768,
        )
        counts["exterior"] = exterior.shape[0]
        evidence.extend(_find_confirmed(certified, exterior))
        if exterior.shape[0] < XI_SAMPLES:
            hints.append("certified_set_in_X collar yielded fewer than 1500 samples")

    analysis = _sample_box(
        screening_box,
        screening_variables,
        ANALYSIS_AND_BOUNDARY_SAMPLES,
        24576,
    )
    if ConditionKind.CONTROL_ADMISSIBLE in query_specs:


        evidence.extend(
            _find_confirmed(
                screening(ConditionKind.CONTROL_ADMISSIBLE),
                analysis[:, : len(problem.system.state_vars)],
            )
        )
    if problem.system.kind.value == "discrete":
        discrete = screening(ConditionKind.DISCRETE_INDUCTIVE)


        discrete_points = (
            np.vstack((initial_points, analysis))
            if initial_points.size
            else analysis
        )
        evidence.extend(_find_confirmed(discrete, discrete_points))
    else:
        boundary = _boundary_candidates(problem, candidate, analysis)
        if boundary.size == 0:
            hints.append("no B=0 point found in the numerical analysis box")
        else:
            strict = screening(ConditionKind.LIE_STRICT)
            evidence.extend(_find_confirmed(strict, boundary))
            values = np.abs(
                np.asarray(
                    evaluate_vector(
                        candidate.certificate_ast,
                        problem.system.state_vars,
                        boundary[:, : len(problem.system.state_vars)],
                    )
                )
            )
            if np.any(values > 1e-12):
                hints.append("near-zero boundary candidates were retained as hints only")

    evidence = evidence[:MAX_COUNTEREXAMPLES]
    return timed(
        FastCheckResult(
            bool(evidence),
            evidence[0] if evidence else None,
            tuple(hints),
            counts,
            tuple(evidence),
        )
    )


def _run_lyapunov_fast_check(
    problem: ProblemSpec,
    query_specs: dict[ConditionKind, QuerySpec],
    digest: str,
    hints: list[str],
    counts: dict[str, int],
) -> FastCheckResult:


    counts["unsafe"] = 0
    if ConditionKind.SUBLEVEL_CONTAINS_INITIAL in query_specs:
        initial = ScreeningCondition(
            condition_id=f"{digest[:12]}:fast:{ConditionKind.SUBLEVEL_CONTAINS_INITIAL.value}",
            query=query_specs[ConditionKind.SUBLEVEL_CONTAINS_INITIAL],
        )
        initial_points = _region_points(problem, initial, XI_SAMPLES, 16384)
        counts["initial"] = initial_points.shape[0]
        evidence = list(_find_confirmed(initial, initial_points))
        leftover = max(0, XI_SAMPLES - initial_points.shape[0])
        if leftover:
            _sample_box(problem.analysis_box, problem.system.state_vars, leftover, 16384)
    else:
        _sample_box(problem.analysis_box, problem.system.state_vars, XI_SAMPLES, 16384)
        counts["initial"] = XI_SAMPLES
        evidence = []
    _sample_box(problem.analysis_box, problem.system.state_vars, XU_SAMPLES, 8192)
    analysis = _sample_box(
        problem.analysis_box,
        problem.system.state_vars,
        ANALYSIS_AND_BOUNDARY_SAMPLES,
        24576,
    )
    specials = np.vstack(
        (
            np.zeros((1, len(problem.system.state_vars))),
            analysis,
        )
    )
    exterior = None
    if ConditionKind.SUBLEVEL_IN_NEIGHBORHOOD in query_specs:
        exterior = _sample_exterior_collar(
            _neighborhood_box(problem),
            problem.system.state_vars,
            XI_SAMPLES,
            32768,
        )
        counts["exterior"] = exterior.shape[0]
    for kind, query in query_specs.items():
        if kind == ConditionKind.SUBLEVEL_CONTAINS_INITIAL:
            continue
        condition = ScreeningCondition(
            condition_id=f"{digest[:12]}:fast:{kind.value}",
            query=query,
        )
        points = (
            exterior
            if kind == ConditionKind.SUBLEVEL_IN_NEIGHBORHOOD and exterior is not None
            else specials
        )
        evidence.extend(_find_confirmed(condition, points))
    evidence = evidence[:MAX_COUNTEREXAMPLES]
    return FastCheckResult(
        bool(evidence),
        evidence[0] if evidence else None,
        tuple(hints),
        counts,
        tuple(evidence),
    )
