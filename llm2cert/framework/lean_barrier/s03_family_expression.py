"""Parse expressions for dimension-indexed system families."""
from __future__ import annotations

import ast
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .s01_models import (
    CandidateProposalLike,
    Expr,
    Identifier,
    ProblemSpec,
    Rational,
    StrictModel,
)
from .s02_expressions import content_hash, variables
from .s03_case_io import (
    BarrierBenchError,
    _proposal_constant_expr,
    _proposal_rational,
    parse_expression,
)

FamilyName = Literal["x", "y"]
FamilyExtent = Literal["m", "n"]
FamilyProblemId = Literal["dcb_ext_p1_003", "dcb_ext_p1_004", "dcb_ext_p2_001"]
_PLACEHOLDER_PREFIX = "__family_indexed_"
_FAMILY_CASES: dict[str, tuple[FamilyExtent, tuple[FamilyName, ...]]] = {
    "dcb_ext_p1_003": ("m", ("x", "y")),
    "dcb_ext_p1_004": ("m", ("x", "y")),
    "dcb_ext_p2_001": ("n", ("x",)),
}


class IndexedVarRef(StrictModel):


    kind: Literal["indexed_var"] = "indexed_var"
    family: FamilyName
    index: Identifier

    @property
    def placeholder(self) -> str:
        return f"{_PLACEHOLDER_PREFIX}{self.family}"


class FamilySumExpr(StrictModel):


    kind: Literal["finite_sum"] = "finite_sum"
    binder: Identifier
    extent: FamilyExtent
    state_families: tuple[FamilyName, ...]
    body: Expr
    indexed_variables: tuple[IndexedVarRef, ...]

    @field_validator("state_families")
    @classmethod
    def supported_layout(cls, value: tuple[FamilyName, ...]) -> tuple[FamilyName, ...]:
        if value not in {("x",), ("x", "y")}:
            raise ValueError("state_families must be ('x',) or ('x', 'y')")
        return value

    @model_validator(mode="after")
    def closed_body(self) -> FamilySumExpr:
        if not self.indexed_variables:
            raise ValueError("finite-sum body must contain an indexed state variable")
        if any(reference.index != self.binder for reference in self.indexed_variables):
            raise ValueError("every indexed state variable must use the sum binder")
        referenced = {reference.family for reference in self.indexed_variables}
        if not referenced <= set(self.state_families):
            raise ValueError("indexed state variable is not part of this family layout")
        expected = {reference.placeholder for reference in self.indexed_variables}
        if variables(self.body) != expected:
            raise ValueError("finite-sum body contains a free or malformed variable")
        return self


class FamilyCandidateSpec(StrictModel):


    schema_version: Literal["lean-barrier.family-candidate.v1"] = (
        "lean-barrier.family-candidate.v1"
    )
    problem_id: FamilyProblemId
    family_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    certificate_family_ast: FamilySumExpr
    shared_controller_ast: Expr | None = None
    construction_summary: str
    assumptions: tuple[str, ...] = ()
    level_c: Expr | None = None
    exp_c1: Rational | None = None
    exp_c2: Rational | None = None
    exp_c3: Rational | None = None

    @model_validator(mode="after")
    def matches_family_problem(self) -> FamilyCandidateSpec:
        extent, state_families = _FAMILY_CASES[self.problem_id]
        certificate = self.certificate_family_ast
        if certificate.extent != extent or certificate.state_families != state_families:
            raise ValueError("family certificate does not match its benchmark problem")
        if self.problem_id == "dcb_ext_p2_001":
            if self.shared_controller_ast is None:
                raise ValueError("System 86 requires one symbolic shared controller kappa(s)")
            if not variables(self.shared_controller_ast) <= {"s"}:
                raise ValueError("System 86 shared controller may contain only s")
        elif self.shared_controller_ast is not None:
            raise ValueError("Systems 82 and 84 do not have a controller")
        return self


class _IndexedBodyRewriter(ast.NodeTransformer):
    def __init__(self, binder: str, state_families: tuple[FamilyName, ...]) -> None:
        self.binder = binder
        self.state_families = set(state_families)
        self.references: set[FamilyName] = set()

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id.startswith(_PLACEHOLDER_PREFIX):
            raise BarrierBenchError("reserved family-expression identifier")
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        if not isinstance(node.func, ast.Name):
            return self.generic_visit(node)
        family = node.func.id
        if family == "sum":
            raise BarrierBenchError("nested finite sums are not supported")
        if family not in {"x", "y"}:
            return self.generic_visit(node)
        if family not in self.state_families:
            raise BarrierBenchError(f"indexed family {family!r} is not available in this system")
        if node.keywords or len(node.args) != 1:
            raise BarrierBenchError(f"{family}(...) requires exactly one positional index")
        index = node.args[0]
        if not isinstance(index, ast.Name) or index.id != self.binder:
            raise BarrierBenchError(f"{family}(...) must use the bound index {self.binder!r}")
        self.references.add(family)
        return ast.copy_location(
            ast.Name(id=f"{_PLACEHOLDER_PREFIX}{family}", ctx=ast.Load()),
            node,
        )


def parse_family_sum(
    source: str,
    *,
    expected_extent: FamilyExtent,
    state_families: tuple[FamilyName, ...],
    expected_binder: str = "i",
) -> FamilySumExpr:


    if expected_extent not in {"m", "n"}:
        raise BarrierBenchError("family extent must be 'm' or 'n'")
    if state_families not in {("x",), ("x", "y")}:
        raise BarrierBenchError("state_families must be ('x',) or ('x', 'y')")
    normalized = source.strip().replace("^", "**")
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as error:
        raise BarrierBenchError(
            f"invalid family expression {source!r}: {error.msg}"
        ) from error
    root = tree.body
    if not (
        isinstance(root, ast.Call)
        and isinstance(root.func, ast.Name)
        and root.func.id == "sum"
        and not root.keywords
        and len(root.args) == 3
    ):
        raise BarrierBenchError("family certificate must be sum(i, m|n, body)")
    binder_node, extent_node, body_node = root.args
    if not isinstance(binder_node, ast.Name) or binder_node.id != expected_binder:
        raise BarrierBenchError(f"sum binder must be {expected_binder!r}")
    if not isinstance(extent_node, ast.Name) or extent_node.id != expected_extent:
        raise BarrierBenchError(f"sum extent must be {expected_extent!r}")

    rewriter = _IndexedBodyRewriter(expected_binder, state_families)
    try:
        rewritten = rewriter.visit(body_node)
        ast.fix_missing_locations(rewritten)
        body = parse_expression(ast.unparse(rewritten))
    except BarrierBenchError:
        raise
    except (TypeError, ValueError) as error:
        raise BarrierBenchError(f"invalid finite-sum body: {error}") from error

    references = tuple(
        IndexedVarRef(family=family, index=expected_binder)
        for family in state_families
        if family in rewriter.references
    )
    try:
        return FamilySumExpr(
            binder=expected_binder,
            extent=expected_extent,
            state_families=state_families,
            body=body,
            indexed_variables=references,
        )
    except ValueError as error:
        raise BarrierBenchError(str(error)) from error


def family_candidate_from_proposal(
    problem: ProblemSpec,
    proposal: CandidateProposalLike,
) -> FamilyCandidateSpec:


    contract = problem.indexed_family
    if contract is None:
        raise BarrierBenchError(
            "family candidates require a typed problem.indexed_family contract"
        )
    if problem.problem_id not in _FAMILY_CASES:
        raise BarrierBenchError(
            "family candidates are supported only for dcb_ext_p1_003, "
            "dcb_ext_p1_004, and dcb_ext_p2_001"
        )
    extent = contract.parameter.name
    state_families = tuple(family.name for family in contract.state_families)
    try:
        symbolic_certificate = parse_family_sum(
            proposal.certificate,
            expected_extent=extent,
            state_families=state_families,
        )
    except BarrierBenchError as error:
        raise BarrierBenchError(f"certificate: {error}") from error

    shared_controller: Expr | None
    if contract.shared_controller is None:
        if proposal.controllers:
            raise BarrierBenchError("this indexed family does not accept controller proposals")
        shared_controller = None
    else:
        controller_contract = contract.shared_controller
        if (
            len(proposal.controllers) != 1
            or proposal.controllers[0].variable != controller_contract.name
        ):
            raise BarrierBenchError(
                "controlled indexed family requires exactly one shared controller "
                f"named {controller_contract.name!r}"
            )
        controller = proposal.controllers[0]
        try:
            shared_expression = parse_expression(controller.expression)
        except BarrierBenchError as error:
            raise BarrierBenchError(f"controller kappa: {error}") from error
        unknown = variables(shared_expression) - {controller_contract.argument}
        if unknown:
            raise BarrierBenchError(
                f"controller {controller_contract.name} may contain only the scalar "
                f"argument {controller_contract.argument}; "
                f"found {', '.join(sorted(unknown))}"
            )
        shared_controller = shared_expression

    return FamilyCandidateSpec(
        problem_id=problem.problem_id,
        family_contract_hash=content_hash(contract),
        certificate_family_ast=symbolic_certificate,
        shared_controller_ast=shared_controller,
        construction_summary=proposal.construction_summary,
        assumptions=proposal.assumptions,
        level_c=_proposal_constant_expr(getattr(proposal, "level_c", None), "level_c"),
        exp_c1=_proposal_rational(getattr(proposal, "exp_c1", None), "exp_c1"),
        exp_c2=_proposal_rational(getattr(proposal, "exp_c2", None), "exp_c2"),
        exp_c3=_proposal_rational(getattr(proposal, "exp_c3", None), "exp_c3"),
    )


def family_candidate_prompt_view(
    problem: ProblemSpec,
    candidate: FamilyCandidateSpec,
) -> dict[str, object]:


    if candidate.problem_id != problem.problem_id:
        raise BarrierBenchError("family candidate/problem id mismatch")
    from .s05_prompts import expr_to_python

    family = candidate.certificate_family_ast
    body = expr_to_python(family.body)
    for reference in family.indexed_variables:
        body = re.sub(
            rf"\b{re.escape(reference.placeholder)}\b",
            f"{reference.family}({family.binder})",
            body,
        )
    view: dict[str, object] = {
        "certificate": f"sum({family.binder}, {family.extent}, {body})",
        "controllers": (
            []
            if candidate.shared_controller_ast is None
            else [
                {
                    "variable": "kappa",
                    "expression": expr_to_python(candidate.shared_controller_ast),
                }
            ]
        ),
        "construction_summary": candidate.construction_summary,
        "assumptions": list(candidate.assumptions),
    }
    contract = problem.indexed_family
    if contract is None or candidate.family_contract_hash != content_hash(contract):
        raise BarrierBenchError("family candidate/contract hash mismatch")
    if contract.target.kind == "roa_sublevel":
        view["level_c"] = (
            None if candidate.level_c is None else expr_to_python(candidate.level_c)
        )
    else:
        for field in ("exp_c1", "exp_c2", "exp_c3"):
            value = getattr(candidate, field)
            view[field] = (
                None
                if value is None
                else (
                    str(value.numerator)
                    if value.denominator == 1
                    else f"{value.numerator}/{value.denominator}"
                )
            )
    return view
