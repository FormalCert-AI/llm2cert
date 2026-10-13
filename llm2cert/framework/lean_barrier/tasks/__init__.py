"""Expose the tasks package."""
from __future__ import annotations

from ..s01_models import ProblemSpec, TaskType
from .invariant import InvariantProfile
from .profile import TaskProfile, VerifyPlan, verify_plan
from .roa import RoaProfile
from .safety import SafetyProfile
from .stability import StabilityProfile

_PROFILES = {
    TaskType.SAFETY: SafetyProfile(),
    TaskType.INVARIANT: InvariantProfile(),
    TaskType.STABILITY: StabilityProfile(),
    TaskType.ROA: RoaProfile(),
}


def profile_for(problem: ProblemSpec) -> TaskProfile:
    try:
        profile = _PROFILES[problem.task_type]
    except KeyError as error:
        raise ValueError(f"unsupported task_type: {problem.task_type}") from error
    return profile


__all__ = ["TaskProfile", "VerifyPlan", "profile_for", "verify_plan"]
