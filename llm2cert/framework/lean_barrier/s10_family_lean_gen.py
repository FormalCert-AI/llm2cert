"""Generate Lean statements for dimension-indexed families."""
from __future__ import annotations

from dataclasses import dataclass

from .s01_models import Expr, IndexedFamilySpec, ProblemSpec, VarExpr
from .s02_expressions import content_hash, differentiate, substitute, variables
from .s03_family_expression import FamilyCandidateSpec
from .s10_lean_gen import LockedTheorem, expr_to_lean

_X = "__family_indexed_x"
_Y = "__family_indexed_y"
_U = "__family_controller_output"
_SCALARS = frozenset({_X, _Y})


@dataclass(frozen=True)
class FamilyLockedTheoremBundle:


    obligations: LockedTheorem
    final: LockedTheorem
    closing_proof_body: str
    closing_theorem_name: str


    @property
    def candidate_hash(self) -> str:
        return self.obligations.candidate_hash

    @property
    def theorem_name(self) -> str:
        return self.obligations.theorem_name

    @property
    def definitions(self) -> str:
        return self.obligations.definitions

    @property
    def statement(self) -> str:
        return self.obligations.statement

    @property
    def definition_check_name(self) -> str | None:
        return self.obligations.definition_check_name

    @property
    def statement_hash(self) -> str:
        return self.obligations.statement_hash


def _scalar_expr(expr: Expr, *, names: frozenset[str] = _SCALARS) -> str:
    return expr_to_lean(expr, {}, scalar_names=names)


def _paired_term(body: str, *, state: str = "z", index: str = "i") -> str:
    return (
        f"(let {_X} : ℝ := {state} (Fin.castAdd m {index}); "
        f"let {_Y} : ℝ := {state} (Fin.natAdd m {index}); {body})"
    )


def _contract_expr(expr: Expr, replacements: dict[str, str]) -> str:


    unknown = variables(expr) - set(replacements)
    if unknown:
        raise ValueError(f"unbound indexed-family dynamics symbols: {sorted(unknown)}")
    rewritten = substitute(
        expr,
        {name: VarExpr(name=placeholder) for name, placeholder in replacements.items()},
    )
    return _scalar_expr(rewritten, names=frozenset(replacements.values()))


def _paired_flow_bodies(contract: IndexedFamilySpec) -> tuple[str, str]:
    equations = {equation.state_family: equation.rhs for equation in contract.block_dynamics}
    return (
        _contract_expr(equations["x"], {"x": _X, "y": _Y}),
        _contract_expr(equations["y"], {"x": _X, "y": _Y}),
    )


def _rational_lean(numerator: int, denominator: int) -> str:
    if denominator == 1:
        return f"({numerator} : ℝ)"
    return f"(({numerator} : ℝ) / ({denominator} : ℝ))"


def _gas_family_locked(
    contract: IndexedFamilySpec,
    candidate: FamilyCandidateSpec,
    suffix: str,
) -> FamilyLockedTheoremBundle:
    body_ast = candidate.certificate_family_ast.body
    body = _scalar_expr(body_ast)
    dx = _scalar_expr(differentiate(body_ast, _X))
    dy = _scalar_expr(differentiate(body_ast, _Y))
    flow_x, flow_y = _paired_flow_bodies(contract)

    certificate = f"familyCertificate_{suffix}"
    certificate_unfold = f"familyCertificate_unfold_{suffix}"
    gradient = f"familyGradient_{suffix}"
    flow = f"familyFlow_{suffix}"
    obligations_claim = f"familyObligationsClaim_{suffix}"
    obligations_theorem = f"verify_parameterized_family_obligations_{suffix}"
    final_theorem = f"verify_parameterized_family_{suffix}"
    term = _paired_term(body)

    definitions = "\n".join(
        (
            f"-- family-candidate-sha256: {content_hash(candidate)}",
            f"-- family-contract-sha256: {content_hash(contract)}",
            "-- R^(2m) is represented without fixing m as State (m + m).",
            f"noncomputable def {certificate} (m : ℕ) "
            f"(z : LeanBarrier.State (m + m)) : ℝ :=\n  ∑ i : Fin m, {term}",
            f"@[simp] theorem {certificate_unfold} (m : ℕ) "
            f"(z : LeanBarrier.State (m + m)) :\n    {certificate} m z = "
            f"∑ i : Fin m, {term} := by\n  rfl",
            f"noncomputable def {gradient} (m : ℕ) "
            f"(z : LeanBarrier.State (m + m)) : LeanBarrier.State (m + m) :=\n"
            f"  Fin.append (fun i : Fin m => {_paired_term(dx)}) "
            f"(fun i : Fin m => {_paired_term(dy)})",
            f"noncomputable def {flow} (m : ℕ) "
            f"(z : LeanBarrier.State (m + m)) : LeanBarrier.State (m + m) :=\n"
            f"  Fin.append (fun i : Fin m => {_paired_term(flow_x)}) "
            f"(fun i : Fin m => {_paired_term(flow_y)})",
        )
    )
    lie = (
        f"(fun z : LeanBarrier.State (m + m) => "
        f"∑ j : Fin (m + m), {gradient} m z j * {flow} m z j)"
    )
    obligations_proposition = (
        f"∀ m : ℕ, 0 < m →\n"
        f"    LeanBarrier.IsGradient ({certificate} m) ({gradient} m) ∧\n"
        f"    Continuous {lie} ∧\n"
        f"    {certificate} m 0 = 0 ∧\n"
        f"    (∀ z : LeanBarrier.State (m + m), z ≠ 0 → "
        f"0 < {certificate} m z) ∧\n"
        f"    {flow} m 0 = 0 ∧\n"
        f"    (∀ z : LeanBarrier.State (m + m), z ≠ 0 → "
        f"(∑ j : Fin (m + m), {gradient} m z j * {flow} m z j) < 0) ∧\n"
        f"    LeanBarrier.Lyapunov.RadiallyUnbounded ({certificate} m)"
    )
    final_proposition = (
        f"∀ m : ℕ, 0 < m →\n"
        f"    LeanBarrier.Lyapunov.ContinuousGloballyAsymptoticallyStable "
        f"({flow} m)"
    )
    obligations_definitions = (
        definitions
        + f"\ndef {obligations_claim} : Prop :=\n  {obligations_proposition}"
    )
    obligations = LockedTheorem(
        candidate_hash=content_hash(candidate),
        theorem_name=obligations_theorem,
        definitions=obligations_definitions,
        statement=f"theorem {obligations_theorem} : {obligations_proposition}",
        definition_check_name=certificate_unfold,
    )
    final = LockedTheorem(
        candidate_hash=content_hash(candidate),
        theorem_name=final_theorem,
        definitions=definitions,
        statement=f"theorem {final_theorem} : {final_proposition}",
        definition_check_name=certificate_unfold,
    )
    closing_theorem_name = (
        "LeanBarrier.Lyapunov."
        "continuous_lyapunov_implies_global_asymptotic_stability"
    )
    closing_proof_body = (
        "by\n"
        "  intro m hm\n"
        f"  rcases {obligations_theorem} m hm with "
        "⟨hgradient, hlieContinuous, hVzero, hpositive, hflowZero, "
        "hlieNegative, hradial⟩\n"
        f"  exact {closing_theorem_name} "
        f"({certificate} m) ({gradient} m) ({flow} m) "
        "hgradient hlieContinuous hVzero hpositive hflowZero "
        "hlieNegative hradial"
    )
    return FamilyLockedTheoremBundle(
        obligations=obligations,
        final=final,
        closing_proof_body=closing_proof_body,
        closing_theorem_name=closing_theorem_name,
    )


def _roa_family_locked(
    contract: IndexedFamilySpec,
    candidate: FamilyCandidateSpec,
    suffix: str,
) -> FamilyLockedTheoremBundle:
    if candidate.shared_controller_ast is None:
        raise ValueError("System 86 requires a shared controller kappa(s)")
    if candidate.level_c is None:
        raise ValueError("System 86 requires an exact level_c")

    body_ast = candidate.certificate_family_ast.body
    body = _scalar_expr(body_ast, names=frozenset({_X}))
    dx = _scalar_expr(differentiate(body_ast, _X), names=frozenset({_X}))
    kappa_body = _scalar_expr(candidate.shared_controller_ast, names=frozenset({"s"}))
    level_body = _scalar_expr(candidate.level_c, names=frozenset())

    certificate = f"familyCertificate_{suffix}"
    certificate_unfold = f"familyCertificate_unfold_{suffix}"
    gradient = f"familyGradient_{suffix}"
    kappa = f"familyKappa_{suffix}"
    flow = f"familyFlow_{suffix}"
    level = f"familyLevel_{suffix}"
    domain = f"familyDomain_{suffix}"
    omega = f"familyOmega_{suffix}"
    obligations_claim = f"familyObligationsClaim_{suffix}"
    obligations_theorem = f"verify_parameterized_family_obligations_{suffix}"
    final_theorem = f"verify_parameterized_family_{suffix}"
    indexed_term = f"(let {_X} : ℝ := z i; {body})"
    equation = contract.block_dynamics[0]
    controller_contract = contract.shared_controller
    if controller_contract is None:
        raise ValueError("ROA family contract requires a shared controller")
    flow_body = _contract_expr(
        equation.rhs,
        {
            controller_contract.input_family: _X,
            controller_contract.output_symbol: _U,
        },
    ).replace(_U, f"{kappa} (z i)")
    if contract.domain.lower is None or contract.domain.upper is None:
        raise ValueError("ROA family contract requires exact coordinate bounds")
    domain_lower = _rational_lean(
        contract.domain.lower.numerator, contract.domain.lower.denominator
    )
    domain_upper = _rational_lean(
        contract.domain.upper.numerator, contract.domain.upper.denominator
    )

    definitions = "\n".join(
        (
            f"-- family-candidate-sha256: {content_hash(candidate)}",
            f"-- family-contract-sha256: {content_hash(contract)}",
            f"noncomputable def {kappa} (s : ℝ) : ℝ := {kappa_body}",
            f"noncomputable def {level} : ℝ := {level_body}",
            f"noncomputable def {certificate} (n : ℕ) "
            f"(z : LeanBarrier.State n) : ℝ :=\n  ∑ i : Fin n, {indexed_term}",
            f"@[simp] theorem {certificate_unfold} (n : ℕ) "
            f"(z : LeanBarrier.State n) :\n    {certificate} n z = "
            f"∑ i : Fin n, {indexed_term} := by\n  rfl",
            f"noncomputable def {gradient} (n : ℕ) "
            f"(z : LeanBarrier.State n) : LeanBarrier.State n :=\n"
            f"  fun i => (let {_X} : ℝ := z i; {dx})",
            f"noncomputable def {flow} (n : ℕ) "
            f"(z : LeanBarrier.State n) : LeanBarrier.State n :=\n"
            f"  fun i => (let {_X} : ℝ := z i; {flow_body})",
            f"def {domain} (n : ℕ) : Set (LeanBarrier.State n) :=\n"
            f"  {{z | ∀ i : Fin n, {domain_lower} ≤ z i ∧ z i ≤ {domain_upper}}}",
            f"def {omega} (n : ℕ) : Set (LeanBarrier.State n) :=\n"
            f"  {{z | {certificate} n z ≤ {level}}}",
        )
    )
    lie = (
        f"(fun z : LeanBarrier.State n => "
        f"∑ j : Fin n, {gradient} n z j * {flow} n z j)"
    )
    obligations_proposition = (
        f"∀ n : ℕ, 0 < n →\n"
        f"    0 < {level} ∧\n"
        f"    {kappa} 0 = 0 ∧\n"
        f"    LeanBarrier.IsGradient ({certificate} n) ({gradient} n) ∧\n"
        f"    Continuous {lie} ∧\n"
        f"    {certificate} n 0 = 0 ∧\n"
        f"    (∀ z : LeanBarrier.State n, z ∈ {omega} n → z ≠ 0 → "
        f"0 < {certificate} n z) ∧\n"
        f"    {flow} n 0 = 0 ∧\n"
        f"    (∀ z : LeanBarrier.State n, z ∈ {omega} n → z ≠ 0 → "
        f"(∑ j : Fin n, {gradient} n z j * {flow} n z j) < 0) ∧\n"
        f"    (∀ z : LeanBarrier.State n, z ∈ {omega} n → z ∈ {domain} n)"
    )
    final_proposition = (
        f"∀ n : ℕ, 0 < n →\n"
        f"    LeanBarrier.Lyapunov.ContinuousROAOn ({omega} n) ({omega} n) "
        f"(LeanBarrier.ClassicalTrajectories ({flow} n))"
    )
    obligations_definitions = (
        definitions
        + f"\ndef {obligations_claim} : Prop :=\n  {obligations_proposition}"
    )
    obligations = LockedTheorem(
        candidate_hash=content_hash(candidate),
        theorem_name=obligations_theorem,
        definitions=obligations_definitions,
        statement=f"theorem {obligations_theorem} : {obligations_proposition}",
        definition_check_name=certificate_unfold,
    )
    final = LockedTheorem(
        candidate_hash=content_hash(candidate),
        theorem_name=final_theorem,
        definitions=definitions,
        statement=f"theorem {final_theorem} : {final_proposition}",
        definition_check_name=certificate_unfold,
    )
    closing_theorem_name = (
        "LeanBarrier.Lyapunov."
        "continuous_lyapunov_sublevel_is_roa_of_subset_coordinateBox"
    )
    closing_proof_body = (
        "by\n"
        "  intro n hn\n"
        f"  rcases {obligations_theorem} n hn with "
        "⟨hc, _hkappaZero, hgradient, hlieContinuous, hVzero, hpositive, "
        "hflowZero, hlieNegative, hsubset⟩\n"
        f"  exact {closing_theorem_name} "
        f"({certificate} n) ({gradient} n) ({flow} n) {level} "
        f"{domain_lower} {domain_upper} hc hgradient hlieContinuous hVzero "
        "hpositive hflowZero hlieNegative hsubset"
    )
    return FamilyLockedTheoremBundle(
        obligations=obligations,
        final=final,
        closing_proof_body=closing_proof_body,
        closing_theorem_name=closing_theorem_name,
    )


def generate_family_locked_theorem(
    problem: ProblemSpec,
    candidate: FamilyCandidateSpec,
) -> FamilyLockedTheoremBundle:


    if problem.problem_id != candidate.problem_id:
        raise ValueError("family candidate does not belong to this problem")
    contract = problem.indexed_family
    if contract is None:
        raise ValueError("indexed-family theorem requires problem.indexed_family")
    if contract.time_domain != "continuous":
        raise ValueError("only continuous indexed families are supported")
    contract_hash = content_hash(contract)
    if candidate.family_contract_hash != contract_hash:
        raise ValueError("family candidate/contract hash mismatch")
    family = candidate.certificate_family_ast
    expected_families = tuple(item.name for item in contract.state_families)
    if family.extent != contract.parameter.name or family.state_families != expected_families:
        raise ValueError("family candidate syntax does not match indexed-family contract")
    if (candidate.shared_controller_ast is None) != (contract.shared_controller is None):
        raise ValueError("family candidate controller does not match indexed-family contract")
    digest = content_hash(candidate)
    suffix = digest[:12]
    if contract.target.kind == "global_asymptotic_stability":
        if contract.state_dimension != "2m":
            raise ValueError("global asymptotic family requires the supported 2m layout")
        return _gas_family_locked(contract, candidate, suffix)
    if contract.target.kind == "roa_sublevel":
        if contract.state_dimension != "n":
            raise ValueError("ROA family requires the supported n layout")
        return _roa_family_locked(contract, candidate, suffix)
    raise ValueError(f"unsupported indexed-family target: {contract.target.kind}")


__all__ = ["FamilyLockedTheoremBundle", "generate_family_locked_theorem"]
