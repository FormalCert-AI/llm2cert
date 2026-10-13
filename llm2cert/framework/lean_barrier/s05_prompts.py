"""Construct model prompts for synthesis, routing, and proof repair."""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from .s03_family_expression import FamilyCandidateSpec

from .s06_agents import openai_strict_json_schema
from .s02_expressions import CORE_UNARY_FUNCTIONS, SUGAR_UNARY_FUNCTIONS, canonical_json, const
from .tasks import profile_for
from .s01_models import (
    AddExpr,
    AtanExpr,
    BoxSpec,
    CandidateProposal,
    RoaCandidateProposal,
    CandidateSpec,
    ConstExpr,
    Constraint,
    CosExpr,
    DivExpr,
    DynamicsKind,
    ExpExpr,
    Expr,
    LeanAgentOutput,
    LeanLocalPatch,
    LogExpr,
    MulExpr,
    NegExpr,
    PiExpr,
    Condition,
    PowExpr,
    ProblemSpec,
    RegionSpec,
    Relation,
    SinExpr,
    SqrtExpr,
    StabilityCandidateProposal,
    SubExpr,
    TanhExpr,
    TaskType,
    VarExpr,
    VerificationRouterDecision,
)

_RELATION_TEXT = {
    Relation.LT: "<",
    Relation.LE: "<=",
    Relation.EQ: "==",
    Relation.GE: ">=",
    Relation.GT: ">",
}


def is_indexed_family_problem(problem: ProblemSpec) -> bool:


    return problem.indexed_family is not None


def _indexed_family_parameter(problem: ProblemSpec) -> str:
    contract = problem.indexed_family
    if contract is None:
        raise ValueError("problem has no indexed_family contract")
    return contract.parameter.name


def _indexed_family_syntax(problem: ProblemSpec) -> str:
    contract = problem.indexed_family
    if contract is None:
        raise ValueError("problem has no indexed_family contract")
    parameter = _indexed_family_parameter(problem)
    coordinates = " and ".join(
        f"{family.name}(i)" for family in contract.state_families
    )
    controller = (
        " For the controller, return exactly one controllers entry with variable "
        f"{contract.shared_controller.name} and a scalar expression in the placeholder "
        f"{contract.shared_controller.argument}; do not return separate "
        "coordinate controllers."
        if contract.shared_controller is not None
        else ""
    )
    return (
        f"This task accepts indexed expressions {coordinates} and the binder "
        f"sum(i, {parameter}, body), which denotes the sum for i=1,...,{parameter}. "
        f"The index i is bound only inside body. These are available expression forms, "
        f"not a prescribed certificate structure. Return one symbolic candidate valid "
        f"for every positive {parameter}; do not instantiate {parameter} to a number or "
        f"expand the family into finitely many coordinates.{controller}"
    )


def _schema(model: type[BaseModel]) -> str:
    return json.dumps(openai_strict_json_schema(model), sort_keys=True, separators=(",", ":"))


def _render(sections: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"{name}:\n{body.strip()}" for name, body in sections)


def _rational_text(numerator: int, denominator: int) -> str:
    if denominator == 1:
        return str(numerator)
    if numerator < 0:
        return f"-({abs(numerator)}/{denominator})"
    return f"({numerator}/{denominator})"


def expr_to_python(expr: Expr) -> str:
    if isinstance(expr, ConstExpr):
        return _rational_text(expr.value.numerator, expr.value.denominator)
    if isinstance(expr, PiExpr):
        return "pi"
    if isinstance(expr, VarExpr):
        return expr.name
    if isinstance(expr, AddExpr):
        return "(" + " + ".join(expr_to_python(arg) for arg in expr.args) + ")"
    if isinstance(expr, SubExpr):
        if isinstance(expr.right, ConstExpr) and expr.right.value.numerator < 0:
            flipped = const(-expr.right.value.numerator, expr.right.value.denominator)
            return f"({expr_to_python(expr.left)} + {expr_to_python(flipped)})"
        return f"({expr_to_python(expr.left)} - {expr_to_python(expr.right)})"
    if isinstance(expr, MulExpr):
        return "(" + " * ".join(expr_to_python(arg) for arg in expr.args) + ")"
    if isinstance(expr, DivExpr):
        return f"({expr_to_python(expr.left)} / {expr_to_python(expr.right)})"
    if isinstance(expr, NegExpr):
        return f"-({expr_to_python(expr.arg)})"
    if isinstance(expr, PowExpr):
        return f"({expr_to_python(expr.base)})**{expr.exponent}"
    if isinstance(expr, SinExpr):
        return f"sin({expr_to_python(expr.arg)})"
    if isinstance(expr, CosExpr):
        return f"cos({expr_to_python(expr.arg)})"
    if isinstance(expr, ExpExpr):
        return f"exp({expr_to_python(expr.arg)})"
    if isinstance(expr, TanhExpr):
        return f"tanh({expr_to_python(expr.arg)})"
    if isinstance(expr, LogExpr):
        return f"log({expr_to_python(expr.arg)})"
    if isinstance(expr, SqrtExpr):
        return f"sqrt({expr_to_python(expr.arg)})"
    if isinstance(expr, AtanExpr):
        return f"atan({expr_to_python(expr.arg)})"
    raise TypeError(f"unsupported expression kind: {type(expr).__name__}")


def synthesis_proposal_model(problem: ProblemSpec) -> type[BaseModel]:


    if problem.task_type == TaskType.STABILITY:
        return StabilityCandidateProposal
    if problem.task_type == TaskType.ROA:
        return RoaCandidateProposal
    return CandidateProposal


def candidate_prompt_view(problem: ProblemSpec, candidate: CandidateSpec) -> dict[str, Any]:


    def rational_text(value: Any) -> str | None:
        if value is None:
            return None
        return _rational_text(value.numerator, value.denominator)

    view: dict[str, Any] = {
        "certificate": expr_to_python(candidate.certificate_ast),
        "controllers": [
            {
                "variable": assignment.variable,
                "expression": expr_to_python(assignment.expression),
            }
            for assignment in candidate.controller_ast.assignments
        ],
        "construction_summary": candidate.construction_summary,
        "assumptions": list(candidate.assumptions),
    }
    if problem.task_type == TaskType.ROA:
        view["level_c"] = (
            None if candidate.level_c is None else expr_to_python(candidate.level_c)
        )
    elif problem.task_type == TaskType.STABILITY:
        view.update(
            {
                "exp_c1": rational_text(candidate.exp_c1),
                "exp_c2": rational_text(candidate.exp_c2),
                "exp_c3": rational_text(candidate.exp_c3),
            }
        )
    else:
        view.update(
            {
                "level_c": (
                    None if candidate.level_c is None else expr_to_python(candidate.level_c)
                ),
                "exp_c1": rational_text(candidate.exp_c1),
                "exp_c2": rational_text(candidate.exp_c2),
                "exp_c3": rational_text(candidate.exp_c3),
            }
        )
    return view


def _box_text(box: BoxSpec | None) -> str:
    if box is None:
        return "unbounded"
    parts = []
    for name in box.lower:
        lo = _rational_text(box.lower[name].numerator, box.lower[name].denominator)
        hi = _rational_text(box.upper[name].numerator, box.upper[name].denominator)
        parts.append(f"{name} in [{lo}, {hi}]")
    return ", ".join(parts)


def _state_domain_text(problem: ProblemSpec) -> str:
    if problem.formal_domain_unbounded:
        return "R^n (unbounded; no screening-box bounds occur in formal queries)"
    return _box_text(problem.analysis_box)


def _control_set_text(problem: ProblemSpec) -> str:
    if not problem.system.control_vars:
        return "none"
    if problem.control_set is None:
        return "not required"
    return _box_text(problem.control_set)


def _control_observations_text(problem: ProblemSpec) -> str:
    observations = problem.system.control_observations
    if observations is None:
        return "full-state feedback"
    return "; ".join(
        f"{control} may use only ({', '.join(observations[control]) or 'no states'})"
        for control in problem.system.control_vars
    )


def _fixed_parameters_text(problem: ProblemSpec) -> str:
    if not problem.fixed_parameters:
        return "none"
    return "; ".join(
        f"{parameter.name} in "
        f"[{_rational_text(parameter.lower.numerator, parameter.lower.denominator)}, "
        f"{_rational_text(parameter.upper.numerator, parameter.upper.denominator)}], "
        "universally quantified and fixed for each trajectory"
        for parameter in problem.fixed_parameters
    )


def _constraint_text(constraint: Constraint) -> str:
    return (
        f"{expr_to_python(constraint.lhs)} {_RELATION_TEXT[constraint.relation]} "
        f"{expr_to_python(constraint.rhs)}"
    )


def _region_text(region: RegionSpec | None) -> str:
    if region is None:
        return "none"
    base_atoms = [_constraint_text(constraint) for constraint in region.constraints]
    base = " and ".join(base_atoms)
    alternatives = []
    for group in region.any_of:
        inner = " and ".join(_constraint_text(constraint) for constraint in group.constraints)
        alternatives.append(f"({inner})" if inner else "true")
    disjunction = " or ".join(alternatives)
    if base and disjunction:
        body = f"({base}) and ({disjunction})"
    elif base:
        body = base
    elif disjunction:
        body = disjunction
    else:
        body = "true"
    if region.bounds is not None:
        return f"{body}  (also {_box_text(region.bounds)})"
    return body


def _assumptions_text(assumptions: tuple[str, ...]) -> str:
    if not assumptions:
        return "none"
    return "; ".join(assumptions)


def _problem_brief(problem: ProblemSpec) -> str:
    contract = problem.indexed_family
    if contract is not None:
        parameter = contract.parameter.name
        family_names = tuple(family.name for family in contract.state_families)
        if contract.state_dimension == "2m":
            state_text = "(x(1), y(1), ..., x(m), y(m)) in R^(2m)"
        else:
            state_text = "(x(1), ..., x(n)) in R^n"

        equations: list[str] = []
        for equation in contract.block_dynamics:
            rhs = expr_to_python(equation.rhs)
            if contract.shared_controller is not None:
                controller = contract.shared_controller
                rhs = re.sub(
                    rf"\b{re.escape(controller.output_symbol)}\b",
                    f"{controller.name}({controller.input_family})",
                    rhs,
                )
            for family_name in family_names:
                rhs = re.sub(
                    rf"\b{re.escape(family_name)}\b", f"{family_name}(i)", rhs
                )
            equations.append(f"d{equation.state_family}(i)/dt = {rhs}")

        if contract.domain.kind == "unbounded":
            domain_text = f"R^({contract.state_dimension})"
        else:
            assert contract.domain.lower is not None and contract.domain.upper is not None
            lower = _rational_text(
                contract.domain.lower.numerator, contract.domain.lower.denominator
            )
            upper = _rational_text(
                contract.domain.upper.numerator, contract.domain.upper.denominator
            )
            domain_text = f"[{lower},{upper}]^({contract.state_dimension})"
        controller_line = (
            ""
            if contract.shared_controller is None
            else (
                f"\nController: one shared scalar law {contract.shared_controller.name}"
                f"({contract.shared_controller.argument}), observed from each coordinate "
                "itself, applied identically at every index, and constrained by "
                f"{contract.shared_controller.name}(0)=0"
            )
        )
        return "\n".join(
            (
                f"System name: {problem.name}",
                f"Problem id: {problem.problem_id}",
                "System semantics: continuous-time",
                f"Family quantification: for every positive natural number {parameter}",
                f"State: {state_text}",
                f"Dynamics: for every i=1,...,{parameter}, {'; '.join(equations)}"
                + controller_line,
                f"Equilibrium: the zero state in R^({contract.state_dimension})",
                f"Formal state domain X: {domain_text}",
                f"Verification target: {contract.target.kind}",
            )
        )
    assert problem.system is not None
    names = ", ".join(problem.system.state_vars)
    equations = []
    for name, expression in zip(problem.system.state_vars, problem.system.dynamics, strict=True):
        if problem.system.kind == DynamicsKind.CONTINUOUS:
            equations.append(f"d{name}/dt = {expr_to_python(expression)}")
        else:
            equations.append(f"{name}[k+1] = {expr_to_python(expression)}")
    controls = ", ".join(problem.system.control_vars) if problem.system.control_vars else "none"
    lines = [
        f"System name: {problem.name}",
        f"Problem id: {problem.problem_id}",
        f"System semantics: {problem.system.kind.value}-time",
        f"Dynamics: {'; '.join(equations)}",
        f"State variables: {names}",
        f"Control variables: {controls}",
        f"Formal state domain X: {_state_domain_text(problem)}",
        f"FastCheck screening box: {_box_text(problem.analysis_box)}",
        f"Initial set X_i: {_region_text(problem.initial_set)}",
        f"Unsafe set X_u: {_region_text(problem.unsafe_set)}",
        f"Assumptions: {_assumptions_text(problem.assumptions)}",
    ]
    if problem.fixed_parameters:
        lines.insert(5, f"Fixed parameters W: {_fixed_parameters_text(problem)}")
    if problem.system.control_vars:
        control_index = 8 if problem.fixed_parameters else 7
        lines.insert(control_index, f"Control set U: {_control_set_text(problem)}")
        lines.insert(
            control_index + 1,
            f"Controller observations: {_control_observations_text(problem)}",
        )
    lines.extend(profile_for(problem).brief_lines(problem))
    return "\n".join(lines)


def synthesis_prompt(
    problem: ProblemSpec,
    *,
    structure_index: int,
    verified_counterexamples: list[dict[str, Any]] | None = None,
    prior_feedback: list[dict[str, Any]] | None = None,
) -> str:
    del structure_index, verified_counterexamples, prior_feedback
    allowed_calls = ",".join((*CORE_UNARY_FUNCTIONS, *SUGAR_UNARY_FUNCTIONS))
    indexed_family = is_indexed_family_problem(problem)
    names = (
        "the indexed coordinates declared in System information"
        if indexed_family
        else ", ".join(problem.system.state_vars)
    )
    fixed_parameter_constraint = (
        "The declared fixed parameters may appear in the supplied dynamics "
        "and in construction_summary when explaining uniform bounds, but "
        "they are forbidden in certificate and controller expressions: "
        "return one state-only B(x), not B(x,w) and not one certificate per "
        "parameter value. "
        if problem.fixed_parameters
        else ""
    )
    proposal_model = synthesis_proposal_model(problem)
    controller_constraint = (
        ""
        if indexed_family
        else (
            "Every controller assignment must obey the Controller observations "
            "information pattern shown above; the pipeline rejects the candidate "
            "after parsing if an assignment reads any other state. "
        )
    )
    expression_examples = (
        "Supported scalar functions may be applied to any indexed subexpression. "
        "Division is allowed; parenthesize denominators that are sums. "
        if indexed_family
        else (
            "Names other than sin,cos,exp,tanh,log,sqrt,atan are expanded to the stored "
            "AST before verification; for example sech(x1) becomes "
            "2/(exp(x1)+exp(-x1)). The equivalent square-root spellings sqrt(x), "
            "x**(1/2), and x**0.5 are all accepted and normalized to the same exact AST. "
            "Division of expressions is allowed, for example x1**2/(1+x1**4); write "
            "parentheses when the denominator is a sum. "
        )
    )
    if indexed_family:
        contract = problem.indexed_family
        assert contract is not None
        parameter = _indexed_family_parameter(problem)
        controlled = contract.shared_controller is not None
        role = (
            "You are a control theory expert specializing in dimension-polymorphic "
            "Lyapunov certificates"
            + (" and shared scalar feedback laws." if controlled else ".")
        )
        if contract.target.kind == "global_asymptotic_stability":
            framework = (
                "For every positive dimension parameter, V must vanish at the zero "
                "state, be positive away from zero, have a strictly negative continuous-"
                "time Lie derivative away from zero, and be radially unbounded. The "
                "locked conclusion is global asymptotic stability of that whole family."
            )
            objective = "Propose V in the certificate expression string."
        else:
            framework = (
                "For every positive dimension parameter, the candidate level set "
                "Omega_c={x | V(x)<=c} must lie in the declared coordinate-wise domain. "
                "V must vanish at zero, be positive away from zero on Omega_c, and have "
                "a strictly negative continuous-time Lie derivative there. The shared "
                "controller must satisfy kappa(0)=0. The locked conclusion certifies "
                "Omega_c itself as a region-of-attraction inner estimate."
            )
            objective = (
                "Propose V in the certificate expression string, one exact positive "
                "level_c, and the declared shared scalar controller."
            )
        objective += (
            f" Propose one symbolic candidate family that satisfies the stated target "
            f"for every positive natural number {parameter}."
        )
    else:
        profile = profile_for(problem)
        role = profile.synthesis_role(problem)
        framework = profile.synthesis_framework(problem)
        objective = profile.synthesis_objective(problem)
    if problem.fixed_parameters:
        parameter_names = ", ".join(
            parameter.name for parameter in problem.fixed_parameters
        )
        objective += (
            " Find one common certificate B(x), depending only on the physical state, "
            f"that proves the required conditions for every fixed ({parameter_names}) "
            "in the declared parameter box W."
        )
    has_controller = (
        problem.indexed_family is not None
        and problem.indexed_family.shared_controller is not None
    ) or (
        problem.system is not None and bool(problem.system.control_vars)
    )
    if has_controller:
        if indexed_family:
            objective += (
                " Jointly design the one shared controller; no separate coordinate "
                "controllers or undeclared hard control bounds may be introduced. "
                "Prefer the simplest controller that can satisfy all formal conditions; "
                "use a nonlinear controller only if a simple controller cannot do so."
            )
        elif problem.control_set is None:
            magnitude_preference = (
                "prefer smaller gains or slower control-to-state growth, so control "
                "magnitude is not made unnecessarily large"
                if problem.formal_domain_unbounded
                else (
                    "prefer a controller with modest magnitude on X instead of "
                    "unnecessarily large gains"
                )
            )
            objective += (
                " Jointly design the required controller; no hard control set U was "
                "declared, so do not invent a bound. Among controllers that satisfy all "
                f"formal conditions, prefer a structurally simple controller and {magnitude_preference}. "
                "Try a constant, linear, or affine controller first; use a nonlinear "
                "controller only if those simple forms cannot satisfy the formal conditions."
            )
        elif not indexed_family:
            objective += (
                " Jointly design the required controller inside the declared control set "
                "U. Among formally valid controllers, prefer a structurally simple one "
                "with modest magnitude on X. Try a constant, linear, or affine controller "
                "first; use a nonlinear controller only if those simple forms cannot "
                "satisfy the formal conditions."
            )
    certificate_symbol = (
        "V" if problem.task_type in {TaskType.STABILITY, TaskType.ROA} else "B"
    )
    if indexed_family:
        verification_roadmap = (
            "The pipeline checks the submitted symbolic candidate against the quantified "
            "family. construction_summary may explain the submitted expression, but it "
            "does not alter the candidate or the verification target."
        )
    elif problem.system is not None and problem.system.kind == DynamicsKind.CONTINUOUS:
        verification_roadmap = (
            f"The pipeline symbolically differentiates {certificate_symbol} and "
            "independently checks the "
            "continuous-time queries. construction_summary is a construction note, not "
            "a certificate; downstream Lean proof agents read it as their roadmap, so "
            "it must name the useful auxiliary quantities, give a factorised form of "
            f"the Lie expression grad {certificate_symbol} dot f_cl in those quantities, "
            "and list the "
            "boundedness facts with explicit constants that close the sign inequality."
        )
        if problem.fixed_parameters:
            verification_roadmap += (
                " The Lie query universally ranges over the fixed parameter box W "
                "(implemented as an existential counterexample search in x and the "
                "parameter). Factor or bound the parameter-dependent Lie expression "
                "uniformly over the full interval; do not optimize for one nominal "
                "parameter value."
            )
    elif problem.task_type in {TaskType.STABILITY, TaskType.ROA}:
        verification_roadmap = (
            "This is a discrete-time Lyapunov task. Use only the one-step closed-loop "
            "map F_cl. The pipeline independently constructs and checks V(F_cl(x)) - V(x). "
            "construction_summary is a construction note, not a certificate; downstream "
            "Lean proof agents read it as their roadmap, so give a factorised one-step "
            "decrease expression and the exact bounds that close the required sign inequality. "
            "Use no continuous-time notation, flow argument, or Lie derivative."
        )
    else:
        verification_roadmap = (
            "This is a discrete-time system. Use only the one-step closed-loop map "
            "F_cl. The pipeline independently constructs and checks B(F_cl(x)) from "
            "the submitted B and controller. construction_summary is a construction "
            "note, not a certificate; downstream Lean proof agents read it as their "
            "roadmap, so it must name the useful auxiliary quantities, give a "
            "factorised form of B(F_cl(x)) - B(x) or an equivalent one-step bound, "
            "and list the boundedness facts with explicit constants that close "
            "B(x) >= 0 -> B(F_cl(x)) >= 0. Use no continuous-time notation, flow "
            "argument, Lie expression, or strict boundary argument."
        )
    if indexed_family:


        family_examples = "No worked certificate examples are supplied for this task."
    elif problem.system is not None and problem.system.kind == DynamicsKind.CONTINUOUS:
        family_examples = (
            "Structure examples only. Polynomial: for dx1/dt = -x1 + x1*x2 and "
            "dx2/dt = -x2 on x1**2 + x2**2 <= 1, V = x1**2 + x2**2 gives "
            "D V = -2*x1**2*(1-x2) - 2*x2**2 <= 0. Non-polynomial: for "
            "dx1/dt = -x1*(1+x1**2), V = log(1+x1**2) gives the exact identity "
            "D V = -2*x1**2, with 1+x1**2 > 0."
        )
    else:
        family_examples = (
            "Structure examples only. Polynomial: for x1[k+1] = x1/2, "
            "V = x1**2 gives V(F(x1)) - V(x1) = -(3/4)*x1**2. "
            "Non-polynomial: for x1[k+1] = log(1+x1) on x1 >= 0, "
            "V = exp(x1)-1 gives V(F(x1)) = x1 and uses exp(x1) >= 1+x1."
        )
    return _render(

        [
            (
                "Role",
                role,
            ),
            ("System information", _problem_brief(problem)),
            ("Mathematical framework", framework),
            (
                "Objective",
                objective,
            ),
            (
                "Certificate-family discipline",
                "Choose the simplest certificate structure justified by the dynamics, "
                "domain, and verification conditions. Non-polynomial dynamics do not by "
                "themselves require a non-polynomial certificate. Use transcendental or "
                "rational terms only when construction_summary gives a concrete identity "
                "or inequality showing how they help close the required condition. Ensure "
                f"every expression is well-defined on X. {family_examples}",
            ),
            (
                "Constraints",
                "Use only declared state variables "
                f"({names}). Do not leave free symbols such as delta or epsilon. "
                + (_indexed_family_syntax(problem) + " " if indexed_family else "")
                + fixed_parameter_constraint
                + controller_constraint
                + "Return certificate "
                "and controller expressions as concise strings; never emit recursive AST "
                "nodes. Numeric literals are parsed as exact rationals: 0.01 becomes 1/100, "
                "and 1/100 is also fine. The name pi denotes the exact constant Real.pi; "
                "do not replace it by a decimal approximation. Allowed function "
                f"names: {allowed_calls}. log is the natural logarithm. sqrt(arg) requires "
                "arg >= 0 on X; atan is the two-sided inverse tangent; atanh(arg) may be "
                "used only when -1 < arg < 1 on X. "
                + expression_examples
                + "Do not invent other function "
                "names and do not use Abs. "
                f"{verification_roadmap}",
            ),
            ("Output schema", _schema(proposal_model)),
            (
                "Stop rules",
                "Return exactly one JSON object matching the schema. "
                + (
                    "Put only the bare sum(i, m|n, body) expression in certificate; "
                    "never prefix it with V =, B =, or an assignment. "
                    if indexed_family
                    else "Put B or V in the certificate string. "
                )
                + "Put each control law in controllers[].expression. "
                "Do not output certificate_ast, controller_ast, kind, left, right, args, "
                "numerator, or denominator nodes. Never replace a failed attempt with a "
                "placeholder linear form just to return something.",
            ),
        ]
    )


def synthesis_followup(
    *,
    problem: ProblemSpec,
    structure_index: int,
    failed_candidate: dict[str, Any] | None,
    verified_counterexample: dict[str, Any] | None,
    rejected_history: list[dict[str, Any]],
    errors: list[str],
) -> str:


    if is_indexed_family_problem(problem):
        dynamics_reminder = (
            "Continue with the continuous-time indexed-family semantics and the locked "
            "all-positive-dimensions target."
        )
    elif problem.system is not None and problem.system.kind == DynamicsKind.CONTINUOUS:
        dynamics_reminder = (
            "Continue with continuous-time flow semantics and the locked continuous-time "
            "conditions."
        )
        if problem.fixed_parameters:
            dynamics_reminder += (
                " Keep the same state-only B(x) and repair the failed condition uniformly "
                "for every fixed parameter in W; the parameter may be used only when "
                "reasoning about the dynamics and its interval bounds."
            )
    elif problem.task_type in {TaskType.STABILITY, TaskType.ROA}:
        dynamics_reminder = (
            "Continue with discrete-time one-step Lyapunov semantics only: reason about "
            "F_cl(x) and V(F_cl(x)) - V(x). Use no continuous-time notation, flow "
            "argument, Lie expression, or strict boundary argument."
        )
    else:
        dynamics_reminder = (
            "Continue with discrete-time one-step semantics only: reason about F_cl(x), "
            "B(F_cl(x)), and B(x) >= 0 -> B(F_cl(x)) >= 0. Use no continuous-time "
            "notation, flow argument, Lie expression, or strict boundary argument."
        )
    if problem.task_type == TaskType.STABILITY:
        task_reminder = (
            "This is P1 Stability: level_c is not part of the output contract and cannot "
            "restrict any obligation. Every counterexample in the fixed claimed domain N "
            "must be addressed by changing V or the controller; it may not be excluded by "
            "asserting V <= c."
        )
    elif problem.task_type == TaskType.ROA:
        task_reminder = (
            "This is P2 ROA: level_c defines Omega_c and may be changed, but the candidate "
            "must still prove the locked containment and Lyapunov obligations on Omega_c."
        )
    else:
        task_reminder = "Keep the locked barrier task and its fixed working domain unchanged."
    family_reminder = (
        " Keep the candidate symbolic for the entire quantified family; do not replace "
        f"{_indexed_family_parameter(problem)} by a concrete dimension."
        if is_indexed_family_problem(problem)
        else ""
    )
    return _render(
        [
            (
                "Next turn",
                "The system message still has the problem, the locked task conditions, and the "
                "output schema. Do not wait for those sections to be repeated. Below is "
                "only new evidence: the failed candidate and independently verified "
                "counterexamples. Diagnose the failed condition yourself and propose the "
                "next candidate. Change the expression structure when coefficient tuning "
                f"cannot address the evidence. {dynamics_reminder} {task_reminder}"
                f"{family_reminder}",
            ),
            (
                "New evidence",
                canonical_json(
                    {
                        "candidate_index": structure_index,
                        "failed_candidate": failed_candidate,
                        "verified_counterexample": verified_counterexample,
                        "rejected_history": rejected_history,
                        "parse_or_semantic_errors": errors,
                    }
                ),
            ),
            (
                "Stop rules",
                "Return exactly one JSON object matching the original task-specific "
                "synthesis schema. Expressions must remain concise strings, not recursive "
                "AST nodes.",
            ),
        ]
    )


def lean_proof_prompt(
    *,
    candidate: CandidateSpec | FamilyCandidateSpec,
    candidate_hash: str,
    condition: Condition,
    locked_definitions: str,
    locked_statement: str,
    public_lemmas: tuple[str, ...],
    previous_proof_body: str,
    compiler_diagnostics: str,
    mode: str,
    indexed_family: bool = False,
) -> str:
    fixed = {
        "candidate_hash": candidate_hash,
        "condition": {
            "condition_id": condition.condition_id,
            "kind": condition.kind.value,
            "description": condition.description,
        },
        "locked_definitions": locked_definitions,
        "locked_statement": locked_statement,
        "public_lemmas": public_lemmas,
        "previous_proof_body": previous_proof_body,
        "compiler_diagnostics": compiler_diagnostics,
        "mode": mode,
    }
    if indexed_family:
        fixed["candidate_construction_summary"] = candidate.construction_summary
        fixed["candidate_assumptions"] = list(candidate.assumptions)
        return _render(
            [
                (
                    "Role",
                    "Prove the locked, candidate-specific Lyapunov obligations for "
                    "the entire dimension-quantified system family.",
                ),
                (
                    "Goal",
                    "Return the complete term placed after := in proof_body. The "
                    "locked definitions contain the indexed system, submitted "
                    "certificate, symbolic dimension, and derived expressions. Prove "
                    "exactly the stated Lyapunov premises for every positive dimension; "
                    "do not replace its natural-number parameter by a numeral. The "
                    "candidate construction summary in Fixed inputs was produced by the "
                    "synthesis agent for this already-locked candidate and is the intended "
                    "proof roadmap.",
                ),
                (
                    "Compilation",
                    "You do not need a local Lean workspace. The harness compiles the "
                    "response against Lean 4 with Mathlib and returns exact diagnostics "
                    "on later rounds. A result is accepted only after compilation, "
                    "statement-hash checking, and the axiom audit. Each helper_lemmas "
                    "entry is compiled as its own module against a shared remaining "
                    "wall-clock budget, so many helpers are expensive and often time out.",
                ),
                ("Fixed inputs", canonical_json(fixed)),
                (
                    "Constraints",
                    "Do not change the definitions, theorem statement, system, controller, "
                    "candidate, dimension quantifier, or candidate hash. proof_body is "
                    "inserted only after :=. Prefer helper_lemmas = [] and put the whole "
                    "argument in proof_body. Use helper_lemmas only when a short reusable "
                    "fact is otherwise awkward; at most two named helpers, each with a "
                    "short proof, never a long dependency chain. Do not use sorry, admit, "
                    "axiom, unsafe, imports, Markdown, or external assumptions. Fix every "
                    "compiler error reported in the current reply. Do not unfold or "
                    "directly prove ContinuousROAOn, ContinuousGloballyAsymptoticallyStable, "
                    "ClassicalTrajectory, or Tendsto: the audited framework applies the "
                    "generic Lyapunov closing theorem after these obligations compile.",
                ),
                ("Output schema", _schema(LeanAgentOutput)),
                (
                    "Stop rules",
                    "Return candidate_proof only with a concrete proof body. Return "
                    "cannot_complete only with the precise mathematical or compiler blocker.",
                ),
            ]
        )
    proof_context = (
        "The synthesis agent wrote the construction note below for this exact "
        "candidate; it usually names the intended variable decomposition, the "
        "factorised form of the derivative expression, and the boundedness "
        "facts that make the decay argument work. The locked statement is the "
        "fully expanded form of that expression: first recover the note's "
        "decomposition with let/set, then prove along the note's argument.\n"
        f"Construction note: {candidate.construction_summary}\n"
        "Assumptions: "
        + ("; ".join(candidate.assumptions) if candidate.assumptions else "none")
    )
    high_dimensional_hint = (
        "For high-dimensional systems, prefer vector, matrix, finite-sum, "
        "quadratic-form, and operator-norm arguments. In coupled finite-dimensional "
        "systems, keep coordinates as functions on Fin n and prove bounds on "
        "∑ i, (x i)^2 with tools such as Finset.sum_le_sum, Cauchy--Schwarz, and "
        "Young inequalities. Do not expand every coordinate square into one giant "
        "ring_nf goal; connect generated coordinate definitions to the abstract "
        "vector or matrix expression with a small extensional bridge lemma."
    )
    return _render(
        [
            ("Role", "Complete one fixed Lean 4/Mathlib condition."),
            (
                "Goal",
                "Return a complete proof after := in proof_body. helper_lemmas is "
                "available when a genuinely reusable proposition makes the proof clearer, "
                "but it is optional: a direct proof is equally valid. Decide the proof "
                "architecture from this locked theorem instead of introducing helpers "
                "merely because the output field exists. Each helper entry, if any, must "
                "contain exactly one named lemma or theorem declaration. Do not change the "
                "locked theorem statement.",
            ),
            (
                "Division of labour",
                "You do not need and will not get a local Lean workspace or compiler. "
                "The harness compiles your text against Lean 4 with Mathlib and returns "
                "the diagnostics to you on the next round. Never return cannot_complete "
                "because the environment, source files, or a compiler are unavailable; "
                "just emit your best concrete proof body.",
            ),
            (
                "Success criteria",
                "The wrapper compiles each helper as a content-addressed Lean module, "
                "imports the accepted modules into the main proof, matches the locked "
                "statement hash, and accepts #print axioms if the "
                "only axioms are propext, Classical.choice, and Quot.sound. sorryAx, "
                "user-written axiom, and any other kernel axiom fail the audit.",
            ),
            ("Fixed inputs", canonical_json(fixed)),
            (
                "Constraints",
                "Do not change definitions, theorem statement, system, controller, candidate, "
                "or candidate hash. Do not emit a top-level lemma inside proof_body; that "
                "text is inserted only after :=. No sorry, admit, axiom, external trusted "
                "assumption, full project, Markdown, or natural-language proof sketch. "
                "If you choose helpers, put one declaration in each helper_lemmas entry "
                "in dependency order and keep each helper focused. Keep one-use facts as "
                "local have/calc steps. If "
                "compiler_diagnostics lists errors, fix all of them in this one reply; do "
                "not wait for a later round. State n is Fin n → ℝ. RadiallyUnbounded uses "
                "R ≤ ∑ i, (x i)^2, not ‖x‖ or EuclideanSpace.norm_sq_eq. That radius "
                "is not a claim that V is quadratic. The locked definitions are ordinary "
                "Lean expressions, not DSL ASTs. Use the generated barrier_unfold_* and "
                "closedLoop_apply_* simp lemmas when exposing their formulas. nlinarith "
                "and linarith only close polynomial or linear goals; "
                "they cannot see Real.exp, Real.log, or Real.tanh, but they treat such "
                "subterms as atoms, so first derive sign facts about them with have and "
                "pass those facts in. The locked "
                "statement already has (hV : ContDiff ℝ 1 barrier); use hV, do not "
                "re-prove smoothness with decide or isTotalSmooth. Use only lemma names "
                "that exist in Mathlib or that you fully prove in helper_lemmas; never "
                "cite invented names such as lean_barrier_*. Before the expensive proof "
                "compile, the harness prechecks qualified Real.* names; this is only an "
                "early name check, and declarations from any Lean or Mathlib namespace "
                "remain allowed when the normal compiler accepts them.",
            ),
            (
                "Recurring pitfalls",
                "The locked statement already binds every hypothesis such as "
                "(hV : ContDiff ℝ 1 barrier); the goal starts at the ¬ ∃. Begin the "
                "proof with rintro ⟨x, hx⟩ (or intro h), never with intro hV. "
                "For a fixed-parameter condition the locked counterexample statement also "
                "binds one or more scalar parameters after x. Destructure all existential "
                "binders, retain the exact interval hypotheses, and prove the inequality "
                "uniformly; the generated barrier still has type State n → ℝ and therefore "
                "must not be redefined as a function of those parameters. "
                "Cite only Mathlib lemma names you are certain exist; when a name "
                "fails with unknown constant, do not guess variant names on the next "
                "round. Treat the proposition intended by that name as an explicit "
                "subgoal: prove it from verified declarations as a local have, or as a "
                "named helper only when it is genuinely reusable, then use that fact in "
                "the main proof. "
                "The compiler feedback includes a local Mathlib source search for the "
                "failed name: use only declarations listed there as ingredients. Close "
                "intermediate have steps with linarith [lemma] "
                "or nlinarith [lemma] rather than exact lemma: exact demands a "
                "syntactically identical type and fails on argument order or "
                "associativity differences that linarith absorbs. When a Type "
                "mismatch shows two types that differ only by parenthesisation or "
                "term order, do not restructure the proof; run ring_nf at h ⊢ first "
                "or replace exact h with linarith [h]. "
                + high_dimensional_hint,
            ),
            (
                "Author's proof roadmap",
                proof_context,
            ),
            ("Output schema", _schema(LeanAgentOutput)),
            (
                "Stop rules",
                "Return candidate_proof only with a concrete proof body. Return cannot_complete "
                "with the precise blocker when the locked statement cannot be completed. "
                "If you believe the locked theorem is FALSE, you must also fill the "
                "counterexample field with one concrete state, e.g. "
                '{"x1": "1/2", "x2": "-3/4"} using exact rationals for every variable. '
                "The harness replays your point in high-precision arithmetic before "
                "accepting the claim; a rejected point is returned to you and you must "
                "keep proving. Never claim falsity from mental arithmetic alone.",
            ),
        ]
    )


def lean_followup(
    *,
    candidate_hash: str,
    condition: Condition,
    locked_definitions: str,
    locked_statement: str,
    previous_proof_body: str,
    compiler_diagnostics: str,
    mode: str,
) -> str:
    return _render(
        [
            (
                "Next turn",
                "The system message still has the Lean role and schema. helper_lemmas "
                "are still one named declaration per entry and are independently cached; "
                "proof_body still goes after :=. Keep already accepted helpers unchanged "
                "and edit only the failing helper or main proof. "
                "Below is the current locked theorem and compiler output. Continue "
                "from your last proof.",
            ),
            (
                "New evidence",
                canonical_json(
                    {
                        "candidate_hash": candidate_hash,
                        "condition": {
                            "condition_id": condition.condition_id,
                            "kind": condition.kind.value,
                            "description": condition.description,
                        },
                        "locked_definitions": locked_definitions,
                        "locked_statement": locked_statement,
                        "previous_proof_body": previous_proof_body,
                        "compiler_diagnostics": compiler_diagnostics,
                        "mode": mode,
                    }
                ),
            ),
            (
                "Stop rules",
                "Return exactly one JSON object: candidate_proof with a concrete proof "
                "body, or cannot_complete with the precise blocker.",
            ),
        ]
    )


def lean_local_repair_prompt(request: Any) -> str:


    fixed = {
        "base_output_hash": request.base_output_hash,
        "patch_id": request.patch_id,
        "target": {
            "kind": request.target_kind,
            "index": request.target_index,
            "line": request.line_index + 1,
            "old_text": request.old_text,
        },
        "source_window": request.source_window,
        "compiler_context": request.compiler_context,
        "lean_verified_declarations": request.verified_declarations,
    }
    return _render(
        [
            (
                "Local repair turn",
                "The initial proof is frozen. For this turn only, do not return the full "
                "helper_lemmas/proof_body document. Repair exactly the framework-selected "
                "line below and return LeanLocalPatch.",
            ),
            ("Compiler-grounded request", canonical_json(fixed)),
            (
                "Constraints",
                "Return replacement_code relative to the existing indentation: its first "
                "line starts in column 1, and every later line at the same Lean nesting level "
                "also starts in column 1; add spaces only for nesting introduced inside the "
                "replacement. It may be one Lean line or a local multi-line `by` proof, but "
                "may not declare a new top-level lemma. Preserve all unrelated proof text. "
                "Never reuse a declaration that compiler_context reports as unknown. A "
                "new qualified declaration name is permitted only when its exact declaration "
                "is shown in lean_verified_declarations; otherwise prove the needed fact "
                "locally from already accepted surrounding facts. No sorry, admit, axiom, import, "
                "unsafe, Markdown, or explanation outside JSON. If this line cannot be "
                "repaired locally without changing another line, return cannot_patch.",
            ),
            ("Output schema", _schema(LeanLocalPatch)),
            (
                "Stop rules",
                "Echo patch_id exactly. Return patch only with concrete replacement_code; "
                "otherwise return cannot_patch with an empty replacement_code and reason.",
            ),
        ]
    )


def verification_router_prompt(
    condition: Condition,
    capability_summary: dict[str, Any],
) -> str:


    fixed = {
        "condition": condition.model_dump(mode="json"),
        "deterministic_capabilities": capability_summary,
    }
    return _render(
        [
            (
                "Role",
                "Choose the verification backend for one fixed condition after the "
                "deterministic fast check has passed.",
            ),
            (
                "Goal",
                "Choose exactly direct_lean or smt. If smt is selected, rank every eligible "
                "solver exactly once.",
            ),
            (
                "Success criteria",
                "Use only the supplied deterministic capability summary. Do not attempt the "
                "proof and do not claim that the condition is valid.",
            ),
            ("Fixed inputs", canonical_json(fixed)),
            (
                "Constraints",
                "Do not change the condition or solver eligibility. direct_lean must return "
                "an empty solver_order. smt must return a complete permutation of the eligible "
                "backends. SMT results are checked independently and may be rescued by Lean4. "
                "When the counterexample query includes a bounded fixed parameter, keep it "
                "as an ordinary quantified query variable: UNSAT means no violating pair "
                "(x,w) exists and therefore establishes the uniform condition. Do not treat "
                "the parameter as a state coordinate or as a certificate variable.",
            ),
            ("Output schema", _schema(VerificationRouterDecision)),
            ("Stop rules", "Return exactly one JSON object and no Markdown."),
        ]
    )


PROMPT_VERSION = "v8"
