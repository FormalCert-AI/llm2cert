"""Define typed contracts for problems, candidates, and verification results."""
from __future__ import annotations

from enum import StrEnum
from math import gcd
from typing import Annotated, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
ExpressionSource = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=20000),
]


class StrictModel(BaseModel):


    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        strict=True,
    )


class Rational(StrictModel):


    numerator: int
    denominator: int = 1

    @model_validator(mode="after")
    def canonical(self) -> Rational:
        if self.denominator <= 0:
            raise ValueError("denominator must be positive")
        if gcd(abs(self.numerator), self.denominator) != 1:
            raise ValueError("rational must be reduced")
        if self.numerator == 0 and self.denominator != 1:
            raise ValueError("zero must be encoded as 0/1")
        return self


class ConstExpr(StrictModel):
    kind: Literal["const"] = "const"
    value: Rational


class PiExpr(StrictModel):


    kind: Literal["pi"] = "pi"


class VarExpr(StrictModel):
    kind: Literal["var"] = "var"
    name: Identifier


class AddExpr(StrictModel):
    kind: Literal["add"] = "add"
    args: tuple[Expr, ...]

    @field_validator("args")
    @classmethod
    def at_least_two(cls, value: tuple[Expr, ...]) -> tuple[Expr, ...]:
        if len(value) < 2:
            raise ValueError("add requires at least two arguments")
        return value


class SubExpr(StrictModel):
    kind: Literal["sub"] = "sub"
    left: Expr
    right: Expr


class MulExpr(StrictModel):
    kind: Literal["mul"] = "mul"
    args: tuple[Expr, ...]

    @field_validator("args")
    @classmethod
    def at_least_two(cls, value: tuple[Expr, ...]) -> tuple[Expr, ...]:
        if len(value) < 2:
            raise ValueError("mul requires at least two arguments")
        return value


class NegExpr(StrictModel):
    kind: Literal["neg"] = "neg"
    arg: Expr


class PowExpr(StrictModel):
    kind: Literal["pow"] = "pow"
    base: Expr
    exponent: int = Field(ge=0)


class SinExpr(StrictModel):
    kind: Literal["sin"] = "sin"
    arg: Expr


class CosExpr(StrictModel):
    kind: Literal["cos"] = "cos"
    arg: Expr


class ExpExpr(StrictModel):
    kind: Literal["exp"] = "exp"
    arg: Expr


class TanhExpr(StrictModel):
    kind: Literal["tanh"] = "tanh"
    arg: Expr


class LogExpr(StrictModel):
    kind: Literal["log"] = "log"
    arg: Expr


class SqrtExpr(StrictModel):
    kind: Literal["sqrt"] = "sqrt"
    arg: Expr


class AtanExpr(StrictModel):
    kind: Literal["atan"] = "atan"
    arg: Expr


class DivExpr(StrictModel):
    kind: Literal["div"] = "div"
    left: Expr
    right: Expr


type Expr = Annotated[
    ConstExpr
    | PiExpr
    | VarExpr
    | AddExpr
    | SubExpr
    | MulExpr
    | DivExpr
    | NegExpr
    | PowExpr
    | SinExpr
    | CosExpr
    | ExpExpr
    | TanhExpr
    | LogExpr
    | SqrtExpr
    | AtanExpr,
    Field(discriminator="kind"),
]
EXPR_ADAPTER = TypeAdapter(Expr)


class Relation(StrEnum):
    LT = "lt"
    LE = "le"
    EQ = "eq"
    GE = "ge"
    GT = "gt"


class Constraint(StrictModel):
    lhs: Expr
    relation: Relation
    rhs: Expr


class ConstraintGroup(StrictModel):


    constraints: tuple[Constraint, ...]


class BoxSpec(StrictModel):


    lower: dict[Identifier, Rational]
    upper: dict[Identifier, Rational]

    @model_validator(mode="after")
    def matching_finite_bounds(self) -> BoxSpec:
        if set(self.lower) != set(self.upper):
            raise ValueError("lower and upper bounds must name the same variables")
        for name in self.lower:
            lo = self.lower[name]
            hi = self.upper[name]
            if lo.numerator * hi.denominator >= hi.numerator * lo.denominator:
                raise ValueError(f"lower bound must be smaller than upper bound for {name}")
        return self


class RegionSpec(StrictModel):


    constraints: tuple[Constraint, ...] = ()
    any_of: tuple[ConstraintGroup, ...] = ()
    bounds: BoxSpec | None = None


class DynamicsKind(StrEnum):
    CONTINUOUS = "continuous"
    DISCRETE = "discrete"


class TaskType(StrEnum):
    SAFETY = "safety"
    INVARIANT = "invariant"
    STABILITY = "stability"
    ROA = "roa"


class StabilityKind(StrEnum):
    LOCAL_LYAPUNOV = "local_lyapunov"
    LOCAL_ASYMPTOTIC = "local_asymptotic"
    LOCAL_EXPONENTIAL = "local_exponential"
    GLOBAL_ASYMPTOTIC = "global_asymptotic"
    GLOBAL_EXPONENTIAL = "global_exponential"


class OriginPolicy(StrEnum):
    EXCLUDE_POINT = "exclude_point"
    EXCLUDE_BALL = "exclude_ball"
    INCLUDE_ORIGIN = "include_origin"


class SafetyInterpretation(StrEnum):
    CONDITIONAL_IN_X = "conditional_in_X"
    OUTSIDE_X_IS_UNSAFE = "outside_X_is_unsafe"
    SEPARATE_SAFE_UNSAFE = "separate_safe_unsafe"


class NeighborhoodSpec(StrictModel):


    unbounded: bool = False
    region: RegionSpec | None = None

    @model_validator(mode="after")
    def coherent_neighborhood(self) -> NeighborhoodSpec:
        if self.unbounded and self.region is not None:
            raise ValueError("unbounded neighborhood must not include a finite region")
        if not self.unbounded and self.region is None:
            raise ValueError("bounded neighborhood requires a region")
        return self


class SourceDomainSpec(StrictModel):


    description: str = ""
    shape: str | None = None
    inner_radius: Rational | None = None
    outer_radius: Rational | None = None


class FixedParameterSpec(StrictModel):


    name: Identifier
    lower: Rational
    upper: Rational
    time_semantics: Literal["fixed"] = "fixed"
    quantifier: Literal["forall"] = "forall"

    @model_validator(mode="after")
    def ordered_bounds(self) -> FixedParameterSpec:
        if (
            self.lower.numerator * self.upper.denominator
            >= self.upper.numerator * self.lower.denominator
        ):
            raise ValueError("fixed parameter lower bound must be smaller than upper bound")
        return self


class IndexedFamilyParameterSpec(StrictModel):


    name: Literal["m", "n"]
    domain: Literal["positive_natural"] = "positive_natural"


class IndexedStateFamilySpec(StrictModel):


    name: Literal["x", "y"]


class IndexedBlockDynamicsSpec(StrictModel):


    state_family: Literal["x", "y"]
    rhs: Expr


class IndexedSharedControllerSpec(StrictModel):


    name: Literal["kappa"] = "kappa"
    argument: Literal["s"] = "s"
    input_family: Literal["x"] = "x"
    output_symbol: Literal["u"] = "u"
    observation: Literal["own_coordinate"] = "own_coordinate"
    shared_across_indices: Literal[True] = True
    zero_at_origin: Literal[True] = True


class IndexedFamilyDomainSpec(StrictModel):


    kind: Literal["unbounded", "coordinate_box"]
    lower: Rational | None = None
    upper: Rational | None = None

    @model_validator(mode="after")
    def coherent_domain(self) -> IndexedFamilyDomainSpec:
        if self.kind == "unbounded":
            if self.lower is not None or self.upper is not None:
                raise ValueError("unbounded indexed-family domain must not have bounds")
            return self
        if self.lower is None or self.upper is None:
            raise ValueError("coordinate_box indexed-family domain requires lower and upper")
        if (
            self.lower.numerator * self.upper.denominator
            >= self.upper.numerator * self.lower.denominator
        ):
            raise ValueError("indexed-family domain lower bound must be smaller than upper")
        return self


class IndexedFamilyTargetSpec(StrictModel):


    kind: Literal["global_asymptotic_stability", "roa_sublevel"]
    stability_kind: StabilityKind

    @model_validator(mode="after")
    def coherent_target(self) -> IndexedFamilyTargetSpec:
        expected = (
            StabilityKind.GLOBAL_ASYMPTOTIC
            if self.kind == "global_asymptotic_stability"
            else StabilityKind.LOCAL_ASYMPTOTIC
        )
        if self.stability_kind != expected:
            raise ValueError(
                f"indexed-family target {self.kind} requires stability_kind={expected.value}"
            )
        return self


class IndexedFamilySpec(StrictModel):


    schema_version: Literal["lean-barrier.indexed-family.v1"] = (
        "lean-barrier.indexed-family.v1"
    )
    time_domain: Literal["continuous"] = "continuous"
    parameter: IndexedFamilyParameterSpec
    state_dimension: Literal["2m", "n"]
    binder: Literal["i"] = "i"
    state_families: tuple[IndexedStateFamilySpec, ...]
    block_dynamics: tuple[IndexedBlockDynamicsSpec, ...]
    shared_controller: IndexedSharedControllerSpec | None = None
    equilibrium: Literal["zero"] = "zero"
    domain: IndexedFamilyDomainSpec
    target: IndexedFamilyTargetSpec

    @model_validator(mode="after")
    def closed_supported_family(self) -> IndexedFamilySpec:
        from .s02_expressions import variables

        family_names = tuple(family.name for family in self.state_families)
        if len(set(family_names)) != len(family_names):
            raise ValueError("indexed state-family names must be unique")
        expected_layout = (
            ("m", ("x", "y")) if self.state_dimension == "2m" else ("n", ("x",))
        )
        if (self.parameter.name, family_names) != expected_layout:
            raise ValueError(
                f"state_dimension={self.state_dimension} requires parameter/families "
                f"{expected_layout}"
            )

        equation_names = tuple(equation.state_family for equation in self.block_dynamics)
        if equation_names != family_names:
            raise ValueError(
                "block_dynamics must contain exactly one equation per state family, "
                "in state_families order"
            )
        controller_symbol = (
            None if self.shared_controller is None else self.shared_controller.output_symbol
        )
        allowed = set(family_names)
        if controller_symbol is not None:
            allowed.add(controller_symbol)
        for equation in self.block_dynamics:
            unknown = variables(equation.rhs) - allowed
            if unknown:
                raise ValueError(
                    f"block dynamics for {equation.state_family} contains unknown local "
                    f"symbols: {sorted(unknown)}"
                )

        used_symbols = set().union(
            *(variables(equation.rhs) for equation in self.block_dynamics)
        )
        if self.shared_controller is None:
            if "u" in used_symbols:
                raise ValueError("uncontrolled indexed family cannot use controller output u")
        else:
            if self.state_dimension != "n" or family_names != ("x",):
                raise ValueError("shared controller is supported only for the n-dimensional x family")
            if self.shared_controller.input_family not in family_names:
                raise ValueError("shared controller input_family is not a declared state family")
            if self.shared_controller.output_symbol not in used_symbols:
                raise ValueError("shared controller output symbol must occur in block_dynamics")

        if self.target.kind == "global_asymptotic_stability":
            if self.domain.kind != "unbounded":
                raise ValueError("global asymptotic family target requires an unbounded domain")
            if self.shared_controller is not None:
                raise ValueError("current global asymptotic families are uncontrolled")
        else:
            if self.domain.kind != "coordinate_box":
                raise ValueError("ROA family target requires a coordinate_box domain")
            if self.shared_controller is None:
                raise ValueError("current ROA family requires one shared controller")
        return self


class SystemSpec(StrictModel):
    kind: DynamicsKind
    state_vars: tuple[Identifier, ...]
    control_vars: tuple[Identifier, ...] = ()


    control_observations: dict[Identifier, tuple[Identifier, ...]] | None = None
    dynamics: tuple[Expr, ...]
    declared_smooth: bool = False
    regularity_lemma: Identifier | None = None

    @model_validator(mode="after")
    def dimensions_match(self) -> SystemSpec:
        if not self.state_vars:
            raise ValueError("at least one state variable is required")
        if len(set(self.state_vars)) != len(self.state_vars):
            raise ValueError("state variables must be unique")
        if len(set(self.control_vars)) != len(self.control_vars):
            raise ValueError("control variables must be unique")
        if set(self.state_vars) & set(self.control_vars):
            raise ValueError("state and control variables must be disjoint")
        if len(self.dynamics) != len(self.state_vars):
            raise ValueError("one dynamics expression is required per state variable")
        if self.control_observations is not None:
            controls = set(self.control_vars)
            if set(self.control_observations) != controls:
                raise ValueError(
                    "control_observations must name exactly the control variables"
                )
            states = set(self.state_vars)
            for control, observed in self.control_observations.items():
                if len(set(observed)) != len(observed):
                    raise ValueError(
                        f"control_observations[{control}] must not contain duplicates"
                    )
                unknown = set(observed) - states
                if unknown:
                    raise ValueError(
                        f"control_observations[{control}] contains unknown states: "
                        f"{sorted(unknown)}"
                    )
        return self


class ProblemSpec(StrictModel):
    schema_version: Literal["lean-barrier.problem.v1"] = "lean-barrier.problem.v1"
    problem_id: Identifier
    name: str


    system: SystemSpec | None = None
    indexed_family: IndexedFamilySpec | None = None
    fixed_parameters: tuple[FixedParameterSpec, ...] = ()
    unsafe_set: RegionSpec | None = None
    initial_set: RegionSpec | None = None


    analysis_box: BoxSpec | None = None
    formal_domain_unbounded: bool = False
    control_set: BoxSpec | None = None
    task_type: TaskType = TaskType.SAFETY
    equilibrium: tuple[Rational, ...] | None = None
    neighborhood: NeighborhoodSpec | None = None
    stability_kind: StabilityKind | None = None
    source_domain: SourceDomainSpec | None = None
    origin_policy: OriginPolicy = OriginPolicy.EXCLUDE_POINT
    safety_interpretation: SafetyInterpretation = SafetyInterpretation.CONDITIONAL_IN_X
    source: str | None = None
    assumptions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def analysis_variables_match(self) -> ProblemSpec:
        if self.indexed_family is not None:
            supported_family_ids = {
                "dcb_ext_p1_003",
                "dcb_ext_p1_004",
                "dcb_ext_p2_001",
            }
            if self.problem_id not in supported_family_ids:
                raise ValueError(
                    "indexed_family is supported only for Systems 82, 84, and 86"
                )
            if self.system is not None or self.analysis_box is not None:
                raise ValueError(
                    "indexed-family problems must not carry a frozen system or analysis_box"
                )
            if self.fixed_parameters:
                raise ValueError("indexed-family problems do not support fixed_parameters")
            if any(
                value is not None
                for value in (
                    self.unsafe_set,
                    self.initial_set,
                    self.control_set,
                    self.equilibrium,
                    self.neighborhood,
                    self.stability_kind,
                )
            ):
                raise ValueError(
                    "indexed-family domain, equilibrium, and target must live only in "
                    "indexed_family"
                )
            expected_task = (
                TaskType.STABILITY
                if self.indexed_family.target.kind == "global_asymptotic_stability"
                else TaskType.ROA
            )
            if self.task_type != expected_task:
                raise ValueError(
                    f"indexed-family target requires task_type={expected_task.value}"
                )
            expected_shape = (
                ("n", "roa_sublevel")
                if self.problem_id == "dcb_ext_p2_001"
                else ("2m", "global_asymptotic_stability")
            )
            actual_shape = (
                self.indexed_family.state_dimension,
                self.indexed_family.target.kind,
            )
            if actual_shape != expected_shape:
                raise ValueError(
                    f"{self.problem_id} requires indexed-family shape {expected_shape}"
                )
            return self
        if self.system is None:
            raise ValueError("ordinary problems require system")
        if self.analysis_box is None:
            raise ValueError("ordinary problems require analysis_box")
        expected = set(self.system.state_vars)
        parameter_names = [parameter.name for parameter in self.fixed_parameters]
        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("fixed parameter names must be unique")
        conflicts = set(parameter_names) & (
            set(self.system.state_vars) | set(self.system.control_vars)
        )
        if conflicts:
            raise ValueError(
                "fixed parameters must be disjoint from state and control variables: "
                f"{sorted(conflicts)}"
            )
        if self.fixed_parameters and (
            self.system.kind != DynamicsKind.CONTINUOUS
            or self.task_type != TaskType.SAFETY
        ):
            raise ValueError(
                "fixed parameters are currently supported only for continuous safety problems"
            )
        if set(self.analysis_box.lower) != expected:
            raise ValueError("analysis_box must bound exactly the state variables")
        if self.equilibrium is not None and len(self.equilibrium) != len(self.system.state_vars):
            raise ValueError("equilibrium must match the state dimension")
        if self.control_set is not None:
            names = set(self.system.control_vars)
            if not names:
                raise ValueError("control_set requires control variables")
            if set(self.control_set.lower) != names:
                raise ValueError("control_set must bound exactly the control variables")
        return self


class ControllerAssignment(StrictModel):
    variable: Identifier
    expression: Expr


class ControllerAST(StrictModel):
    assignments: tuple[ControllerAssignment, ...] = ()


class ControllerProposal(StrictModel):


    variable: Identifier
    expression: ExpressionSource


class _CandidateProposalBase(StrictModel):


    certificate: ExpressionSource
    controllers: tuple[ControllerProposal, ...] = ()
    construction_summary: str = Field(min_length=1, max_length=2000)
    assumptions: tuple[str, ...] = ()


class CandidateProposal(_CandidateProposalBase):


    level_c: ExpressionSource | None = None
    exp_c1: ExpressionSource | None = None
    exp_c2: ExpressionSource | None = None
    exp_c3: ExpressionSource | None = None


class StabilityCandidateProposal(_CandidateProposalBase):


    exp_c1: ExpressionSource | None = None
    exp_c2: ExpressionSource | None = None
    exp_c3: ExpressionSource | None = None


class RoaCandidateProposal(_CandidateProposalBase):


    level_c: ExpressionSource


CandidateProposalLike = CandidateProposal | StabilityCandidateProposal | RoaCandidateProposal


class CandidateSpec(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        strict=True,
        populate_by_name=True,
    )
    schema_version: Literal["lean-barrier.candidate.v1"] = "lean-barrier.candidate.v1"
    certificate_ast: Expr = Field(
        validation_alias=AliasChoices("certificate_ast", "barrier_ast"),
    )
    controller_ast: ControllerAST = ControllerAST()
    construction_summary: str = Field(min_length=1, max_length=2000)
    assumptions: tuple[str, ...] = ()


    level_c: Expr | None = None
    exp_c1: Rational | None = None
    exp_c2: Rational | None = None
    exp_c3: Rational | None = None

    @field_validator("level_c", mode="before")
    @classmethod
    def upgrade_rational_level(cls, value: object) -> object:
        if isinstance(value, Rational):
            return ConstExpr(value=value)
        if isinstance(value, dict) and "kind" not in value:
            if set(value).issubset({"numerator", "denominator"}) and "numerator" in value:
                return {"kind": "const", "value": value}
        return value


class ConditionKind(StrEnum):
    INDEXED_FAMILY = "indexed_family"
    UNSAFE_SEPARATION = "unsafe_separation"
    INITIAL_CONTAINMENT = "initial_containment"
    BARRIER_C1 = "barrier_c1"
    LIE_STRICT = "lie_strict"
    DISCRETE_INDUCTIVE = "discrete_inductive"
    CONTROL_ADMISSIBLE = "control_admissible"
    SAFETY_INSTANTIATION = "safety_instantiation"
    CERTIFIED_SET_IN_X = "certified_set_in_X"
    EQUILIBRIUM_FIXED = "equilibrium_fixed"
    V_AT_EQUILIBRIUM = "v_at_equilibrium"
    POSITIVE_DEFINITE = "positive_definite"
    LIE_NONPOSITIVE = "lie_nonpositive"
    LIE_NEGATIVE = "lie_negative"
    QUADRATIC_LOWER = "quadratic_lower"
    QUADRATIC_UPPER = "quadratic_upper"
    EXPONENTIAL_DECAY = "exponential_decay"
    RADIAL_UNBOUNDED = "radial_unbounded"
    LEVEL_POSITIVE = "level_positive"
    SUBLEVEL_CONTAINS_INITIAL = "sublevel_contains_initial"
    SUBLEVEL_IN_NEIGHBORHOOD = "sublevel_in_neighborhood"
    STABILITY_INSTANTIATION = "stability_instantiation"
    ROA_INSTANTIATION = "roa_instantiation"
    INVARIANT_INSTANTIATION = "invariant_instantiation"


class QuerySpec(StrictModel):


    variables: tuple[Identifier, ...]
    constraints: tuple[Constraint, ...]
    any_of: tuple[ConstraintGroup, ...] = ()
    formal_bounds: BoxSpec | None = None


class Condition(StrictModel):
    schema_version: Literal["lean-barrier.condition.v1"] = "lean-barrier.condition.v1"
    condition_id: str
    kind: ConditionKind
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    description: str
    query: QuerySpec | None = None
    lean_theorem_name: Identifier
    required: bool = True


class VerificationRoute(StrEnum):
    DIRECT_LEAN = "direct_lean"
    SMT = "smt"


class Backend(StrEnum):
    Z3 = "z3"
    CVC5 = "cvc5"
    YICES = "yices"
    DREAL = "dreal"


class VerificationRouterDecision(StrictModel):


    condition_id: str
    route: VerificationRoute
    solver_order: tuple[Backend, ...] = ()
    rationale: str = Field(min_length=1, max_length=1000)


class RoutingDecision(StrictModel):
    schema_version: Literal["lean-barrier.routing.v1"] = "lean-barrier.routing.v1"
    condition_id: str
    route: VerificationRoute
    solver_order: tuple[Backend, ...] = ()
    used_fallback: bool = False
    rationale: str

    @model_validator(mode="after")
    def route_matches_order(self) -> RoutingDecision:
        if self.route == VerificationRoute.DIRECT_LEAN and self.solver_order:
            raise ValueError("direct_lean must not include solvers")
        if len(set(self.solver_order)) != len(self.solver_order):
            raise ValueError("solver_order must not contain duplicates")
        return self


class SolverStatus(StrEnum):
    SAT = "sat"
    UNSAT = "unsat"
    DELTA_SAT = "delta_sat"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    ERROR = "error"


class ReplayStatus(StrEnum):
    CONFIRMED = "confirmed"
    NOT_CONFIRMED = "not_confirmed"
    NOT_APPLICABLE = "not_applicable"


class IntervalValue(StrictModel):
    lower: str
    upper: str


class Witness(StrictModel):
    point: dict[Identifier, str] | None = None
    box: dict[Identifier, IntervalValue] | None = None


class SolverResult(StrictModel):
    schema_version: Literal["lean-barrier.solver-result.v1"] = "lean-barrier.solver-result.v1"
    condition_id: str
    backend: Backend
    expected_version: str
    observed_version: str | None = None
    status: SolverStatus
    duration_seconds: float = Field(ge=0)
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    formal_query: str = ""
    container_image: str | None = None
    witness: Witness | None = None
    replay_status: ReplayStatus = ReplayStatus.NOT_APPLICABLE
    replay_residual: str | None = None
    stdout: str = ""
    stderr: str = ""


class LeanAgentStatus(StrEnum):
    CANDIDATE_PROOF = "candidate_proof"
    CANNOT_COMPLETE = "cannot_complete"


class LeanAgentOutput(StrictModel):
    status: LeanAgentStatus
    helper_lemmas: tuple[str, ...] = ()
    proof_body: str = ""
    blocking_reason: str | None = None


    counterexample: dict[Identifier, str] | None = None

    @model_validator(mode="after")
    def coherent_status(self) -> LeanAgentOutput:
        if self.status == LeanAgentStatus.CANDIDATE_PROOF and not self.proof_body.strip():
            raise ValueError("candidate_proof requires a proof_body")
        if self.status == LeanAgentStatus.CANNOT_COMPLETE and not self.blocking_reason:
            raise ValueError("cannot_complete requires blocking_reason")
        return self


class LeanLocalPatchStatus(StrEnum):
    PATCH = "patch"
    CANNOT_PATCH = "cannot_patch"


class LeanLocalPatch(StrictModel):


    status: LeanLocalPatchStatus
    patch_id: str = Field(min_length=1, max_length=200)
    replacement_code: str = Field(default="", max_length=4000)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def coherent_patch(self) -> LeanLocalPatch:
        if self.status == LeanLocalPatchStatus.PATCH and not self.replacement_code.strip():
            raise ValueError("patch requires replacement_code")
        if self.status == LeanLocalPatchStatus.CANNOT_PATCH and self.replacement_code.strip():
            raise ValueError("cannot_patch must not include replacement_code")
        return self


class LeanAttempt(StrictModel):
    round_index: int = Field(ge=1, le=8)
    agent_status: LeanAgentStatus
    helper_lemmas: tuple[str, ...] = ()
    proof_body: str = ""
    generated_source_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    compiled: bool = False
    diagnostics: str = ""
    printed_axioms: tuple[str, ...] = ()


class LeanResult(StrictModel):
    schema_version: Literal["lean-barrier.lean-result.v1"] = "lean-barrier.lean-result.v1"
    condition_id: str
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    statement_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: LeanAgentStatus
    compiled: bool
    rounds: int = Field(ge=0, le=8)
    proof_rounds: int = Field(default=0, ge=0, le=8)
    name_repair_rounds: int = Field(default=0, ge=0, le=8)
    agent_call_retries: int = Field(default=0, ge=0, le=2)
    duration_seconds: float = Field(ge=0)
    proof_body_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    diagnostics: str = ""
    printed_axioms: tuple[str, ...] = ()
    audit_passed: bool = False
    blocking_reason: str | None = None
    attempts: tuple[LeanAttempt, ...] = ()


class EvidenceLevel(StrEnum):
    INTERVAL_VALIDATED = "interval_validated"
    EXACT_MODEL_REPLAY = "exact_model_replay"
    SOLVER_UNSAT = "solver_unsat"
    LEAN_KERNEL = "lean_kernel"
    HINT_ONLY = "hint_only"


class CounterexampleEvidence(StrictModel):
    condition_id: str
    source: str
    level: EvidenceLevel
    witness: Witness
    residual: str


class CandidateStatus(StrEnum):
    VERIFIED = "verified"
    REJECTED = "rejected"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    UNRESOLVED = "unresolved"
    SEARCH_EXHAUSTED = "search_exhausted"


class CertificationLevel(StrEnum):


    SOLVER_VERIFIED = "solver_verified"
    HYBRID_VERIFIED = "hybrid_verified"
    LEAN_CERTIFIED = "lean_certified"


class VerificationScope(StrEnum):
    OBLIGATIONS_VERIFIED = "obligations_verified"
    PROPERTY_VERIFIED = "property_verified"


class BackendProfile(StrEnum):
    LEAN = "lean"
    SMT = "smt"
    HYBRID = "hybrid"


class ConditionOutcome(StrictModel):
    condition_id: str
    passed: bool
    source: Literal["solver", "lean", "static", "counterexample", "unresolved"]
    detail: str


class CandidateVerdict(StrictModel):
    schema_version: Literal["lean-barrier.verdict.v1"] = "lean-barrier.verdict.v1"
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CandidateStatus
    certification: CertificationLevel | None = None
    scope: VerificationScope | None = None
    backend_profile: BackendProfile | None = None
    outcomes: tuple[ConditionOutcome, ...] = ()
    counterexample: CounterexampleEvidence | None = None
    counterexamples: tuple[CounterexampleEvidence, ...] = ()
    human_report_path: str | None = None

    @model_validator(mode="before")
    @classmethod
    def infer_v1_verification_dimensions(cls, data: object) -> object:


        if not isinstance(data, dict):
            return data
        values = dict(data)
        status = values.get("status")
        if status not in {CandidateStatus.VERIFIED, CandidateStatus.VERIFIED.value}:
            return values
        certification = values.get("certification")
        if certification is None:
            return values
        values.setdefault("scope", VerificationScope.OBLIGATIONS_VERIFIED)
        profile = {
            CertificationLevel.LEAN_CERTIFIED: BackendProfile.LEAN,
            CertificationLevel.LEAN_CERTIFIED.value: BackendProfile.LEAN,
            CertificationLevel.SOLVER_VERIFIED: BackendProfile.SMT,
            CertificationLevel.SOLVER_VERIFIED.value: BackendProfile.SMT,
            CertificationLevel.HYBRID_VERIFIED: BackendProfile.HYBRID,
            CertificationLevel.HYBRID_VERIFIED.value: BackendProfile.HYBRID,
        }.get(certification)
        if profile is not None:
            values.setdefault("backend_profile", profile)
        return values

    @model_validator(mode="after")
    def dimensions_only_when_verified(self) -> CandidateVerdict:
        if self.status == CandidateStatus.VERIFIED and self.certification is None:
            raise ValueError("verified verdict requires a certification level")
        if self.status != CandidateStatus.VERIFIED and self.certification is not None:
            raise ValueError("only verified candidates may have a certification level")
        if self.status == CandidateStatus.VERIFIED:
            if self.scope is None or self.backend_profile is None:
                raise ValueError(
                    "verified verdict requires scope and backend_profile"
                )
        elif self.scope is not None or self.backend_profile is not None:
            raise ValueError(
                "scope and backend_profile are only defined for verified verdicts"
            )
        return self


class CandidateRecord(StrictModel):
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    structure_index: int = Field(ge=0)
    candidate: CandidateSpec


PUBLIC_MODELS: dict[str, type[BaseModel]] = {
    "ProblemSpec": ProblemSpec,
    "CandidateProposal": CandidateProposal,
    "CandidateSpec": CandidateSpec,
    "Condition": Condition,
    "RoutingDecision": RoutingDecision,
    "VerificationRouterDecision": VerificationRouterDecision,
    "SolverResult": SolverResult,
    "LeanResult": LeanResult,
    "CandidateVerdict": CandidateVerdict,
}


for _model in (
    PiExpr,
    AddExpr,
    SubExpr,
    MulExpr,
    NegExpr,
    PowExpr,
    SinExpr,
    CosExpr,
    ExpExpr,
    TanhExpr,
    LogExpr,
    SqrtExpr,
    AtanExpr,
    DivExpr,
    Constraint,
    SystemSpec,
    CandidateSpec,
):
    _model.model_rebuild(_types_namespace={"Expr": Expr})
