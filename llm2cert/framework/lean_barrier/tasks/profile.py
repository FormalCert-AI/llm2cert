"""Select task profiles and schedule proof obligations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..s01_models import (
    CandidateSpec,
    Condition,
    ConditionKind,
    ProblemSpec,
    TaskType,
)


_CLOSING_KINDS = {
    ConditionKind.SAFETY_INSTANTIATION,
    ConditionKind.INVARIANT_INSTANTIATION,
    ConditionKind.STABILITY_INSTANTIATION,
    ConditionKind.ROA_INSTANTIATION,
}


@dataclass(frozen=True)
class VerifyPlan:


    static: tuple[Condition, ...]
    parallel: tuple[Condition, ...]
    sequential: tuple[Condition, ...]
    closing: Condition
    closing_style: str
    dreal_positive_allowed: bool


def verify_plan(problem: ProblemSpec, conditions: tuple[Condition, ...]) -> VerifyPlan:


    static: list[Condition] = []
    parallel: list[Condition] = []
    sequential: list[Condition] = []
    closing: Condition | None = None
    for condition in conditions:
        if condition.kind in _CLOSING_KINDS:
            closing = condition
            continue
        if condition.kind == ConditionKind.DISCRETE_INDUCTIVE:
            sequential.append(condition)
            continue
        if condition.kind == ConditionKind.RADIAL_UNBOUNDED:
            sequential.append(condition)
            continue
        if condition.query is None:
            static.append(condition)
        else:
            parallel.append(condition)
    if closing is None:
        raise RuntimeError("task schedule is missing a closing condition")


    closing_style = "generic"
    allow_dreal = True
    if problem.task_type == TaskType.STABILITY and problem.stability_kind is not None:
        from .lyapunov_common import dreal_positive_allowed

        allow_dreal = dreal_positive_allowed(problem.stability_kind)
    return VerifyPlan(
        static=tuple(static),
        parallel=tuple(parallel),
        sequential=tuple(sequential),
        closing=closing,
        closing_style=closing_style,
        dreal_positive_allowed=allow_dreal,
    )


class TaskProfile(Protocol):


    task_type: TaskType

    def validate(self, problem: ProblemSpec, candidate: CandidateSpec | None = None) -> None: ...

    def build_conditions(
        self, problem: ProblemSpec, candidate: CandidateSpec
    ) -> tuple[Condition, ...]: ...

    def synthesis_role(self, problem: ProblemSpec) -> str: ...

    def synthesis_framework(self, problem: ProblemSpec) -> str: ...

    def synthesis_objective(self, problem: ProblemSpec) -> str: ...

    def brief_lines(self, problem: ProblemSpec) -> list[str]: ...
