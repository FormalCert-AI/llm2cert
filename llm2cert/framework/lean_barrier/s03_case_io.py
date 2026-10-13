"""Load benchmark records and construct problem inputs."""
from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from .s02_expressions import add, const, div, expand_call, mul, neg, pow_nat, sub, variables
from .s01_models import (
    BoxSpec,
    CandidateProposalLike,
    CandidateSpec,
    ConstExpr,
    Constraint,
    ConstraintGroup,
    ControllerAssignment,
    ControllerAST,
    DynamicsKind,
    Expr,
    FixedParameterSpec,
    IndexedBlockDynamicsSpec,
    IndexedFamilyDomainSpec,
    IndexedFamilyParameterSpec,
    IndexedFamilySpec,
    IndexedFamilyTargetSpec,
    IndexedSharedControllerSpec,
    IndexedStateFamilySpec,
    NeighborhoodSpec,
    OriginPolicy,
    PiExpr,
    ProblemSpec,
    Rational,
    RegionSpec,
    Relation,
    SafetyInterpretation,
    SourceDomainSpec,
    StabilityKind,
    SystemSpec,
    TaskType,
    VarExpr,
)


class BarrierBenchError(ValueError):
    pass


@dataclass(frozen=True)
class SignConversion:
    barrier: str = "B_ours = -B_bench"
    initial: str = "B_bench <= 0 becomes B_ours >= 0"
    unsafe: str = "B_bench > 0 becomes B_ours < 0"
    lie: str = "L_f B_bench <= 0 becomes L_f B_ours >= 0"
    discrete: str = "B_bench(f(x)) <= 0 becomes B_ours(f(x)) >= 0"


@dataclass(frozen=True)
class ImportedCase:
    bench_id: int
    problem: ProblemSpec
    converted_candidate: CandidateSpec | None
    sign_conversion: SignConversion = SignConversion()


class _ExpressionParser:
    def __init__(self, source: str) -> None:
        self.source = source.strip().replace("^", "**")
        self.tree = ast.parse(self.source, mode="eval")

    def parse(self) -> Expr:
        return self._node(self.tree.body)

    def _number(self, node: ast.Constant) -> Expr:
        token = ast.get_source_segment(self.source, node)
        if token is None:
            token = repr(node.value)
        return const(Fraction(token))

    def _power(self, base: Expr, exponent: Expr) -> Expr:


        if not isinstance(exponent, ConstExpr):
            raise BarrierBenchError(
                "power exponent must be an exact numeric constant; "
                "use sqrt(base) or base**(1/2) for a square root"
            )
        value = Fraction(exponent.value.numerator, exponent.value.denominator)
        try:
            if value.denominator == 1:
                integer = value.numerator
                if integer >= 0:
                    return pow_nat(base, integer)
                return div(const(1), pow_nat(base, -integer))
            if value.denominator == 2:
                root = expand_call("sqrt", base)
                magnitude = pow_nat(root, abs(value.numerator))
                return magnitude if value > 0 else div(const(1), magnitude)
        except ValueError as error:
            raise BarrierBenchError(str(error)) from error
        raise BarrierBenchError(
            f"unsupported exact exponent {value}; integer and half-integer powers "
            "are supported, including base**(1/2) and base**0.5"
        )

    def _node(self, node: ast.AST) -> Expr:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return self._number(node)
        if isinstance(node, ast.Name):
            if node.id.lower() in {"pi", "π"}:
                return PiExpr()
            return VarExpr(name=node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return neg(self._node(node.operand))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
            return self._node(node.operand)
        if isinstance(node, ast.BinOp):
            left = self._node(node.left)
            right = self._node(node.right)
            if isinstance(node.op, ast.Add):
                return add(left, right)
            if isinstance(node.op, ast.Sub):
                return sub(left, right)
            if isinstance(node.op, ast.Mult):
                return mul(left, right)
            if isinstance(node.op, ast.Div):
                try:
                    return div(left, right)
                except ValueError as error:
                    raise BarrierBenchError(str(error)) from error
            if isinstance(node.op, ast.Pow):
                return self._power(left, right)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and len(node.args) == 1:
            argument = self._node(node.args[0])
            try:
                return expand_call(node.func.id, argument)
            except ValueError as error:
                raise BarrierBenchError(str(error)) from error
        raise BarrierBenchError(f"unsupported expression syntax: {ast.dump(node)}")


def parse_expression(source: str) -> Expr:
    normalized = re.sub(r"([A-Za-z_]\w*)\[k\]", r"\1", source)
    try:
        return _ExpressionParser(normalized).parse()
    except BarrierBenchError:
        raise
    except (SyntaxError, TypeError, ValueError) as error:
        detail = getattr(error, "msg", str(error))
        raise BarrierBenchError(f"invalid expression {source!r}: {detail}") from error


def _proposal_rational(value: str | None, field: str) -> Rational | None:
    if value is None:
        return None
    expression = parse_expression(value)
    if not isinstance(expression, ConstExpr):
        raise BarrierBenchError(f"{field} must be an exact constant, got {value!r}")
    return expression.value


def _proposal_constant_expr(value: str | None, field: str) -> Expr | None:
    if value is None:
        return None
    expression = parse_expression(value)
    names = variables(expression)
    if names:
        raise BarrierBenchError(
            f"{field} must be state-independent; found variables {', '.join(sorted(names))}"
        )
    return expression


def candidate_from_proposal(proposal: CandidateProposalLike) -> CandidateSpec:


    try:
        certificate = parse_expression(proposal.certificate)
    except BarrierBenchError as error:
        raise BarrierBenchError(f"certificate: {error}") from error

    assignments: list[ControllerAssignment] = []
    for controller in proposal.controllers:
        try:
            expression = parse_expression(controller.expression)
        except BarrierBenchError as error:
            raise BarrierBenchError(f"controller {controller.variable}: {error}") from error
        assignments.append(
            ControllerAssignment(variable=controller.variable, expression=expression)
        )

    return CandidateSpec(
        certificate_ast=certificate,
        controller_ast=ControllerAST(assignments=tuple(assignments)),
        construction_summary=proposal.construction_summary,
        assumptions=proposal.assumptions,
        level_c=_proposal_constant_expr(getattr(proposal, "level_c", None), "level_c"),
        exp_c1=_proposal_rational(getattr(proposal, "exp_c1", None), "exp_c1"),
        exp_c2=_proposal_rational(getattr(proposal, "exp_c2", None), "exp_c2"),
        exp_c3=_proposal_rational(getattr(proposal, "exp_c3", None), "exp_c3"),
    )


def _rational(value: float | str | Fraction) -> Rational:
    fraction = Fraction(str(value))
    return Rational(numerator=fraction.numerator, denominator=fraction.denominator)


def _box(state_vars: tuple[str, ...], bounds: Sequence[Sequence[float | str | Fraction]]) -> BoxSpec:
    if len(bounds) != len(state_vars):
        raise BarrierBenchError("set dimension does not match dynamics")
    return BoxSpec(
        lower={name: _rational(bounds[index][0]) for index, name in enumerate(state_vars)},
        upper={name: _rational(bounds[index][1]) for index, name in enumerate(state_vars)},
    )


def _box_constraints(box: BoxSpec) -> tuple[Constraint, ...]:
    from .s01_models import ConstExpr

    result: list[Constraint] = []
    for name in box.lower:
        result.extend(
            (
                Constraint(
                    lhs=VarExpr(name=name),
                    relation=Relation.GE,
                    rhs=ConstExpr(value=box.lower[name]),
                ),
                Constraint(
                    lhs=VarExpr(name=name),
                    relation=Relation.LE,
                    rhs=ConstExpr(value=box.upper[name]),
                ),
            )
        )
    return tuple(result)


def _region_from_box(
    state_vars: tuple[str, ...],
    bounds: Sequence[Sequence[float | str | Fraction]],
    *,
    complement: bool,
) -> RegionSpec:


    if len(bounds) != len(state_vars):
        raise BarrierBenchError("set dimension does not match dynamics")
    endpoints: list[tuple[Expr, Expr]] = []
    for index, name in enumerate(state_vars):
        pair = bounds[index]
        if len(pair) != 2:
            raise BarrierBenchError(f"box bound for {name} must contain [lower, upper]")
        lower = parse_expression(str(pair[0]))
        upper = parse_expression(str(pair[1]))
        for label, endpoint in (("lower", lower), ("upper", upper)):
            names = variables(endpoint)
            if names:
                raise BarrierBenchError(
                    f"box {label} endpoint for {name} must be state-independent; "
                    f"found variables {', '.join(sorted(names))}"
                )
        endpoints.append((lower, upper))

    if all(
        isinstance(endpoint, ConstExpr)
        for pair in endpoints
        for endpoint in pair
    ):
        box = BoxSpec(
            lower={name: endpoints[index][0].value for index, name in enumerate(state_vars)},
            upper={name: endpoints[index][1].value for index, name in enumerate(state_vars)},
        )
        if not complement:
            return RegionSpec(bounds=box)
        endpoints = [
            (ConstExpr(value=box.lower[name]), ConstExpr(value=box.upper[name]))
            for name in state_vars
        ]

    if complement:
        outside: list[ConstraintGroup] = []
        for name, (lower, upper) in zip(state_vars, endpoints, strict=True):
            outside.extend(
                (
                    ConstraintGroup(
                        constraints=(
                            Constraint(
                                lhs=VarExpr(name=name), relation=Relation.LT, rhs=lower
                            ),
                        )
                    ),
                    ConstraintGroup(
                        constraints=(
                            Constraint(
                                lhs=VarExpr(name=name), relation=Relation.GT, rhs=upper
                            ),
                        )
                    ),
                )
            )
        return RegionSpec(any_of=tuple(outside))

    constraints: list[Constraint] = []
    for name, (lower, upper) in zip(state_vars, endpoints, strict=True):
        constraints.extend(
            (
                Constraint(lhs=VarExpr(name=name), relation=Relation.GE, rhs=lower),
                Constraint(lhs=VarExpr(name=name), relation=Relation.LE, rhs=upper),
            )
        )
    return RegionSpec(constraints=tuple(constraints))


def _constraint(raw: dict[str, Any]) -> Constraint:


    try:
        relation = Relation(str(raw["relation"]).lower())
    except (KeyError, ValueError) as error:
        raise BarrierBenchError("constraint relation must be one of lt/le/eq/ge/gt") from error
    try:
        lhs = parse_expression(str(raw["lhs"]))
        rhs = parse_expression(str(raw["rhs"]))
    except KeyError as error:
        raise BarrierBenchError("constraint requires lhs, relation, and rhs") from error
    return Constraint(lhs=lhs, relation=relation, rhs=rhs)


def _hull(boxes: Iterable[BoxSpec], state_vars: tuple[str, ...]) -> BoxSpec | None:
    values = tuple(boxes)
    if not values:
        return None
    lower: dict[str, Rational] = {}
    upper: dict[str, Rational] = {}
    for name in state_vars:
        lo = min(Fraction(box.lower[name].numerator, box.lower[name].denominator) for box in values)
        hi = max(Fraction(box.upper[name].numerator, box.upper[name].denominator) for box in values)
        lower[name] = Rational(numerator=lo.numerator, denominator=lo.denominator)
        upper[name] = Rational(numerator=hi.numerator, denominator=hi.denominator)
    return BoxSpec(lower=lower, upper=upper)


def _region(raw: dict[str, Any], state_vars: tuple[str, ...]) -> RegionSpec:
    kind = raw.get("type")
    complement = bool(raw.get("complement", False))
    if kind in ("bounds", "box"):
        return _region_from_box(state_vars, raw["bounds"], complement=complement)
    if kind == "ball":
        center = raw["center"]
        radius = Fraction(str(raw["radius"]))
        if len(center) != len(state_vars):
            raise BarrierBenchError("ball dimension does not match dynamics")
        squared = add(
            *(
                pow_nat(sub(VarExpr(name=name), const(Fraction(str(center[index])))), 2)
                for index, name in enumerate(state_vars)
            )
        )
        relation = Relation.GE if complement else Relation.LE
        constraint = Constraint(lhs=squared, relation=relation, rhs=const(radius**2))
        if complement:
            return RegionSpec(constraints=(constraint,))
        bounds = [
            [Fraction(str(center[index])) - radius, Fraction(str(center[index])) + radius]
            for index in range(len(state_vars))
        ]
        return RegionSpec(constraints=(constraint,), bounds=_box(state_vars, bounds))
    if kind in {"constraint", "constraints"}:
        bounds = None
        if raw.get("bounds") is not None:
            bounds = _box(state_vars, raw["bounds"])
        if kind == "constraint":
            constraints = (_constraint(raw),)
        else:
            items = raw.get("constraints")
            if not isinstance(items, list) or not items:
                raise BarrierBenchError("constraints region requires a nonempty constraints array")
            constraints = tuple(_constraint(item) for item in items)
        return RegionSpec(bounds=bounds, constraints=constraints)
    if kind == "union":
        children = tuple(_region(child, state_vars) for child in raw.get("sets", ()))
        if not children:
            raise BarrierBenchError("union must contain at least one set")
        groups: list[ConstraintGroup] = []
        boxes: list[BoxSpec] = []
        for child in children:
            child_shared = (
                _box_constraints(child.bounds) if child.bounds is not None else ()
            ) + child.constraints
            if child.any_of:
                for disjunct in child.any_of:
                    groups.append(ConstraintGroup(constraints=child_shared + disjunct.constraints))
            else:
                groups.append(ConstraintGroup(constraints=child_shared))
            if child.bounds is not None:
                boxes.append(child.bounds)
        bounds = _hull(boxes, state_vars) if len(boxes) == len(children) else None
        return RegionSpec(any_of=tuple(groups), bounds=bounds)
    raise BarrierBenchError(f"unsupported set type: {kind!r}")


def _parse_assignments(source: str, *, discrete: bool) -> tuple[tuple[str, ...], tuple[Expr, ...]]:
    variables: list[str] = []
    expressions: list[Expr] = []
    for assignment in source.split(","):
        lhs, separator, rhs = assignment.partition("=")
        if not separator:
            raise BarrierBenchError(f"invalid assignment: {assignment}")
        lhs = lhs.strip()
        if discrete:
            match = re.fullmatch(r"([A-Za-z_]\w*)\[k\+1\]", lhs)
        else:
            match = re.fullmatch(r"d([A-Za-z_]\w*)/dt", lhs)
        if not match:
            raise BarrierBenchError(f"invalid dynamics lhs: {lhs}")
        variables.append(match.group(1))
        expressions.append(parse_expression(rhs.strip()))
    return tuple(variables), tuple(expressions)


def _controller(source: str | None) -> ControllerAST:
    if not source:
        return ControllerAST()
    assignments: list[ControllerAssignment] = []
    for raw in source.split(","):
        lhs, separator, rhs = raw.partition("=")
        if not separator:
            raise BarrierBenchError(f"invalid controller assignment: {raw}")
        variable = re.sub(r"\[k\]$", "", lhs.strip())
        assignments.append(
            ControllerAssignment(variable=variable, expression=parse_expression(rhs.strip()))
        )
    return ControllerAST(assignments=tuple(assignments))


def _analysis_box(
    state_vars: tuple[str, ...],
    regions: tuple[RegionSpec | None, ...],
    radius: Fraction,
) -> BoxSpec:
    bounded = [region.bounds for region in regions if region is not None and region.bounds]
    hull = _hull(bounded, state_vars)
    if hull is None:
        return BoxSpec(
            lower={
                name: Rational(numerator=-radius.numerator, denominator=radius.denominator)
                for name in state_vars
            },
            upper={
                name: Rational(numerator=radius.numerator, denominator=radius.denominator)
                for name in state_vars
            },
        )
    lower: dict[str, Rational] = {}
    upper: dict[str, Rational] = {}
    for name in state_vars:
        lo = Fraction(hull.lower[name].numerator, hull.lower[name].denominator)
        hi = Fraction(hull.upper[name].numerator, hull.upper[name].denominator)
        margin = max((hi - lo) / 10, Fraction(1, 10))
        lo = max(lo - margin, -radius)
        hi = min(hi + margin, radius)
        if lo >= hi:
            lo, hi = -radius, radius
        lower[name] = Rational(numerator=lo.numerator, denominator=lo.denominator)
        upper[name] = Rational(numerator=hi.numerator, denominator=hi.denominator)
    return BoxSpec(lower=lower, upper=upper)


def _q(value: Rational) -> Fraction:
    return Fraction(value.numerator, value.denominator)


def box_contained(inner: BoxSpec, outer: BoxSpec) -> bool:
    for name in inner.lower:
        if _q(inner.lower[name]) < _q(outer.lower[name]):
            return False
        if _q(inner.upper[name]) > _q(outer.upper[name]):
            return False
    return True


def resolve_case_path(path: str | Path) -> Path:


    resolved = Path(path)
    if resolved.exists():
        return resolved
    if resolved.parent.name == "cases":
        for task in ("safety", "invariant", "stability", "roa"):
            alternative = resolved.parent / task / resolved.name
            if alternative.exists():
                return alternative
    return resolved


def _optional_rational(raw: dict[str, Any], key: str) -> Rational | None:
    if key not in raw or raw[key] is None:
        return None
    return _rational(raw[key])


def _optional_constant_expr(raw: dict[str, Any], key: str) -> Expr | None:
    if key not in raw or raw[key] is None:
        return None
    return _proposal_constant_expr(str(raw[key]), key)


def _neighborhood(raw: dict[str, Any] | None, state_vars: tuple[str, ...]) -> NeighborhoodSpec | None:
    if raw is None:
        return None
    if raw.get("unbounded") or raw.get("type") == "unbounded":
        return NeighborhoodSpec(unbounded=True)
    return NeighborhoodSpec(unbounded=False, region=_region(raw, state_vars))


def _source_domain(raw: dict[str, Any] | None) -> SourceDomainSpec | None:
    if raw is None:
        return None
    return SourceDomainSpec(
        description=str(raw.get("description", "")),
        shape=None if raw.get("shape") is None else str(raw["shape"]),
        inner_radius=_optional_rational(raw, "inner_radius"),
        outer_radius=_optional_rational(raw, "outer_radius"),
    )


def _fixed_parameters(raw: object) -> tuple[FixedParameterSpec, ...]:


    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise BarrierBenchError("fixed_parameters must be an array")
    result: list[FixedParameterSpec] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise BarrierBenchError(f"fixed_parameters[{index}] must be an object")
        unknown = set(item) - {"name", "bounds", "time_semantics", "quantifier"}
        if unknown:
            raise BarrierBenchError(
                f"fixed_parameters[{index}] has unknown fields: {sorted(unknown)}"
            )
        if "name" not in item or "bounds" not in item:
            raise BarrierBenchError(
                f"fixed_parameters[{index}] requires name and bounds"
            )
        bounds = item["bounds"]
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            raise BarrierBenchError(
                f"fixed_parameters[{index}].bounds must contain [lower, upper]"
            )
        time_semantics = str(item.get("time_semantics", "fixed"))
        quantifier = str(item.get("quantifier", "forall"))
        if time_semantics != "fixed":
            raise BarrierBenchError(
                f"fixed_parameters[{index}].time_semantics must be 'fixed'"
            )
        if quantifier != "forall":
            raise BarrierBenchError(
                f"fixed_parameters[{index}].quantifier must be 'forall'"
            )
        try:
            result.append(
                FixedParameterSpec(
                    name=str(item["name"]),
                    lower=_rational(bounds[0]),
                    upper=_rational(bounds[1]),
                    time_semantics="fixed",
                    quantifier="forall",
                )
            )
        except (TypeError, ValueError) as error:
            raise BarrierBenchError(
                f"invalid fixed_parameters[{index}]: {error}"
            ) from error
    return tuple(result)


def _indexed_family(raw: object) -> IndexedFamilySpec | None:


    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise BarrierBenchError("indexed_family must be an object")
    expected_fields = {
        "schema_version",
        "time_domain",
        "parameter",
        "state_dimension",
        "binder",
        "state_families",
        "block_dynamics",
        "shared_controller",
        "equilibrium",
        "domain",
        "target",
    }
    unknown = set(raw) - expected_fields
    if unknown:
        raise BarrierBenchError(f"indexed_family has unknown fields: {sorted(unknown)}")
    required = expected_fields - {"binder", "shared_controller", "equilibrium"}
    missing = required - set(raw)
    if missing:
        raise BarrierBenchError(f"indexed_family is missing fields: {sorted(missing)}")

    parameter_raw = raw["parameter"]
    if not isinstance(parameter_raw, dict):
        raise BarrierBenchError("indexed_family.parameter must be an object")
    families_raw = raw["state_families"]
    if not isinstance(families_raw, (list, tuple)):
        raise BarrierBenchError("indexed_family.state_families must be an array")
    dynamics_raw = raw["block_dynamics"]
    if not isinstance(dynamics_raw, (list, tuple)):
        raise BarrierBenchError("indexed_family.block_dynamics must be an array")
    domain_raw = raw["domain"]
    if not isinstance(domain_raw, dict):
        raise BarrierBenchError("indexed_family.domain must be an object")
    target_raw = raw["target"]
    if not isinstance(target_raw, dict):
        raise BarrierBenchError("indexed_family.target must be an object")
    controller_raw = raw.get("shared_controller")
    if controller_raw is not None and not isinstance(controller_raw, dict):
        raise BarrierBenchError("indexed_family.shared_controller must be an object or null")

    try:
        return IndexedFamilySpec(
            schema_version=str(raw["schema_version"]),
            time_domain=str(raw["time_domain"]),
            parameter=IndexedFamilyParameterSpec(
                name=str(parameter_raw["name"]),
                domain=str(parameter_raw["domain"]),
            ),
            state_dimension=str(raw["state_dimension"]),
            binder=str(raw.get("binder", "i")),
            state_families=tuple(
                IndexedStateFamilySpec(name=str(item["name"]))
                for item in families_raw
            ),
            block_dynamics=tuple(
                IndexedBlockDynamicsSpec(
                    state_family=str(item["state_family"]),
                    rhs=parse_expression(str(item["rhs"])),
                )
                for item in dynamics_raw
            ),
            shared_controller=(
                None
                if controller_raw is None
                else IndexedSharedControllerSpec(
                    name=str(controller_raw["name"]),
                    argument=str(controller_raw["argument"]),
                    input_family=str(controller_raw["input_family"]),
                    output_symbol=str(controller_raw["output_symbol"]),
                    observation=str(controller_raw["observation"]),
                    shared_across_indices=controller_raw["shared_across_indices"],
                    zero_at_origin=controller_raw["zero_at_origin"],
                )
            ),
            equilibrium=str(raw.get("equilibrium", "zero")),
            domain=IndexedFamilyDomainSpec(
                kind=str(domain_raw["kind"]),
                lower=(
                    None if domain_raw.get("lower") is None else _rational(domain_raw["lower"])
                ),
                upper=(
                    None if domain_raw.get("upper") is None else _rational(domain_raw["upper"])
                ),
            ),
            target=IndexedFamilyTargetSpec(
                kind=str(target_raw["kind"]),
                stability_kind=StabilityKind(str(target_raw["stability_kind"])),
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise BarrierBenchError(f"invalid indexed_family contract: {error}") from error


def _box_as_bounds(box: BoxSpec, state_vars: tuple[str, ...]) -> list[list[Fraction]]:
    return [[_q(box.lower[name]), _q(box.upper[name])] for name in state_vars]


def import_case(raw: dict[str, Any], bench_id: int, *, analysis_radius: int = 10) -> ImportedCase:
    problem_raw = raw["problem"]
    indexed_family = _indexed_family(problem_raw.get("indexed_family"))
    if indexed_family is not None:
        problem_id = str(problem_raw.get("problem_id", f"barrierbench_{bench_id:03d}"))
        if problem_id not in {"dcb_ext_p1_003", "dcb_ext_p1_004", "dcb_ext_p2_001"}:
            raise BarrierBenchError(
                "indexed_family is supported only for Systems 82, 84, and 86"
            )
        forbidden_projection = {
            "dynamics",
            "controller_parameters",
            "controller_observations",
            "control_bounds",
            "equilibrium",
            "neighborhood",
            "analysis_bounds",
            "formal_domain",
            "stability_kind",
            "initial_set",
            "unsafe_set",
            "fixed_parameters",
        } & set(problem_raw)
        if forbidden_projection:
            raise BarrierBenchError(
                "indexed-family records must not contain a frozen ordinary projection: "
                f"{sorted(forbidden_projection)}"
            )
        expected_task = (
            TaskType.STABILITY
            if indexed_family.target.kind == "global_asymptotic_stability"
            else TaskType.ROA
        )
        task_type = TaskType(str(problem_raw.get("task_type", expected_task.value)))
        try:
            problem = ProblemSpec(
                problem_id=problem_id,
                name=str(problem_raw.get("name", f"BarrierBench case {bench_id}")),
                indexed_family=indexed_family,
                task_type=task_type,
                source=str(
                    problem_raw.get("source", f"imported case, 0-based id {bench_id}")
                ),
                assumptions=tuple(str(item) for item in problem_raw.get("assumptions", ())),
            )
        except ValueError as error:
            raise BarrierBenchError(f"invalid indexed-family problem: {error}") from error
        if raw.get("certificate") is not None or raw.get("barrier") is not None:
            raise BarrierBenchError(
                "indexed-family executable records do not accept fixed-dimensional certificates"
            )
        return ImportedCase(bench_id=bench_id, problem=problem, converted_candidate=None)

    dynamics_text = problem_raw["dynamics"]
    discrete = "[k+1]" in dynamics_text
    state_vars, dynamics = _parse_assignments(dynamics_text, discrete=discrete)
    controls_text = problem_raw.get("controller_parameters", "")
    control_vars = tuple(part.strip() for part in controls_text.split(",") if part.strip())
    observations_raw = problem_raw.get("controller_observations")
    control_observations = None
    if observations_raw is not None:
        if not isinstance(observations_raw, dict):
            raise BarrierBenchError("controller_observations must be an object")
        control_observations = {}
        for control, observed in observations_raw.items():
            if not isinstance(observed, (list, tuple)):
                raise BarrierBenchError(
                    f"controller_observations[{control}] must be an array"
                )
            control_observations[str(control)] = tuple(
                str(state) for state in observed
            )
    task_type = TaskType(str(problem_raw.get("task_type", TaskType.SAFETY.value)))
    initial = (
        _region(problem_raw["initial_set"], state_vars)
        if problem_raw.get("initial_set") is not None
        else None
    )
    unsafe = (
        _region(problem_raw["unsafe_set"], state_vars)
        if problem_raw.get("unsafe_set") is not None
        else None
    )
    neighborhood = _neighborhood(problem_raw.get("neighborhood"), state_vars)
    analysis_bounds = problem_raw.get("analysis_bounds")
    analysis_box = (
        _box(state_vars, analysis_bounds)
        if analysis_bounds is not None
        else _analysis_box(
            state_vars,
            (initial, unsafe, None if neighborhood is None else neighborhood.region),
            Fraction(analysis_radius),
        )
    )
    interpretation = SafetyInterpretation(
        str(problem_raw.get("safety_interpretation", SafetyInterpretation.CONDITIONAL_IN_X.value))
    )
    if interpretation == SafetyInterpretation.OUTSIDE_X_IS_UNSAFE and unsafe is None:
        unsafe = _region(
            {
                "type": "box",
                "bounds": _box_as_bounds(analysis_box, state_vars),
                "complement": True,
            },
            state_vars,
        )
    equilibrium = None
    if problem_raw.get("equilibrium") is not None:
        equilibrium = tuple(_rational(value) for value in problem_raw["equilibrium"])
    stability_kind = None
    if problem_raw.get("stability_kind") is not None:
        stability_kind = StabilityKind(str(problem_raw["stability_kind"]))
    origin_policy = OriginPolicy(
        str(problem_raw.get("origin_policy", OriginPolicy.EXCLUDE_POINT.value))
    )
    formal_domain = str(problem_raw.get("formal_domain", "analysis_box"))
    if formal_domain not in {"analysis_box", "unbounded"}:
        raise BarrierBenchError("formal_domain must be 'analysis_box' or 'unbounded'")
    control_set = None
    if problem_raw.get("control_bounds") is not None:
        if not control_vars:
            raise BarrierBenchError("control_bounds requires controller_parameters")
        control_set = _box(control_vars, problem_raw["control_bounds"])
    problem = ProblemSpec(
        problem_id=str(problem_raw.get("problem_id", f"barrierbench_{bench_id:03d}")),
        name=str(problem_raw.get("name", f"BarrierBench case {bench_id}")),
        system=SystemSpec(
            kind=DynamicsKind.DISCRETE if discrete else DynamicsKind.CONTINUOUS,
            state_vars=state_vars,
            control_vars=control_vars,
            control_observations=control_observations,
            dynamics=dynamics,
        ),
        fixed_parameters=_fixed_parameters(problem_raw.get("fixed_parameters")),
        initial_set=initial,
        unsafe_set=unsafe,
        analysis_box=analysis_box,
        formal_domain_unbounded=formal_domain == "unbounded",
        control_set=control_set,
        task_type=task_type,
        equilibrium=equilibrium,
        neighborhood=neighborhood,
        stability_kind=stability_kind,
        source_domain=_source_domain(problem_raw.get("source_domain")),
        origin_policy=origin_policy,
        safety_interpretation=interpretation,
        source=str(
            problem_raw.get(
                "source",
                f"imported case, 0-based id {bench_id}",
            )
        ),
        assumptions=tuple(str(item) for item in problem_raw.get("assumptions", ())),
    )
    if (
        interpretation == SafetyInterpretation.CONDITIONAL_IN_X
        and not problem.formal_domain_unbounded
        and unsafe is not None
        and unsafe.bounds is not None
        and not box_contained(unsafe.bounds, analysis_box)
    ):
        raise BarrierBenchError("unsafe_set bounds must lie inside the working domain X")
    if (
        task_type == TaskType.ROA
        and initial is not None
        and neighborhood is not None
        and not neighborhood.unbounded
        and neighborhood.region is not None
        and initial.bounds is not None
        and neighborhood.region.bounds is not None
        and not box_contained(initial.bounds, neighborhood.region.bounds)
    ):
        raise BarrierBenchError("initial set X_I must lie inside neighborhood N")
    candidate: CandidateSpec | None = None
    summary = "BarrierBench sub-level certificate converted centrally to v1 super-level semantics."
    level_c = _optional_constant_expr(raw, "level_c")
    exp_c1 = _optional_rational(raw, "exp_c1")
    exp_c2 = _optional_rational(raw, "exp_c2")
    exp_c3 = _optional_rational(raw, "exp_c3")
    if raw.get("certificate") is not None:
        candidate = CandidateSpec(
            certificate_ast=parse_expression(str(raw["certificate"])),
            controller_ast=_controller(raw.get("controllers")),
            construction_summary=str(raw.get("construction_summary", "imported certificate")),
            assumptions=(),
            level_c=level_c,
            exp_c1=exp_c1,
            exp_c2=exp_c2,
            exp_c3=exp_c3,
        )
    elif raw.get("barrier") is not None:
        candidate = CandidateSpec(
            certificate_ast=neg(parse_expression(raw["barrier"])),
            controller_ast=_controller(raw.get("controllers")),
            construction_summary=summary,
            assumptions=(),
            level_c=level_c,
            exp_c1=exp_c1,
            exp_c2=exp_c2,
            exp_c3=exp_c3,
        )
    from .tasks import profile_for

    profile_for(problem).validate(problem, candidate)
    return ImportedCase(bench_id=bench_id, problem=problem, converted_candidate=candidate)
