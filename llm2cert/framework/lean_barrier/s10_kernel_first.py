"""Construct deterministic Lean proof templates."""
from __future__ import annotations

import re

from .s01_models import ConditionKind, LeanAgentOutput, LeanAgentStatus
from .s10_lean_gen import LockedTheorem

MAX_KERNEL_FIRST_DIMENSION = 5

_DECLARATION_NAME = re.compile(
    r"^(?:noncomputable\s+)?def\s+([A-Za-z_][A-Za-z0-9_']*)|"
    r"^@\[simp\]\s+theorem\s+([A-Za-z_][A-Za-z0-9_']*)",
    re.MULTILINE,
)


def _generated_names(definitions: str) -> tuple[str, ...]:
    names: list[str] = []
    for match in _DECLARATION_NAME.finditer(definitions):
        name = match.group(1) or match.group(2)
        if name not in names:
            names.append(name)
    return tuple(names)


def _polynomialish(definitions: str) -> bool:


    if "Real." in definitions:
        return False


    return re.search(r"/\s*\(\(?x\s", definitions) is None


def kernel_first_candidate(
    locked: LockedTheorem,
    condition_kind: ConditionKind,
    dimension: int,
    *,
    polynomial_goal: bool,
) -> tuple[str, LeanAgentOutput] | None:


    if dimension < 1 or dimension > MAX_KERNEL_FIRST_DIMENSION:
        return None
    names = _generated_names(locked.definitions)
    square_facts = ", ".join(
        f"sq_nonneg (x {index})" for index in range(dimension)
    )
    if condition_kind == ConditionKind.RADIAL_UNBOUNDED:
        barrier_unfold = next(
            (name for name in names if name.startswith("barrier_unfold_")),
            None,
        )
        if barrier_unfold is None:
            return None
        body = (
            "by\n"
            "  intro K\n"
            "  refine ⟨K, ?_⟩\n"
            "  intro x hx\n"
            f"  simp [{barrier_unfold}] at *\n"
            f"  nlinarith [{square_facts}]"
        )
        return (
            "radial_simp_nlinarith",
            LeanAgentOutput(
                status=LeanAgentStatus.CANDIDATE_PROOF,
                helper_lemmas=(),
                proof_body=body,
            ),
        )
    if not polynomial_goal:
        return None
    if condition_kind == ConditionKind.DISCRETE_INDUCTIVE:
        if not _polynomialish(locked.definitions):
            return None
        barrier_unfold = next(
            (name for name in names if name.startswith("barrier_unfold_")),
            None,
        )
        closed_loop_apply = tuple(
            name for name in names if name.startswith("closedLoop_apply_")
        )
        if barrier_unfold is None or len(closed_loop_apply) != dimension:
            return None
        rewrites = ", ".join((barrier_unfold, *closed_loop_apply))
        body = (
            "by\n"
            "  rintro ⟨x, _, hx, hnext⟩\n"
            f"  simp only [{rewrites}] at hx hnext\n"
            f"  nlinarith [{square_facts}]"
        )
        return (
            "discrete_inductive_simp_nlinarith",
            LeanAgentOutput(
                status=LeanAgentStatus.CANDIDATE_PROOF,
                helper_lemmas=(),
                proof_body=body,
            ),
        )
    if not _polynomialish(locked.definitions):
        return None
    simp_names = ", ".join(names)
    simp_line = f"  simp [{simp_names}] at hx" if simp_names else "  simp at hx"
    body = (
        "by\n"
        "  rintro ⟨x, hx⟩\n"
        f"{simp_line}\n"
        f"  nlinarith [{square_facts}]"
    )
    return (
        "polynomial_simp_nlinarith",
        LeanAgentOutput(
            status=LeanAgentStatus.CANDIDATE_PROOF,
            helper_lemmas=(),
            proof_body=body,
        ),
    )


__all__ = ["MAX_KERNEL_FIRST_DIMENSION", "kernel_first_candidate"]
