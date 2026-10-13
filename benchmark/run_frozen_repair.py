#!/usr/bin/env python3
"""Compare three repair strategies on frozen RQ3 inputs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
CURRENT_ROOT = REPO_ROOT / "llm2cert"
FRAMEWORK_ROOT = CURRENT_ROOT / "framework"
RAW_RQ1_SOURCE = (
    REPO_ROOT / "results/main/data"
)
RAW_RQ3_COHORT = REPO_ROOT / "results/rq3/inputs/manifest.json"
ABLATION_ROOT = REPO_ROOT / "results/rq3"
ABLATION_COHORT = REPO_ROOT / "results/rq3/inputs/manifest.json"
ABLATION_OUTPUT = ABLATION_ROOT / "output"
DEFAULT_SOURCE = REPO_ROOT / "results/rq3/inputs"
DEFAULT_COHORT = DEFAULT_SOURCE / "manifest.json"
DEFAULT_OUTPUT = REPO_ROOT / "runs/rq3"
DEFAULT_ARMS = ("failure_only", "verbatim_diagnostics", "current_guided")
ALL_ARMS = (*DEFAULT_ARMS, "local_patch")
ARM_DEFINITIONS = {
    "failure_only": "common lean_followup with only a fixed failure signal",
    "verbatim_diagnostics": "common lean_followup with verbatim Lean stdout/stderr",
    "current_guided": (
        "common lean_followup with current processed/enriched compiler diagnostics; "
        "full-proof repair, not an explicit category/location/goals schema"
    ),
    "local_patch": "optional exploratory transactional LocalPatch arm",
}

EXPECTED_CANDIDATES: int | None = None
EXPECTED_OBLIGATIONS: int | None = None
EXPECTED_BUNDLE_PAYLOAD_FILES: int | None = None
NATIVE_REPAIR_FEEDBACK = {
    "failure_only": "failure_only",
    "verbatim_diagnostics": "verbatim",
    "current_guided": "processed",
    "local_patch": "processed",
}
COHORT_SCHEMA_VERSION = "dynacert-rq3-cohort.v1"
SCHEMA_VERSION = "dynacert-rq3-frozen-repair.v1"
BUNDLE_SCHEMA_VERSION = "dynacert-rq3-frozen-inputs.v1"
MAX_FRAMEWORK_PROOF_BUDGET_SECONDS = 900.0
FINALIZATION_RESERVE_SECONDS = 60.0
INVISIBLE = str.maketrans("", "", "\ufeff\u200b\u200c\u200d\u2060")
INITIAL_CALL_FIELDS = (
    "schema_version",
    "role",
    "prompt_version",
    "model_id",
    "parameters",
    "status",
    "prompt",
    "prompt_hash",
    "response",
    "response_hash",
    "error",
    "updated_at_utc",
)
INITIAL_CALL_PARAMETER_FIELDS = ("provider", "thinking", "max_tokens")
COMPILER_RESULT_FIELDS = (
    "schema_version",
    "status",
    "module_name",
    "returncode",
    "stdout",
    "stderr",
    "duration_seconds",
    "timed_out",
    "source_hash",
)
SECRET_PATTERNS = (
    (
        "private-key-marker",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
    ),
    ("provider-token", re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")),
    ("github-token", re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    (
        "jwt-token",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
            r"[A-Za-z0-9_-]{8,}\b"
        ),
    ),
    (
        "authorization-value",
        re.compile(
            r"\bauthorization\b\s*[:=]\s*[\"']?(?:bearer|basic)\s+"
            r"[A-Za-z0-9._~+/-]{8,}",
            re.IGNORECASE,
        ),
    ),
    (
        "credential-assignment",
        re.compile(
            r"[\"']?(?:api[_-]?key|access[_-]?token|secret[_-]?key)"
            r"[\"']?\s*[:=]\s*[\"'][^\"'\r\n]{8,}[\"']",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class FrozenFixture:
    fixture_id: str
    record_id: str
    problem_class: str
    candidate_index: int
    condition_slug: str
    condition_id: str
    condition_kind: str
    candidate_hash: str
    statement_hash: str
    run_root: str
    candidate_path: str
    condition_path: str
    lean_dir: str
    lean_result_path: str
    initial_call_path: str
    first_compiler_result_path: str
    first_failure_source_hash: str
    first_failure_kind: str
    initial_attempt_index: int = 0
    initial_system_prompt: str | None = None

    @property
    def job_component(self) -> str:
        return self.fixture_id.replace(":", "_").replace("/", "_")


@dataclass(frozen=True)
class Job:
    fixture_id: str
    arm: str
    repeat: int


def deadline_spec(repair_budget_seconds: float) -> dict[str, float]:


    budget = float(repair_budget_seconds)
    if budget <= 0 or budget > MAX_FRAMEWORK_PROOF_BUDGET_SECONDS:
        raise ValueError(
            "repair budget must be in (0, 900] seconds; LeanProofRunner itself "
            "has a 900-second proof cap"
        )
    return {
        "repair_budget_seconds": budget,
        "finalization_reserve_seconds": FINALIZATION_RESERVE_SECONDS,
        "trajectory_deadline_seconds": budget + FINALIZATION_RESERVE_SECONDS,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _extract_json_object(text: str) -> dict[str, Any] | None:
    clean = text.translate(INVISIBLE).strip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(clean):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(clean, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _submitted_pair(payload: dict[str, Any]) -> tuple[tuple[str, ...], str]:
    return (
        tuple(str(item) for item in payload.get("helper_lemmas") or ()),
        str(payload.get("proof_body") or ""),
    )


def _matching_initial_call(lean_dir: Path, first_attempt: dict[str, Any]) -> Path:
    target = _submitted_pair(first_attempt)
    matches: list[Path] = []
    for path in sorted((lean_dir / "calls").glob("*.json")):
        response = _extract_json_object(str(_read_json(path).get("response") or ""))
        if response is not None and _submitted_pair(response) == target:
            matches.append(path)
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one initial agent response for {lean_dir}, found {len(matches)}"
        )
    return matches[0]


NO_COMPILE_GATE = "no_compile_gate"


def _utc(value: Any) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


def _first_failed_compiler_result(
    lean_dir: Path,
    attempt: dict[str, Any] | None = None,
    initial_call_path: Path | None = None,
) -> Path | None:


    results = sorted((lean_dir / "compiler_attempts").glob("*/result.json"))
    target = None if attempt is None else attempt.get("generated_source_hash")
    if target is None and initial_call_path is not None:
        calls = sorted((lean_dir / "calls").glob("*.json"))
        window_start = _utc(_read_json(initial_call_path).get("updated_at_utc"))
        later = [path for path in calls if path.name > initial_call_path.name]
        window_end = (
            _utc((_read_json(later[0]).get("call_info") or {}).get("called_at_utc"))
            if later
            else None
        )
        for path in results:
            payload = _read_json(path)
            started = _utc(payload.get("started_at_utc"))
            if started is None or window_start is None or started < window_start:
                continue
            if window_end is not None and started >= window_end:
                break
            if int(payload.get("returncode", 1)) != 0:
                return path
        return None
    for path in results:
        payload = _read_json(path)
        if int(payload.get("returncode", 1)) == 0:
            continue


        if target is None or payload.get("source_hash") == target:
            return path
    raise RuntimeError(f"no failed compiler artifact under {lean_dir}")


def _context_compiler_result(lean_dir: Path) -> Path:


    for path in sorted((lean_dir / "compiler_attempts").glob("*/result.json")):
        if int(_read_json(path).get("returncode", 1)) == 0:
            return path
    raise RuntimeError(f"no successful context compile under {lean_dir}")


def _repaired_lean_attempts(result: dict[str, Any]) -> bool:
    attempts = result.get("attempts") or []
    return bool(
        len(attempts) >= 2
        and not bool(attempts[0].get("compiled"))
        and any(bool(item.get("compiled")) for item in attempts[1:])
        and bool(result.get("compiled"))
        and bool(result.get("audit_passed"))
    )


def _counterexample_refuted(result: dict[str, Any]) -> bool:
    attempts = result.get("attempts") or []
    text = " ".join(
        (
            str(result.get("blocking_reason") or ""),
            str((attempts[0].get("diagnostics") if attempts else "") or ""),
        )
    )
    return "counterexample confirmed" in text


def _ablation_outcome(result: dict[str, Any]) -> str | None:


    attempts = result.get("attempts") or []
    if _repaired_lean_attempts(result):
        return "repaired"
    if not attempts or bool(attempts[0].get("compiled")) or _counterexample_refuted(result):
        return None
    if bool(result.get("compiled")) and bool(result.get("audit_passed")):
        return None
    return "unrepaired"


def build_ablation_cohort(source_root: Path) -> dict[str, Any]:


    source_root = source_root.resolve()
    summary_path = source_root / "summary.json"
    summary_rows = json.loads(summary_path.read_text(encoding="utf-8"))
    anchors: list[tuple[dict[str, Any], Path]] = []
    for row in sorted(summary_rows, key=lambda item: item["record_id"]):
        run = Path(row["run_path"])
        if row.get("status") == "verified":
            verified = [
                path.parent
                for path in sorted((run / "candidates").glob("*/verdict.json"))
                if _read_json(path).get("status") == "verified"
            ]
            if len(verified) != 1:
                raise RuntimeError(
                    f"expected one verified candidate in {run}, found {verified}"
                )
            anchors.append((row, verified[0]))
            continue
        if row.get("status") != "timed_out":
            continue
        for verdict_path in sorted((run / "candidates").glob("*/verdict.json")):
            candidate_dir = verdict_path.parent
            if any(
                _repaired_lean_attempts(_read_json(path))
                for path in candidate_dir.glob("conditions/*/lean/result.json")
            ):
                anchors.append((row, candidate_dir))
    fixtures: list[dict[str, Any]] = []
    for row, candidate_dir in anchors:
        run = Path(row["run_path"])
        for result_path in sorted(candidate_dir.glob("conditions/*/lean/result.json")):
            result = _read_json(result_path)
            outcome = _ablation_outcome(result)
            if outcome is None:
                continue
            condition_dir = result_path.parents[1]
            routing_path = condition_dir / "routing.json"
            attempts = result.get("attempts") or []
            fixtures.append(
                {
                    "fixture_id": (
                        f"{row['record_id']}:c{int(candidate_dir.name):02d}:"
                        f"{condition_dir.name}"
                    ),
                    "record_id": row["record_id"],
                    "run_id": run.name,
                    "condition_id": result.get("condition_id"),
                    "route": (
                        _read_json(routing_path).get("route")
                        if routing_path.is_file()
                        else "direct_lean_query_free"
                    ),
                    "outcome": outcome,
                    "system_status": row.get("status"),
                    "proof_attempts": len(attempts),
                    "repair_rounds": max(0, len(attempts) - 1),
                    "blocking_reason": result.get("blocking_reason"),
                }
            )
    record_ids = sorted({item["record_id"] for item in fixtures})
    repaired = sum(item["outcome"] == "repaired" for item in fixtures)
    unrepaired = sum(item["outcome"] == "unrepaired" for item in fixtures)
    if (len(record_ids), len(fixtures), repaired, unrepaired) != (19, 26, 21, 5):
        raise RuntimeError(
            "ablation cohort drift: expected 19 systems / 26 obligations "
            f"(21 repaired, 5 unrepaired), found {len(record_ids)}/{len(fixtures)} "
            f"({repaired} repaired, {unrepaired} unrepaired)"
        )
    return {
        "schema_version": "dynacert-rq3-ablation-cohort.v1",
        "definition": (
            "LLM-router full run. On each system that repaired at least one Lean "
            "obligation, include every obligation on that candidate whose first proof "
            "attempt failed and which was not refuted by a confirmed counterexample. "
            "This covers obligations the original trace repaired and obligations it "
            "left unrepaired. Direct Lean, Lean rescue after SMT, and query-free Lean "
            "are included because each one entered Lean under the LLM router run."
        ),
        "source_experiment": str(source_root),
        "source_summary_sha256": _file_sha256(summary_path),
        "rq3_repair_set": {
            "candidate_count": len(record_ids),
            "obligation_count": len(fixtures),
            "repaired_obligation_count": repaired,
            "unrepaired_obligation_count": unrepaired,
            "record_ids": record_ids,
        },
        "fixtures": fixtures,
        "created_at_utc": datetime.now(UTC).isoformat(),
    }


def build_cohort(source_root: Path) -> dict[str, Any]:


    source_root = source_root.resolve()
    summary_path = source_root / "summary.json"
    rows = sorted(
        (
            row
            for row in json.loads(summary_path.read_text(encoding="utf-8"))
            if row.get("status") == "verified"
        ),
        key=lambda row: row["record_id"],
    )
    fixtures: list[dict[str, Any]] = []
    lean_obligations = 0
    for row in rows:
        run = Path(row["run_path"])
        verified = [
            path.parent
            for path in sorted((run / "candidates").glob("*/verdict.json"))
            if _read_json(path).get("status") == "verified"
        ]
        if len(verified) != 1:
            raise RuntimeError(f"expected one verified candidate in {run}, found {verified}")
        candidate_dir = verified[0]
        for result_path in sorted(candidate_dir.glob("conditions/*/lean/result.json")):
            lean_obligations += 1
            result = _read_json(result_path)
            if not _repaired_lean_attempts(result):
                continue
            condition_dir = result_path.parents[1]
            routing_path = condition_dir / "routing.json"
            fixtures.append(
                {
                    "fixture_id": (
                        f"{row['record_id']}:c{int(candidate_dir.name):02d}:"
                        f"{condition_dir.name}"
                    ),
                    "record_id": row["record_id"],
                    "run_id": run.name,
                    "condition_id": result.get("condition_id"),
                    "route": (
                        _read_json(routing_path).get("route")
                        if routing_path.is_file()
                        else "direct_lean_query_free"
                    ),
                    "proof_attempts": len(result.get("attempts") or []),
                    "repair_rounds": len(result.get("attempts") or []) - 1,
                }
            )
    record_ids = sorted({item["record_id"] for item in fixtures})
    return {
        "schema_version": COHORT_SCHEMA_VERSION,
        "definition": (
            "Lean obligations of the unique final verified candidate whose first "
            "proof attempt failed and a later attempt compiled and passed audit"
        ),
        "source_experiment": str(source_root),
        "source_summary_sha256": _file_sha256(summary_path),
        "verified_certificates": len(rows),
        "lean_obligations_in_verified_certificates": lean_obligations,
        "rq3_repair_set": {
            "candidate_count": len(record_ids),
            "obligation_count": len(fixtures),
            "record_ids": record_ids,
        },
        "fixtures": fixtures,
        "created_at_utc": datetime.now(UTC).isoformat(),
    }


def discover_fixtures(
    source_root: Path = DEFAULT_SOURCE,
    cohort_path: Path = DEFAULT_COHORT,
    *,
    strict_size: bool = True,
) -> list[FrozenFixture]:
    cohort_payload = _read_json(cohort_path)
    cohort = (
        cohort_payload.get("rq3_repair_set")
        or cohort_payload.get("rq3_repair_cohort")
        or {}
    )
    record_ids = tuple(str(item) for item in cohort.get("record_ids") or ())
    listed_fixture_ids = {
        str(item["fixture_id"])
        for item in cohort_payload.get("fixtures") or []
        if isinstance(item, dict) and item.get("fixture_id")
    }


    listed_run_ids = {
        str(item["fixture_id"]): str(item["run_id"])
        for item in cohort_payload.get("fixtures") or []
        if isinstance(item, dict) and item.get("fixture_id") and item.get("run_id")
    }
    listed_outcomes = {
        str(item["fixture_id"]): str(item.get("outcome") or "repaired")
        for item in cohort_payload.get("fixtures") or []
        if isinstance(item, dict) and item.get("fixture_id")
    }


    bundled_selection = {
        str(item["fixture_id"]): (
            str((item.get("artifacts") or {})["first_compiler_result"]),
            str(item["first_failure_kind"]),
        )
        for item in cohort_payload.get("fixtures") or []
        if isinstance(item, dict)
        and cohort_payload.get("schema_version") == BUNDLE_SCHEMA_VERSION
        and (item.get("artifacts") or {}).get("first_compiler_result")
    }
    start_overrides = dict(cohort_payload.get("repair_start_overrides") or {})
    for item in cohort_payload.get("fixtures") or []:
        if item.get("initial_attempt_index", 0):
            override = dict(start_overrides.get(item["fixture_id"]) or {})
            override["initial_attempt_index"] = item["initial_attempt_index"]
            if item.get("initial_system_prompt") is not None:
                override["initial_system_prompt"] = item["initial_system_prompt"]
            start_overrides[item["fixture_id"]] = override
    fixtures: list[FrozenFixture] = []
    pattern = "runs/*/*/run-*/candidates/*/conditions/*/lean/result.json"
    for result_path in source_root.glob(pattern):
        parts = result_path.relative_to(source_root / "runs").parts
        problem_class, record_id = parts[0], parts[1]
        if record_id not in record_ids:
            continue
        result = _read_json(result_path)
        attempts = result.get("attempts") or []
        lean_dir = result_path.parent
        condition_dir = lean_dir.parent
        candidate_dir = condition_dir.parents[1]
        run_root = candidate_dir.parents[1]
        candidate_index = int(candidate_dir.name)
        fixture_id = f"{record_id}:c{candidate_index:02d}:{condition_dir.name}"
        if listed_fixture_ids and fixture_id not in listed_fixture_ids:
            continue
        if fixture_id in listed_run_ids and run_root.name != listed_run_ids[fixture_id]:
            continue
        outcome = listed_outcomes.get(fixture_id, "repaired")
        repaired = _repaired_lean_attempts(result)
        if outcome == "unrepaired":
            if not attempts or bool(attempts[0].get("compiled")):
                raise RuntimeError(
                    f"{fixture_id}: unrepaired fixture has no failed first attempt"
                )
        elif not repaired:
            continue
        condition = _read_json(condition_dir / "condition.json")
        start_index = (start_overrides.get(fixture_id) or {}).get("initial_attempt_index", 0)
        if outcome == "unrepaired":
            if type(start_index) is not int or not 0 <= start_index < len(attempts):
                raise ValueError(f"{fixture_id}: invalid initial_attempt_index {start_index!r}")
            first_attempt = attempts[start_index]
            if first_attempt.get("compiled"):
                raise ValueError(f"{fixture_id}: selected start must be a failed attempt")
        else:
            if type(start_index) is not int or not 0 <= start_index < len(attempts) - 1:
                raise ValueError(f"{fixture_id}: invalid initial_attempt_index {start_index!r}")
            first_attempt = attempts[start_index]
            if first_attempt.get("compiled") or not any(
                item.get("compiled") for item in attempts[start_index + 1:]
            ):
                raise ValueError(f"{fixture_id}: selected start must fail before a later success")
        first_call = _matching_initial_call(lean_dir, first_attempt)
        failure_kind = (
            "declaration_preflight"
            if first_attempt.get("generated_source_hash") is None
            else "proof_compile"
        )
        if fixture_id in bundled_selection:
            relative, failure_kind = bundled_selection[fixture_id]
            compiler_result = source_root / relative
        else:
            compiler_result = _first_failed_compiler_result(
                lean_dir, first_attempt, first_call
            )
            if compiler_result is None:
                failure_kind = NO_COMPILE_GATE
                compiler_result = _context_compiler_result(lean_dir)
        compiler_payload = _read_json(compiler_result)
        if (
            start_index
            and failure_kind == "declaration_preflight"
            and "helper_lemmas[" in str(first_attempt.get("diagnostics") or "")
        ):
            failure_kind = "helper_compile"
        fixtures.append(
            FrozenFixture(
                fixture_id=fixture_id,
                record_id=record_id,
                problem_class=problem_class,
                candidate_index=candidate_index,
                condition_slug=condition_dir.name,
                condition_id=str(result["condition_id"]),
                condition_kind=str(condition["kind"]),
                candidate_hash=str(result["candidate_hash"]),
                statement_hash=str(result["statement_hash"]),
                run_root=str(run_root.resolve()),
                candidate_path=str((candidate_dir / "candidate.json").resolve()),
                condition_path=str((condition_dir / "condition.json").resolve()),
                lean_dir=str(lean_dir.resolve()),
                lean_result_path=str(result_path.resolve()),
                initial_call_path=str(first_call.resolve()),
                first_compiler_result_path=str(compiler_result.resolve()),
                first_failure_source_hash=str(compiler_payload["source_hash"]),
                first_failure_kind=failure_kind,
                initial_attempt_index=start_index,
                initial_system_prompt=(start_overrides.get(fixture_id) or {}).get("initial_system_prompt"),
            )
        )
    fixtures.sort(key=lambda item: item.fixture_id)
    if listed_fixture_ids and {item.fixture_id for item in fixtures} != listed_fixture_ids:
        missing = sorted(listed_fixture_ids - {item.fixture_id for item in fixtures})
        raise RuntimeError(f"cohort fixtures not found: {missing}")
    if strict_size and EXPECTED_CANDIDATES is not None:
        candidates = {item.record_id for item in fixtures}
        if len(candidates) != EXPECTED_CANDIDATES or len(fixtures) != EXPECTED_OBLIGATIONS:
            raise RuntimeError(
                "frozen cohort drift: expected "
                f"{EXPECTED_CANDIDATES} candidates/{EXPECTED_OBLIGATIONS} obligations, "
                f"found {len(candidates)}/{len(fixtures)}"
            )
    return fixtures


def _fixture_map(source_root: Path, cohort_path: Path) -> dict[str, FrozenFixture]:
    return {
        fixture.fixture_id: fixture
        for fixture in discover_fixtures(source_root, cohort_path)
    }


def _load_frozen_models(fixture: FrozenFixture) -> tuple[Any, Any, Any, Any, Any, dict[str, Any]]:
    if str(FRAMEWORK_ROOT) not in sys.path:
        sys.path.insert(0, str(FRAMEWORK_ROOT))
    if str(CURRENT_ROOT) not in sys.path:
        sys.path.insert(0, str(CURRENT_ROOT))
    from lean_barrier.s01_models import Condition, LeanAgentOutput, LeanAgentStatus, ProblemSpec
    from lean_barrier.s01_models import CandidateSpec
    from lean_barrier.s03_family_expression import FamilyCandidateSpec
    from lean_barrier.s10_family_lean_gen import generate_family_locked_theorem
    from lean_barrier.s10_lean_backend import generate_locked_theorem

    problem_path = Path(fixture.run_root) / "input/problem.json"
    problem = ProblemSpec.model_validate_json(problem_path.read_text(encoding="utf-8"))
    candidate_text = Path(fixture.candidate_path).read_text(encoding="utf-8")
    candidate_payload = json.loads(candidate_text)
    if candidate_payload.get("schema_version") == "lean-barrier.family-candidate.v1":
        candidate = FamilyCandidateSpec.model_validate(candidate_payload, strict=False)
    else:
        candidate = CandidateSpec.model_validate(candidate_payload, strict=False)


    condition = Condition.model_validate_json(
        Path(fixture.condition_path).read_text(encoding="utf-8")
    )
    if condition.condition_id != fixture.condition_id:
        raise RuntimeError(f"{fixture.fixture_id}: frozen condition id mismatch")
    if isinstance(candidate, FamilyCandidateSpec):
        locked = generate_family_locked_theorem(problem, candidate).obligations
    else:
        locked = generate_locked_theorem(problem, candidate, condition)
    if locked.candidate_hash != fixture.candidate_hash:
        raise RuntimeError(f"{fixture.fixture_id}: candidate hash drift")
    if locked.statement_hash != fixture.statement_hash:
        raise RuntimeError(f"{fixture.fixture_id}: locked statement hash drift")
    result = _read_json(Path(fixture.lean_result_path))
    first_attempt = result["attempts"][fixture.initial_attempt_index]
    proof_body = str(first_attempt.get("proof_body") or "")


    if proof_body.strip():
        frozen = LeanAgentOutput(
            status=LeanAgentStatus.CANDIDATE_PROOF,
            helper_lemmas=tuple(first_attempt.get("helper_lemmas") or ()),
            proof_body=proof_body,
            blocking_reason=None,
            counterexample=None,
        )
    else:
        frozen = LeanAgentOutput(
            status=LeanAgentStatus.CANNOT_COMPLETE,
            helper_lemmas=tuple(first_attempt.get("helper_lemmas") or ()),
            proof_body="",
            blocking_reason=str(first_attempt.get("diagnostics") or "frozen attempt had no proof body"),
            counterexample=None,
        )
    call = _read_json(Path(fixture.initial_call_path))
    response = _extract_json_object(str(call.get("response") or ""))
    if response is None or _submitted_pair(response) != _submitted_pair(first_attempt):
        raise RuntimeError(f"{fixture.fixture_id}: frozen initial response mismatch")
    return problem, candidate, condition, locked, frozen, call


def validate_fixture(fixture: FrozenFixture) -> dict[str, Any]:
    _, _, _, locked, frozen, call = _load_frozen_models(fixture)
    compiler = _read_json(Path(fixture.first_compiler_result_path))
    if fixture.first_failure_kind != NO_COMPILE_GATE and int(compiler.get("returncode", 0)) == 0:
        raise RuntimeError(f"{fixture.fixture_id}: frozen first compiler result is not a failure")
    return {
        "fixture_id": fixture.fixture_id,
        "record_id": fixture.record_id,
        "condition_kind": fixture.condition_kind,
        "failure_kind": fixture.first_failure_kind,
        "candidate_hash": locked.candidate_hash,
        "statement_hash": locked.statement_hash,
        "initial_proof_lines": len(frozen.proof_body.splitlines()),
        "original_model_id": call.get("model_id"),
        "first_failure_source_hash": fixture.first_failure_source_hash,
        "initial_attempt_index": fixture.initial_attempt_index,
        "original_proof_version": fixture.initial_attempt_index + 1,
    }


def _raw_compiler_output(payload: dict[str, Any]) -> str:
    return f"{payload.get('stdout') or ''}\n{payload.get('stderr') or ''}".strip()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_relative(path: Path, source_root: Path) -> Path:
    source = path.resolve()
    root = source_root.resolve()
    try:
        relative = source.relative_to(root)
    except ValueError as error:
        raise RuntimeError(f"fixture artifact escaped source root: {source}") from error
    if not source.is_file():
        raise FileNotFoundError(source)
    return relative


def _sanitized_initial_call(path: Path) -> dict[str, Any]:
    raw = _read_json(path)
    sanitized = {key: raw[key] for key in INITIAL_CALL_FIELDS if key in raw}
    parameters = raw.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ValueError(f"expected parameters object in {path}")
    sanitized["parameters"] = {
        key: parameters[key]
        for key in INITIAL_CALL_PARAMETER_FIELDS
        if key in parameters
    }
    return sanitized


def _sanitized_compiler_result(path: Path) -> dict[str, Any]:
    raw = _read_json(path)
    return {key: raw[key] for key in COMPILER_RESULT_FIELDS if key in raw}


def _secret_scan(root: Path) -> dict[str, Any]:


    suspicious_keys = {
        "api_key",
        "apikey",
        "authorization",
        "headers",
        "credentials",
        "access_token",
        "secret_key",
        "password",
    }
    findings: list[dict[str, str]] = []
    files_scanned = 0

    def walk_keys(value: Any, json_path: str = "$") -> Iterable[tuple[str, str]]:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                normalized = key_text.lower().replace("-", "_")
                if normalized in suspicious_keys:
                    yield json_path, key_text
                yield from walk_keys(child, f"{json_path}.{key_text}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk_keys(child, f"{json_path}[{index}]")

    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        files_scanned += 1
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append({"path": relative, "kind": "non-utf8-file"})
            continue
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append({"path": relative, "kind": name})
        if path.suffix == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                findings.append({"path": relative, "kind": "invalid-json"})
                continue
            for json_path, key in walk_keys(payload):
                findings.append(
                    {
                        "path": relative,
                        "kind": "suspicious-json-key",
                        "location": json_path,
                        "key": key,
                    }
                )
    return {
        "files_scanned": files_scanned,
        "pattern_names": [name for name, _ in SECRET_PATTERNS],
        "finding_count": len(findings),
        "findings": findings,
    }


def _bundle_artifact_paths(
    fixture: FrozenFixture, source_root: Path
) -> dict[str, str]:
    compiler_result = Path(fixture.first_compiler_result_path)
    paths = {
        "problem": Path(fixture.run_root) / "input/problem.json",
        "candidate": Path(fixture.candidate_path),
        "condition": Path(fixture.condition_path),
        "lean_result": Path(fixture.lean_result_path),
        "initial_call": Path(fixture.initial_call_path),
        "first_compiler_result": compiler_result,
        "first_compiler_source": compiler_result.with_name("source.lean"),
        "locked_source": Path(fixture.lean_dir) / "locked_source.lean",
        "locked_statement": Path(fixture.lean_dir) / "locked_statement.lean",
        "lean_status": Path(fixture.lean_dir) / "status.json",
    }
    return {
        name: _source_relative(path, source_root).as_posix()
        for name, path in paths.items()
    }


def validate_frozen_bundle(
    source_root: Path = DEFAULT_SOURCE,
    manifest_path: Path = DEFAULT_COHORT,
) -> dict[str, Any]:


    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ValueError(
            f"not an RQ3 frozen input bundle manifest: {manifest_path}"
        )
    entries = manifest.get("files") or []
    if not isinstance(entries, list):
        raise ValueError("bundle manifest files must be a list")
    expected: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    root = source_root.resolve()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("bundle manifest file entry must be an object")
        relative = Path(str(entry.get("path") or ""))
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError(f"unsafe bundle file path: {relative}")
        relative_text = relative.as_posix()
        if relative_text in expected:
            raise ValueError(f"duplicate bundle file entry: {relative_text}")
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise FileNotFoundError(f"missing bundle file: {relative_text}")
        observed_size = path.stat().st_size
        observed_hash = _file_sha256(path)
        if observed_size != int(entry.get("bytes", -1)):
            raise RuntimeError(f"bundle size mismatch: {relative_text}")
        if observed_hash != entry.get("sha256"):
            raise RuntimeError(f"bundle SHA-256 mismatch: {relative_text}")
        expected[relative_text] = entry
        total_bytes += observed_size

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.resolve() != manifest_path.resolve()
    }
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise RuntimeError(
            f"bundle inventory mismatch; missing={missing}, extra={extra}"
        )
    if len(expected) != int(manifest.get("payload_file_count", -1)):
        raise RuntimeError("bundle payload file-count mismatch")
    if (
        EXPECTED_BUNDLE_PAYLOAD_FILES is not None
        and len(expected) != EXPECTED_BUNDLE_PAYLOAD_FILES
    ):
        raise RuntimeError(
            "bundle payload drift: expected "
            f"{EXPECTED_BUNDLE_PAYLOAD_FILES} files, found {len(expected)}"
        )
    if total_bytes != int(manifest.get("payload_bytes", -1)):
        raise RuntimeError("bundle payload byte-count mismatch")

    cohort = manifest.get("rq3_repair_set") or {}
    record_ids = tuple(str(item) for item in cohort.get("record_ids") or ())
    manifest_fixtures = manifest.get("fixtures") or []
    if not isinstance(manifest_fixtures, list):
        raise ValueError("bundle manifest fixtures must be a list")
    if len(record_ids) != len(set(record_ids)):
        raise RuntimeError("bundle repair-set record_ids are not unique")
    if len(record_ids) != int(cohort.get("candidate_count", -1)):
        raise RuntimeError("bundle candidate-count mismatch")
    if len(manifest_fixtures) != int(cohort.get("obligation_count", -1)):
        raise RuntimeError("bundle obligation-count mismatch")
    if EXPECTED_CANDIDATES is not None and (
        len(record_ids) != EXPECTED_CANDIDATES
        or len(manifest_fixtures) != EXPECTED_OBLIGATIONS
    ):
        raise RuntimeError(
            "bundle cohort drift: expected "
            f"{EXPECTED_CANDIDATES} candidates/{EXPECTED_OBLIGATIONS} obligations"
        )

    discovered = discover_fixtures(root, manifest_path)
    discovered_by_id = {fixture.fixture_id: fixture for fixture in discovered}
    manifest_ids = [str(fixture.get("fixture_id") or "") for fixture in manifest_fixtures]
    if len(manifest_ids) != len(set(manifest_ids)):
        raise RuntimeError("bundle manifest fixture IDs are not unique")
    if set(manifest_ids) != set(discovered_by_id):
        raise RuntimeError("bundle manifest fixture mapping differs from payload")

    required_artifacts = {
        "problem",
        "candidate",
        "condition",
        "lean_result",
        "initial_call",
        "first_compiler_result",
        "first_compiler_source",
        "locked_source",
        "locked_statement",
        "lean_status",
    }
    for fixture in manifest_fixtures:
        fixture_id = str(fixture["fixture_id"])
        artifacts = fixture.get("artifacts") or {}
        if set(artifacts) != required_artifacts:
            raise RuntimeError(
                f"bundle artifact mapping is incomplete for {fixture_id}"
            )
        expected_artifacts = _bundle_artifact_paths(
            discovered_by_id[fixture_id], root
        )
        if artifacts != expected_artifacts:
            raise RuntimeError(
                f"bundle artifact mapping drift for {fixture_id}"
            )
        if any(str(path) not in expected for path in artifacts.values()):
            raise RuntimeError(
                f"bundle artifact mapping references unlisted file for {fixture_id}"
            )
        for field in (
            "record_id",
            "problem_class",
            "candidate_index",
            "condition_slug",
            "condition_id",
            "condition_kind",
            "candidate_hash",
            "statement_hash",
            "first_failure_kind",
            "first_failure_source_hash",
        ):
            if fixture.get(field) != getattr(discovered_by_id[fixture_id], field):
                raise RuntimeError(
                    f"bundle fixture metadata drift for {fixture_id}: {field}"
                )
        if fixture.get("initial_attempt_index", 0) != discovered_by_id[fixture_id].initial_attempt_index:
            raise RuntimeError(f"bundle fixture initial-attempt drift for {fixture_id}")
        if fixture.get("initial_system_prompt") != discovered_by_id[fixture_id].initial_system_prompt:
            raise RuntimeError(f"bundle fixture initial-prompt drift for {fixture_id}")
        call = _read_json(root / artifacts["initial_call"])
        unexpected_call = set(call) - set(INITIAL_CALL_FIELDS)
        parameters = call.get("parameters") or {}
        unexpected_parameters = set(parameters) - set(INITIAL_CALL_PARAMETER_FIELDS)
        if unexpected_call or unexpected_parameters or "call_info" in call:
            raise RuntimeError(
                "unsanitized initial call "
                f"{artifacts['initial_call']}: fields={sorted(unexpected_call)}, "
                f"parameters={sorted(unexpected_parameters)}"
            )
        compiler = _read_json(root / artifacts["first_compiler_result"])
        unexpected_compiler = set(compiler) - set(COMPILER_RESULT_FIELDS)
        if unexpected_compiler:
            raise RuntimeError(
                f"unsanitized compiler result {artifacts['first_compiler_result']}: "
                f"fields={sorted(unexpected_compiler)}"
            )
        source = (root / artifacts["first_compiler_source"]).read_text(
            encoding="utf-8"
        )
        source_hash = hashlib.sha256(
            json.dumps(
                source,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if source_hash != compiler.get("source_hash"):
            raise RuntimeError(
                f"compiler source hash mismatch: {artifacts['first_compiler_source']}"
            )

    secret_scan = _secret_scan(root)
    if secret_scan["finding_count"]:
        raise RuntimeError(
            "secret scan rejected frozen bundle: "
            + json.dumps(secret_scan["findings"], ensure_ascii=False)
        )
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "payload_file_count": len(expected),
        "payload_bytes": total_bytes,
        "manifest_sha256": _file_sha256(manifest_path),
        "secret_scan": secret_scan,
    }


def export_frozen_bundle(
    source_root: Path = RAW_RQ1_SOURCE,
    cohort_path: Path = RAW_RQ3_COHORT,
    destination: Path = DEFAULT_SOURCE,
    *,
    force: bool = False,
) -> dict[str, Any]:


    source_root = source_root.resolve()
    cohort_path = cohort_path.resolve()
    destination = destination.resolve()
    fixtures = discover_fixtures(source_root, cohort_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        raise FileExistsError(
            f"bundle destination already exists (use --force): {destination}"
        )
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-export-", dir=destination.parent)
    )
    inventory_sources: dict[str, tuple[Path, str]] = {}
    fixture_manifest: list[dict[str, Any]] = []

    def register(path: Path, kind: str) -> str:
        relative = _source_relative(path, source_root).as_posix()
        previous = inventory_sources.get(relative)
        if previous is not None and previous[0].resolve() != path.resolve():
            raise RuntimeError(f"conflicting bundle source for {relative}")
        inventory_sources[relative] = (path.resolve(), kind)
        return relative

    try:
        for fixture in fixtures:
            paths = _bundle_artifact_paths(fixture, source_root)
            compiler_result = Path(fixture.first_compiler_result_path)
            originals = {
                "problem": Path(fixture.run_root) / "input/problem.json",
                "candidate": Path(fixture.candidate_path),
                "condition": Path(fixture.condition_path),
                "lean_result": Path(fixture.lean_result_path),
                "initial_call": Path(fixture.initial_call_path),
                "first_compiler_result": compiler_result,
                "first_compiler_source": compiler_result.with_name("source.lean"),
                "locked_source": Path(fixture.lean_dir) / "locked_source.lean",
                "locked_statement": Path(fixture.lean_dir) / "locked_statement.lean",
                "lean_status": Path(fixture.lean_dir) / "status.json",
            }
            for name, path in originals.items():
                if register(path, name) != paths[name]:
                    raise RuntimeError(f"relative artifact path drift for {name}")
            fixture_manifest.append(
                {
                    "fixture_id": fixture.fixture_id,
                    "record_id": fixture.record_id,
                    "problem_class": fixture.problem_class,
                    "candidate_index": fixture.candidate_index,
                    "condition_slug": fixture.condition_slug,
                    "condition_id": fixture.condition_id,
                    "condition_kind": fixture.condition_kind,
                    "candidate_hash": fixture.candidate_hash,
                    "statement_hash": fixture.statement_hash,
                    "first_failure_kind": fixture.first_failure_kind,
                    "first_failure_source_hash": fixture.first_failure_source_hash,
                    "initial_attempt_index": fixture.initial_attempt_index,
                    "initial_system_prompt": fixture.initial_system_prompt,
                    "outcome": next((x.get("outcome", "repaired") for x in _read_json(cohort_path).get("fixtures", []) if x["fixture_id"] == fixture.fixture_id), "repaired"),
                    "artifacts": paths,
                }
            )

        file_entries: list[dict[str, Any]] = []
        for relative, (source, kind) in sorted(inventory_sources.items()):
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source_hash = _file_sha256(source)
            if kind == "initial_call":
                _atomic_json(target, _sanitized_initial_call(source))
            elif kind == "first_compiler_result":
                _atomic_json(target, _sanitized_compiler_result(source))
            else:
                shutil.copyfile(source, target)
            file_entries.append(
                {
                    "path": relative,
                    "kind": kind,
                    "bytes": target.stat().st_size,
                    "sha256": _file_sha256(target),
                    "source_sha256": source_hash,
                }
            )

        scan = _secret_scan(temporary)
        if scan["finding_count"]:
            raise RuntimeError(
                "secret scan rejected export: "
                + json.dumps(scan["findings"], ensure_ascii=False)
            )
        experiment_path = source_root / "experiment.json"
        experiment = _read_json(experiment_path)
        record_ids = sorted({fixture.record_id for fixture in fixtures})
        manifest = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "description": (
                "Sanitized, self-contained first-failure inputs for the RQ3 "
                "Lean proof-repair ablation."
            ),
            "source": {
                "experiment_id": experiment.get("experiment_id"),
                "model": experiment.get("model"),
                "provider": experiment.get("provider"),
                "raw_experiment_sha256": _file_sha256(experiment_path),
                "raw_cohort_sha256": _file_sha256(cohort_path),
            },
            "repair_start_overrides": _read_json(cohort_path).get("repair_start_overrides") or {},
            "rq3_repair_set": {
                "candidate_count": len(record_ids),
                "obligation_count": len(fixtures),
                "record_ids": record_ids,
            },
            "sanitization": {
                "initial_call_fields": list(INITIAL_CALL_FIELDS),
                "initial_call_parameter_fields": list(
                    INITIAL_CALL_PARAMETER_FIELDS
                ),
                "compiler_result_fields": list(COMPILER_RESULT_FIELDS),
                "excluded_initial_call_content": [
                    "call_info",
                    "reasoning_content",
                    "request/response headers",
                    "credentials",
                ],
                "lean_result_policy": "complete result retained; harness reads the explicitly selected initial_attempt_index (default 0)",
            },
            "fixtures": fixture_manifest,
            "payload_file_count": len(file_entries),
            "payload_bytes": sum(int(entry["bytes"]) for entry in file_entries),
            "files": file_entries,
            "secret_scan": {
                "files_scanned": scan["files_scanned"],
                "pattern_names": scan["pattern_names"],
                "finding_count": 0,
            },
        }
        _atomic_json(temporary / "manifest.json", manifest)


        validated = validate_frozen_bundle(
            temporary, temporary / "manifest.json"
        )

        backup: Path | None = None
        if destination.exists():
            backup = destination.with_name(
                destination.name
                + ".replaced-"
                + datetime.now(UTC).strftime("%Y%m%dT%H%M%S-%fZ")
            )
            destination.replace(backup)
        try:
            temporary.replace(destination)
        except Exception:
            if backup is not None and not destination.exists():
                backup.replace(destination)
            raise
        validated.update(
            {
                "destination": str(destination),
                "candidate_count": len(record_ids),
                "obligation_count": len(fixtures),
                "replaced_bundle": str(backup) if backup is not None else None,
            }
        )
        return validated
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def frozen_source_signature(
    fixtures: Sequence[FrozenFixture], source_root: Path, cohort_path: Path
) -> dict[str, Any]:
    fixture_hashes: dict[str, str] = {}
    for fixture in fixtures:
        paths = (
            Path(fixture.run_root) / "input/problem.json",
            Path(fixture.candidate_path),
            Path(fixture.condition_path),
            Path(fixture.lean_result_path),
            Path(fixture.initial_call_path),
            Path(fixture.first_compiler_result_path),
        )


        parts = [
            (
                _source_relative(path, source_root).as_posix(),
                _file_sha256(path),
            )
            for path in paths
        ]
        encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"))
        fixture_hashes[fixture.fixture_id] = hashlib.sha256(
            encoded.encode("utf-8")
        ).hexdigest()
    experiment_path = source_root / "experiment.json"
    return {
        "source_root": str(source_root.resolve()),
        "cohort_path": str(cohort_path.resolve()),
        "cohort_sha256": _file_sha256(cohort_path),
        "experiment_sha256": (
            _file_sha256(experiment_path) if experiment_path.is_file() else None
        ),
        "fixture_sha256": fixture_hashes,
    }


def _job_path(output_root: Path, fixture: FrozenFixture, arm: str, repeat: int) -> Path:
    return output_root / "jobs" / fixture.job_component / arm / f"repeat-{repeat:03d}"


def _call_metrics(agent_dir: Path) -> dict[str, Any]:
    responses = attempts = tokens = reasoning_tokens = 0
    llm_seconds = 0.0
    for path in sorted(agent_dir.glob("*-lean.json")):
        artifact = _read_json(path)
        info = artifact.get("call_info") or {}
        usage = info.get("usage") or {}
        responses += 1
        attempts += int(info.get("attempts", 1))
        tokens += int(usage.get("total_tokens", 0))
        details = usage.get("completion_tokens_details") or {}
        reasoning_tokens += int(details.get("reasoning_tokens", 0))
        llm_seconds += float(info.get("duration_seconds", 0.0))
    return {
        "recorded_responses": responses,
        "transport_attempts": attempts,
        "tokens": tokens,
        "reasoning_tokens": reasoning_tokens,
        "llm_seconds": round(llm_seconds, 6),
    }


FAILURE_ONLY_SIGNAL = "Lean compilation failed."
_UNKNOWN_DECL = re.compile(r"[Uu]nknown (?:constant|identifier)\s+`([^`\s]+)`")


def _unknown_declarations(text: str) -> frozenset[str]:
    return frozenset(_UNKNOWN_DECL.findall(text or ""))


def _first_unknown_probe(compiler: Any) -> tuple[frozenset[str], str]:


    for call in compiler.calls:
        if call.get("phase") != "frozen_replay_setup":
            continue
        text = f"{call.get('stdout') or ''}\n{call.get('stderr') or ''}".strip()
        found = _unknown_declarations(text)
        if found:
            return found, text
    return frozenset(), ""


def _first_probe_unknowns(compiler: Any) -> frozenset[str]:


    return _first_unknown_probe(compiler)[0]


def feedback_boundary(arm: str, raw: str, processed: str) -> tuple[str, str]:


    if arm == "failure_only":
        return "failure_signal", FAILURE_ONLY_SIGNAL
    if arm == "verbatim_diagnostics":
        return "verbatim_compiler_output", raw
    if arm == "current_guided":
        return "processed_diagnostics", processed
    raise ValueError(f"feedback boundary is undefined for {arm!r}")


class _CapturingReplayingCompiler:


    def __init__(
        self,
        delegate: Any,
        store: Any,
        replay: dict[str, Any],
    ) -> None:
        self.delegate = delegate
        self.store = store
        self.formal = delegate.formal
        self.lean_project = delegate.lean_project
        self.replay = replay
        self.replayed = False
        self.repair_phase = False
        self.calls: list[dict[str, Any]] = []
        self.last_raw = ""
        self.last_failure_raw = ""
        self.last_relevant_raw = ""

    @property
    def module_cache_root(self) -> Path:
        return self.delegate.module_cache_root

    def begin_repair(self) -> None:
        self.repair_phase = True

    def _invalidate_repair_module(self, module_name: str) -> list[str]:
        if not re.fullmatch(
            r"LeanBarrier\.GeneratedCache\.(?:Context|Helper)_[0-9a-f]{64}",
            module_name,
        ):
            raise RuntimeError(
                f"refusing to invalidate non-generated Lean module {module_name!r}"
            )
        relative = Path(*module_name.split("."))
        cache_root = self.delegate.module_cache_root.resolve()
        object_root = (
            self.delegate.lean_project / ".lake/build/lib/lean"
        ).resolve()
        paths = (
            (cache_root / relative).with_suffix(".lean").resolve(),
            (cache_root / relative).with_suffix(".audit").resolve(),
            (object_root / relative).with_suffix(".olean").resolve(),
        )
        if not all(
            path.is_relative_to(cache_root) or path.is_relative_to(object_root)
            for path in paths
        ):
            raise RuntimeError("generated Lean cache path escaped its validated root")
        removed: list[str] = []
        for path in paths:
            if path.is_file():
                path.unlink()
                removed.append(str(path))
        return removed

    def _run(
        self,
        kind: str,
        source: str,
        timeout_seconds: float,
        module_name: str | None = None,
    ) -> Any:
        from lean_barrier.s02_expressions import content_hash
        from lean_barrier.s13_runtime import ExecutionResult

        source_hash = content_hash(source)
        replayed = False
        removed_cache_paths: list[str] = []
        if not self.replayed and source_hash == str(self.replay["source_hash"]):
            result = ExecutionResult(
                int(self.replay["returncode"]),
                str(self.replay.get("stdout") or ""),
                str(self.replay.get("stderr") or ""),
                0.0,
                bool(self.replay.get("timed_out", False)),
            )
            self.replayed = replayed = True
        elif kind == "module":
            if self.repair_phase:
                removed_cache_paths = self._invalidate_repair_module(str(module_name))
            result = self.delegate.compile_module(
                str(module_name),
                source,
                timeout_seconds=timeout_seconds,
            )
        else:
            result = self.delegate.compile(source, timeout_seconds=timeout_seconds)
        raw = f"{result.stdout}\n{result.stderr}".strip()
        self.last_raw = raw
        if int(result.returncode) != 0 or bool(result.timed_out):
            self.last_failure_raw = raw
            self.last_relevant_raw = raw
        elif "#print axioms" in source:


            self.last_relevant_raw = raw
        index = len(self.calls)
        entry = {
            "index": index,
            "kind": kind,
            "module_name": module_name,
            "source_hash": source_hash,
            "invalidated_repair_cache_paths": removed_cache_paths,
            "returncode": int(result.returncode),
            "timed_out": bool(result.timed_out),
            "duration_seconds": float(result.duration_seconds),
            "phase": "repair" if self.repair_phase else "frozen_replay_setup",
            "replayed_rq1_first_failure": replayed,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        self.calls.append(entry)
        self.store.write_text("compiler", f"{index:04d}-source", source, ".lean")
        self.store.write_json("compiler", f"{index:04d}-result", entry)
        return result

    def compile(self, source: str, *, timeout_seconds: float) -> Any:
        return self._run("proof_or_probe", source, timeout_seconds)

    def compile_module(
        self, module_name: str, source: str, *, timeout_seconds: float
    ) -> Any:
        return self._run("module", source, timeout_seconds, module_name)


def _execute_trajectory(
    fixture: FrozenFixture,
    arm: str,
    repeat: int,
    timeout_seconds: float,
    max_repair_calls: int | None,
    store: Any,
) -> dict[str, Any]:
    if arm not in ALL_ARMS:
        raise ValueError(f"unsupported arm: {arm}")
    if max_repair_calls is not None and max_repair_calls < 1:
        raise ValueError("max_repair_calls must be positive when provided")
    (
        problem,
        candidate,
        condition,
        locked,
        frozen,
        initial_call,
    ) = _load_frozen_models(fixture)

    import pipeline_app
    from lean_barrier.s01_models import LeanAgentOutput, LeanAgentStatus, LeanLocalPatch
    from lean_barrier.s05_prompts import lean_followup, lean_local_repair_prompt
    from lean_barrier.s06_agents import JSON_TURN
    from lean_barrier.s10_lean_backend import DevelopmentLeanCompiler, LeanProofRunner
    from lean_barrier.s10_local_repair import (
        apply_local_patch,
        localize_lean_error,
        targets_replacement_span,
    )
    from lean_barrier.s13_runtime import RunDeadline

    first_result = _read_json(Path(fixture.lean_result_path))
    selected_attempt = first_result["attempts"][fixture.initial_attempt_index]
    frozen_processed = str(selected_attempt.get("diagnostics") or "")
    from lean_barrier.s10_lean_runner import agent_repair_feedback

    frozen_compiler = _read_json(Path(fixture.first_compiler_result_path))


    gate_failure = fixture.first_failure_kind == NO_COMPILE_GATE
    frozen_raw = "" if gate_failure else _raw_compiler_output(frozen_compiler)
    native_feedback = NATIVE_REPAIR_FEEDBACK[arm]
    deadlines = deadline_spec(timeout_seconds)
    store.write_json("frozen", "initial-call", initial_call)
    store.write_json("frozen", "first-attempt", selected_attempt)
    store.write_json("frozen", "first-compiler-result", frozen_compiler)
    store.write_text("frozen", "locked-definitions", locked.definitions, ".lean")
    store.write_text("frozen", "locked-statement", locked.statement, ".lean")
    expected_parameters = initial_call.get("parameters") or {}
    runtime_signature = {
        "provider": pipeline_app.PROVIDER,
        "model": pipeline_app.MODEL,
        "thinking": pipeline_app.THINKING,
        "max_tokens": pipeline_app.MAX_TOKENS,
        "reasoning_effort": pipeline_app.REASONING_EFFORT,
    }
    expected_signature = {
        "provider": expected_parameters.get("provider"),
        "model": initial_call.get("model_id"),
        "thinking": expected_parameters.get("thinking"),
        "max_tokens": expected_parameters.get("max_tokens"),


        "reasoning_effort": "high",
    }
    if runtime_signature != expected_signature:
        raise RuntimeError(
            "active model configuration does not match the frozen RQ1 Lean calls: "
            f"expected {expected_signature}, got {runtime_signature}"
        )
    base_compiler = DevelopmentLeanCompiler(CURRENT_ROOT / "formalization/lean")
    compiler = _CapturingReplayingCompiler(
        base_compiler,
        store,
        {"source_hash": "<no-compile-gate>"} if gate_failure else frozen_compiler,
    )


    class _ContinueFrozenPreflightTimeout(LeanProofRunner):


        def _preflight_real_names(self, output: Any, *, timeout_seconds: float) -> Any:
            result = super()._preflight_real_names(output, timeout_seconds=timeout_seconds)
            if result is None or "declaration preflight timed out" not in frozen_processed:
                return result
            text, terminal = result
            if terminal and "declaration preflight timed out" in text:
                return text, False
            return result

    runner_cls = (
        _ContinueFrozenPreflightTimeout
        if "declaration preflight timed out" in frozen_processed
        else LeanProofRunner
    )
    proof_runner = runner_cls(
        compiler, repair_feedback=native_feedback
    )
    definitions_ok, definition_diagnostics = proof_runner.preflight_locked_definitions(
        locked
    )
    if not definitions_ok:
        raise RuntimeError(
            "locked definitions failed setup preflight: " + definition_diagnostics
        )


    trajectory_deadline = RunDeadline(deadlines["trajectory_deadline_seconds"])
    proof_runner.deadline = trajectory_deadline
    roles = pipeline_app.make_roles(store, deadline=trajectory_deadline)
    suite = roles.lean_prover.__self__
    model_runner = suite.lean_runner.fresh()
    model_runner.system_prompt = fixture.initial_system_prompt or str(initial_call["prompt"])
    store.write_text("frozen", "initial-system-prompt", model_runner.system_prompt, ".txt")
    model_runner.conversation = [
        {"role": "user", "content": JSON_TURN},
        {"role": "assistant", "content": str(initial_call["response"])},
    ]

    class BudgetedTransport:


        def __init__(self, delegate: Any) -> None:
            self.delegate = delegate
            self.calls = 0

        def __call__(self, **kwargs: Any) -> Any:
            if max_repair_calls is not None and self.calls >= max_repair_calls:
                raise RuntimeError("frozen RQ3 post-failure model-call budget exhausted")
            self.calls += 1
            return self.delegate(**kwargs)

    transport = BudgetedTransport(model_runner._transport)
    model_runner._transport = transport
    model_runner._repair_transport = transport

    state: dict[str, Any] = {
        "repair_turns": 0,
        "repair_started": None,
        "current": frozen,
        "patch_base": None,
        "patch_request": None,
        "patch_line_count": 0,
        "patch_pending": False,
        "local_patch_calls": 0,
        "events": [],
        "gate_reproduced": False,
        "preflight_reproduced": False,
    }

    def prove(round_index: int, previous: str, diagnostics: str) -> Any:
        if round_index == 1:
            return frozen
        if gate_failure and not state["gate_reproduced"]:
            expected = agent_repair_feedback(native_feedback, processed=frozen_processed)
            if diagnostics != expected:
                raise RuntimeError(
                    "frozen gate failure was not reproduced by the current runner; "
                    "refusing a paid repair call"
                )
            state["gate_reproduced"] = True


        if (
            fixture.first_failure_kind == "declaration_preflight"
            and not compiler.replayed
            and not state["preflight_reproduced"]
        ):
            frozen_unknown = _unknown_declarations(frozen_processed) | _unknown_declarations(
                frozen_raw
            )
            live_unknown, live_raw = _first_unknown_probe(compiler)
            timeout_frozen = "declaration preflight timed out" in frozen_processed
            timeout_feedback = agent_repair_feedback(
                native_feedback, processed=frozen_processed
            )
            if timeout_frozen and diagnostics == timeout_feedback:
                state["preflight_reproduced"] = True
            elif frozen_unknown and live_unknown == frozen_unknown:
                state["preflight_reproduced"] = True
            elif timeout_frozen:


                state["preflight_reproduced"] = True
                if native_feedback == "verbatim" and live_raw:
                    state["first_repair_feedback"] = live_raw
                else:
                    state["first_repair_feedback"] = diagnostics
            else:
                raise RuntimeError(
                    "frozen declaration preflight was not reproduced; "
                    "refusing a paid repair call"
                )
        if (
            not gate_failure
            and fixture.first_failure_kind != "declaration_preflight"
            and not compiler.replayed
        ):
            raise RuntimeError(
                "frozen first-failure source did not match current generated source; "
                "refusing a paid repair call"
            )
        if max_repair_calls is not None and transport.calls >= max_repair_calls:
            return LeanAgentOutput(
                status=LeanAgentStatus.CANNOT_COMPLETE,
                helper_lemmas=(),
                proof_body=str(state["current"].proof_body),
                blocking_reason="frozen RQ3 repair-call budget exhausted",
                counterexample=None,
            )
        if state["repair_started"] is None:
            state["repair_started"] = time.monotonic()
            compiler.begin_repair()
        state["repair_turns"] += 1
        repair_index = int(state["repair_turns"])
        processed = frozen_processed if repair_index == 1 else diagnostics
        raw = frozen_raw if repair_index == 1 else (compiler.last_relevant_raw or diagnostics)
        action = "full_regeneration"
        prompt_kind = arm
        fallback_note = ""

        if arm == "local_patch":
            allow_patch = True
            if state["patch_pending"]:
                next_request = localize_lean_error(
                    state["current"], processed, locked.statement
                )
                same_target = bool(
                    state["patch_request"] is not None
                    and targets_replacement_span(
                        state["patch_request"],
                        next_request,
                        state["patch_line_count"],
                    )
                )
                if same_target:
                    state["current"] = state["patch_base"]
                    fallback_note = (
                        "\n\nThe transactional patch did not remove the selected source "
                        "error. The framework rolled back to the pre-patch proof."
                    )
                    allow_patch = False
                else:
                    fallback_note = (
                        "\n\nLean no longer reports the selected source error, so the "
                        "transactional patch was committed. Diagnostics are for a later error."
                    )
                state["patch_base"] = None
                state["patch_request"] = None
                state["patch_line_count"] = 0
                state["patch_pending"] = False
            if state["local_patch_calls"] < 2 and allow_patch:
                request = localize_lean_error(
                    state["current"], processed, locked.statement
                )
                if request is not None:
                    action = "local_patch"
                    prompt_kind = "structured_local_patch"
                    state["local_patch_calls"] += 1
                    patch = model_runner.run(lean_local_repair_prompt(request), LeanLocalPatch)
                    patched = apply_local_patch(state["current"], request, patch)
                    if patched is not None:
                        state["patch_base"] = state["current"]
                        state["patch_request"] = request
                        state["patch_line_count"] = len(patch.replacement_code.splitlines())
                        state["patch_pending"] = True
                        state["current"] = patched
                        state["events"].append(
                            {"repair_turn": repair_index, "action": action, "prompt": prompt_kind}
                        )
                        return patched
                    fallback_note += (
                        "\n\nThe constrained local repair was declined or invalid; use "
                        "the full-proof repair path."
                    )

        if arm in DEFAULT_ARMS and repair_index == 1:


            boundary_kind = feedback_boundary(arm, raw, processed)[0]
            if state.get("first_repair_feedback") is not None:
                boundary_value = state["first_repair_feedback"]
            else:
                boundary_value = agent_repair_feedback(
                    native_feedback, processed=processed, raw=raw
                )
        elif arm in DEFAULT_ARMS:

            boundary_kind = feedback_boundary(arm, "", "")[0]
            boundary_value = diagnostics
        else:
            boundary_kind, boundary_value = "processed_diagnostics", processed
        prompt_kind = boundary_kind
        prompt = lean_followup(
            candidate_hash=locked.candidate_hash,
            condition=condition,
            locked_definitions=locked.definitions,
            locked_statement=locked.statement,
            previous_proof_body=str(state["current"].proof_body),
            compiler_diagnostics=boundary_value + fallback_note,
            mode="direct_lean",
        )
        output = model_runner.run(prompt, LeanAgentOutput)
        if output.status == LeanAgentStatus.CANDIDATE_PROOF:
            state["current"] = output
        state["events"].append(
            {"repair_turn": repair_index, "action": action, "prompt": prompt_kind}
        )
        return output

    started = time.monotonic()
    result = proof_runner.run(fixture.condition_id, locked, prove)
    total_elapsed = time.monotonic() - started
    reproduced = (
        state["gate_reproduced"]
        if gate_failure
        else compiler.replayed or state["preflight_reproduced"]
    )
    if not reproduced:
        raise RuntimeError("RQ1 first failure was not replayed")
    repair_elapsed = (
        0.0
        if state["repair_started"] is None
        else time.monotonic() - float(state["repair_started"])
    )
    repair_compiles = [item for item in compiler.calls if item["phase"] == "repair"]
    metrics = _call_metrics(store.root / "agents")
    verified = bool(result.compiled and result.audit_passed)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "outcome": "verified" if verified else "unrepaired",
        "fixture": asdict(fixture),
        "arm": arm,
        "repeat": repeat,
        "controls": {
            "candidate_regeneration": False,
            "verification_router": False,
            "smt": False,
            "kernel_first": False,
            "lean_rescue": False,
            "same_initial_prompt_response": True,
            "original_initial_proof_version": fixture.initial_attempt_index + 1,
            "initial_prompt_policy": (
                "original_role_prompt_with_selected_failed_response"
                if fixture.initial_system_prompt is not None
                else "frozen_initial_prompt_response"
            ),
            "same_locked_statement": True,
            "replayed_rq1_first_failure": compiler.replayed,
            "reproduced_rq1_gate_failure": state["gate_reproduced"],
            "reproduced_declaration_preflight": state["preflight_reproduced"],
            "native_repair_feedback": native_feedback,
            "repair_module_cache_policy": "invalidate generated helper modules before use",
        },
        "limits": {
            **deadlines,
            "additional_post_failure_transport_cap": max_repair_calls,
            "ordinary_proof_rounds_total_including_frozen_first_failure": 6,
            "name_repair_rounds": 3,
            "json_format_repairs_per_agent_turn": 3,
            "lean_llm_call_timeout_seconds": 600.0,
        },
        "metrics": {
            **metrics,
            "repair_calls": transport.calls,
            "repair_turns": state["repair_turns"],
            "local_patch_calls": state["local_patch_calls"],
            "lean_compile_calls": len(repair_compiles),
            "lean_seconds": round(
                sum(float(item["duration_seconds"]) for item in repair_compiles), 6
            ),
            "observed_repair_seconds": round(repair_elapsed, 6),
            "observed_total_seconds": round(total_elapsed, 6),
            "charged_time_seconds": round(
                repair_elapsed if verified else timeout_seconds, 6
            ),
        },
        "events": state["events"],
        "lean_result": result.model_dump(mode="json"),
        "created_at_utc": datetime.now(UTC).isoformat(),
    }
    return payload


def run_one(
    fixture: FrozenFixture,
    arm: str,
    repeat: int,
    output_root: Path,
    timeout_seconds: float,
    max_repair_calls: int | None,
    *,
    resume: bool,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    destination = _job_path(output_root, fixture, arm, repeat)
    result_path = destination / "result.json"
    prior_status = None
    if result_path.is_file():
        try:
            prior_status = _read_json(result_path).get("status")
        except (OSError, ValueError, json.JSONDecodeError):
            prior_status = "invalid"
    if resume and prior_status == "completed":
        return {
            "job": [fixture.fixture_id, arm, repeat],
            "status": "skipped",
            "path": str(result_path),
        }
    replace_existing = force or (resume and destination.exists())
    if destination.exists() and not replace_existing:
        raise FileExistsError(f"job already exists (use --resume or --force): {destination}")
    if dry_run:
        return {
            "job": [fixture.fixture_id, arm, repeat],
            "status": "planned",
            "path": str(result_path),
        }

    output_root.mkdir(parents=True, exist_ok=True)
    temporary_parent = output_root / ".incomplete"
    temporary_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="rq3-job-", dir=temporary_parent))
    try:
        from lean_barrier.s15_artifacts import ArtifactStore
    except ModuleNotFoundError:
        if str(FRAMEWORK_ROOT) not in sys.path:
            sys.path.insert(0, str(FRAMEWORK_ROOT))
        from lean_barrier.s15_artifacts import ArtifactStore
    store = ArtifactStore(temporary.parent, temporary.name)
    store.write_json(
        "manifest",
        "job",
        {
            "schema_version": SCHEMA_VERSION,
            "fixture": asdict(fixture),
            "arm": arm,
            "repeat": repeat,
            "deadlines": deadline_spec(timeout_seconds),
            "additional_post_failure_transport_cap": max_repair_calls,
        },
    )
    try:
        payload = _execute_trajectory(
            fixture, arm, repeat, timeout_seconds, max_repair_calls, store
        )
    except Exception as error:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "harness_error",
            "outcome": "harness_error",
            "fixture": asdict(fixture),
            "arm": arm,
            "repeat": repeat,
            "limits": {
                **deadline_spec(timeout_seconds),
                "additional_post_failure_transport_cap": max_repair_calls,
            },
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
            "created_at_utc": datetime.now(UTC).isoformat(),
        }
    _atomic_json(store.root / "result.json", payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        replaced_root = output_root / ".replaced"
        replaced_root.mkdir(parents=True, exist_ok=True)
        backup = replaced_root / (
            f"{fixture.job_component}-{arm}-repeat-{repeat:03d}-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%S-%fZ")
        )
        destination.replace(backup)
    store.root.replace(destination)
    return {
        "job": [fixture.fixture_id, arm, repeat],
        "status": payload["status"],
        "outcome": payload["outcome"],
        "path": str(destination / "result.json"),
    }


def runtime_provenance() -> dict[str, Any]:


    active: dict[str, Any] = {}
    try:
        if str(CURRENT_ROOT) not in sys.path:
            sys.path.insert(0, str(CURRENT_ROOT))
        import pipeline_app

        active = {
            "provider": pipeline_app.PROVIDER,
            "model": pipeline_app.MODEL,
            "reasoning_effort": pipeline_app.REASONING_EFFORT,
            "thinking": pipeline_app.THINKING,
            "max_tokens": pipeline_app.MAX_TOKENS,
            "api_key_configured": bool(pipeline_app.API_KEY),
            "lean_role_parameters": dict(pipeline_app.ROLE_PARAMS.get("lean") or {}),
        }
    except Exception as error:
        active = {"unavailable": f"{type(error).__name__}: {error}"}

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments], cwd=REPO_ROOT, text=True, capture_output=True, check=False
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    dirty = git("status", "--porcelain=v1", "--untracked-files=all")
    lean_toolchain = CURRENT_ROOT / "formalization/lean/lean-toolchain"
    lake_manifest = CURRENT_ROOT / "formalization/lean/lake-manifest.json"
    mathlib_revision = None
    if lake_manifest.is_file():
        try:
            packages = _read_json(lake_manifest).get("packages") or []
            mathlib = next(
                (
                    item
                    for item in packages
                    if isinstance(item, dict) and item.get("name") == "mathlib"
                ),
                None,
            )
            if mathlib:
                mathlib_revision = mathlib.get("rev") or mathlib.get("revision")
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    def file_sha256(path: Path) -> str | None:
        if not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return {
        "active_model": active,
        "git_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(dirty),
        "git_status_sha256": hashlib.sha256(dirty.encode("utf-8")).hexdigest(),
        "lean_toolchain": (
            lean_toolchain.read_text(encoding="utf-8").strip()
            if lean_toolchain.is_file()
            else None
        ),
        "mathlib_revision": mathlib_revision,
        "python": sys.version,


        "code_sha256": {
            "rq3_runner": file_sha256(Path(__file__).resolve()),
            "s05_prompts": file_sha256(
                FRAMEWORK_ROOT / "lean_barrier/s05_prompts.py"
            ),
            "s06_agent_suite": file_sha256(
                FRAMEWORK_ROOT / "lean_barrier/s06_agent_suite.py"
            ),
            "s10_lean_runner": file_sha256(
                FRAMEWORK_ROOT / "lean_barrier/s10_lean_runner.py"
            ),
        },
    }


def frozen_model_signature(fixtures: Sequence[FrozenFixture]) -> dict[str, Any]:
    signatures: set[tuple[Any, ...]] = set()
    for fixture in fixtures:
        call = _read_json(Path(fixture.initial_call_path))
        parameters = call.get("parameters") or {}
        signatures.add(
            (
                parameters.get("provider"),
                call.get("model_id"),
                parameters.get("thinking"),
                parameters.get("max_tokens"),
                "high",
            )
        )
    if len(signatures) != 1:
        raise RuntimeError(f"frozen RQ1 calls have inconsistent model signatures: {signatures}")
    provider, model, thinking, max_tokens, reasoning_effort = next(iter(signatures))
    return {
        "provider": provider,
        "model": model,
        "thinking": thinking,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
    }


def assert_matching_runtime(
    fixtures: Sequence[FrozenFixture], provenance: dict[str, Any]
) -> None:
    expected = frozen_model_signature(fixtures)
    active = provenance.get("active_model") or {}
    observed = {key: active.get(key) for key in expected}
    if observed != expected:
        raise RuntimeError(
            "refusing paid RQ3 batch: active model configuration differs from RQ1; "
            f"expected {expected}, got {observed}"
        )
    if active.get("api_key_configured") is not True:
        raise RuntimeError(
            "refusing paid RQ3 batch: the selected provider API key is not configured"
        )


IMMUTABLE_MANIFEST_FIELDS = (
    "schema_version",
    "source_signature",
    "arms",
    "arm_definitions",
    "repeats",
    "seed",
    "deadlines",
    "max_repair_calls",
    "candidate_count",
    "obligation_count",
    "fixtures",
    "expected_jobs",
    "job_order",
    "frozen_model_signature",
    "runtime_provenance",
)


def immutable_manifest_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    return {key: manifest.get(key) for key in IMMUTABLE_MANIFEST_FIELDS}


def immutable_manifest_sha256(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(
        immutable_manifest_payload(manifest),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def assert_compatible_resume_manifest(
    existing: dict[str, Any], requested: dict[str, Any]
) -> None:
    existing_hash = immutable_manifest_sha256(existing)
    requested_hash = immutable_manifest_sha256(requested)
    if existing_hash != requested_hash:
        differing = [
            key
            for key in IMMUTABLE_MANIFEST_FIELDS
            if existing.get(key) != requested.get(key)
        ]
        raise RuntimeError(
            "refusing to resume into an incompatible RQ3 batch; immutable fields "
            f"differ: {differing}. Use a new --output-root."
        )


COHORT_GROWTH_FIELDS = (
    "source_signature",
    "candidate_count",
    "obligation_count",
    "fixtures",
    "expected_jobs",
    "job_order",
)


def assert_compatible_cohort_growth(
    existing: dict[str, Any], requested: dict[str, Any]
) -> None:


    fixed = [key for key in IMMUTABLE_MANIFEST_FIELDS if key not in COHORT_GROWTH_FIELDS]
    differing = [key for key in fixed if existing.get(key) != requested.get(key)]
    if differing:
        raise RuntimeError(
            f"refusing cohort growth; non-cohort immutable fields differ: {differing}"
        )
    old_hashes = (existing.get("source_signature") or {}).get("fixture_sha256") or {}
    new_hashes = (requested.get("source_signature") or {}).get("fixture_sha256") or {}
    dropped = sorted(set(old_hashes) - set(new_hashes))
    changed = sorted(
        key for key in set(old_hashes) & set(new_hashes) if old_hashes[key] != new_hashes[key]
    )
    if dropped or changed:
        raise RuntimeError(
            f"refusing cohort growth; dropped={dropped}, changed={changed}"
        )


def _parse_arms(value: str, include_local_patch: bool = False) -> tuple[str, ...]:
    arms = tuple(item.strip() for item in value.split(",") if item.strip())
    if include_local_patch and "local_patch" not in arms:
        arms = (*arms, "local_patch")
    unknown = sorted(set(arms) - set(ALL_ARMS))
    if unknown or not arms or len(set(arms)) != len(arms):
        raise ValueError(f"invalid or duplicate arms: {unknown or arms}")
    return arms


def build_jobs(
    fixtures: Sequence[FrozenFixture],
    arms: Sequence[str],
    repeats: int,
    seed: int,
) -> list[Job]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    jobs: list[Job] = []
    fixture_ids = [fixture.fixture_id for fixture in fixtures]


    for wave in range(len(arms)):
        for repeat in range(repeats):
            ordered = sorted(
                fixture_ids,
                key=lambda fixture_id: hashlib.sha256(
                    f"fixture-order:{seed}:{wave}:{repeat}:{fixture_id}".encode()
                ).hexdigest(),
            )
            if jobs and ordered and jobs[-1].fixture_id == ordered[0]:
                ordered = [*ordered[1:], ordered[0]]
            for fixture_id in ordered:
                offset = int(
                    hashlib.sha256(
                        f"arm-order:{seed}:{fixture_id}:{repeat}".encode()
                    ).hexdigest(),
                    16,
                ) % len(arms)
                arm = arms[(offset + wave) % len(arms)]
                jobs.append(Job(fixture_id, arm, repeat))
    if any(left.fixture_id == right.fixture_id for left, right in zip(jobs, jobs[1:])):
        raise AssertionError("scheduler produced adjacent jobs for the same frozen fixture")
    expected = len(fixtures) * repeats * len(arms)
    if len(jobs) != expected or len(set(jobs)) != expected:
        raise AssertionError("scheduler did not produce each arm/fixture/repeat exactly once")
    return jobs


def _worker(payload: dict[str, Any]) -> dict[str, Any]:
    fixtures = _fixture_map(Path(payload["source_root"]), Path(payload["cohort_path"]))
    fixture = fixtures[str(payload["fixture_id"])]
    return run_one(
        fixture,
        str(payload["arm"]),
        int(payload["repeat"]),
        Path(payload["output_root"]),
        float(payload["timeout_seconds"]),
        (
            None
            if payload.get("max_repair_calls") is None
            else int(payload["max_repair_calls"])
        ),
        resume=bool(payload["resume"]),
        force=bool(payload["force"]),
    )


def run_batch(
    args: argparse.Namespace,
    fixtures: list[FrozenFixture],
    arms: tuple[str, ...],
) -> int:
    jobs = build_jobs(fixtures, arms, args.repeats, args.seed)
    provenance = runtime_provenance()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_root": str(args.source.resolve()),
        "cohort_path": str(args.cohort.resolve()),
        "source_signature": frozen_source_signature(
            fixtures, args.source, args.cohort
        ),
        "output_root": str(args.output_root.resolve()),
        "arms": list(arms),
        "arm_definitions": {arm: ARM_DEFINITIONS[arm] for arm in arms},
        "repeats": args.repeats,
        "workers": args.workers,
        "seed": args.seed,
        "deadlines": deadline_spec(args.timeout),
        "max_repair_calls": args.max_repair_calls,
        "candidate_count": len({item.record_id for item in fixtures}),
        "obligation_count": len(fixtures),
        "fixtures": [asdict(item) for item in fixtures],
        "expected_jobs": len(jobs),
        "job_order": [asdict(job) for job in jobs],
        "controls": {
            "candidate_regeneration": False,
            "verification_router": False,
            "smt": False,
            "kernel_first": False,
        },
        "frozen_model_signature": frozen_model_signature(fixtures),
        "runtime_provenance": provenance,
    }
    manifest["immutable_signature_sha256"] = immutable_manifest_sha256(manifest)
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return 0
    assert_matching_runtime(fixtures, provenance)
    manifest_path = args.output_root / "batch_manifest.json"
    if manifest_path.is_file():
        existing = _read_json(manifest_path)
        if args.resume and getattr(args, "allow_cohort_growth", False):
            assert_compatible_cohort_growth(existing, manifest)
            if immutable_manifest_sha256(existing) != immutable_manifest_sha256(manifest):
                history = list(existing.get("cohort_growth_history") or [])
                history.append(
                    {
                        "grown_at_utc": datetime.now(UTC).isoformat(),
                        "previous_obligation_count": existing.get("obligation_count"),
                        "previous_immutable_signature_sha256": existing.get(
                            "immutable_signature_sha256"
                        ),
                    }
                )
                _atomic_json(
                    manifest_path, {**manifest, "cohort_growth_history": history}
                )
        elif args.resume:
            assert_compatible_resume_manifest(existing, manifest)
        elif not args.force:
            raise FileExistsError(
                "batch manifest already exists (use --resume or a new output root): "
                f"{manifest_path}"
            )
        else:
            _atomic_json(manifest_path, manifest)
    else:
        existing_jobs = list((args.output_root / "jobs").glob("*/*/repeat-*/result.json"))
        if args.resume and existing_jobs:
            raise RuntimeError(
                "refusing resume: job results exist without a batch_manifest.json"
            )
        _atomic_json(manifest_path, manifest)
    payloads = [
        {
            **asdict(job),
            "source_root": str(args.source),
            "cohort_path": str(args.cohort),
            "output_root": str(args.output_root),
            "timeout_seconds": args.timeout,
            "max_repair_calls": args.max_repair_calls,
            "resume": args.resume,
            "force": args.force,
        }
        for job in jobs
    ]
    completed = 0
    if args.workers == 1:
        iterator: Iterable[dict[str, Any]] = (_worker(payload) for payload in payloads)
        for result in iterator:
            completed += 1
            print(json.dumps({"progress": [completed, len(jobs)], **result}), flush=True)
    else:
        worker_errors: list[dict[str, Any]] = []


        wave_size = len(fixtures) * args.repeats
        for wave_start in range(0, len(payloads), wave_size):
            wave_payloads = payloads[wave_start : wave_start + wave_size]
            with ProcessPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(_worker, payload): payload
                    for payload in wave_payloads
                }
                for future in as_completed(futures):
                    completed += 1
                    try:
                        result = future.result()
                    except Exception as error:
                        payload = futures[future]
                        result = {
                            "job": [
                                payload["fixture_id"], payload["arm"], payload["repeat"]
                            ],
                            "status": "worker_error",
                            "error": f"{type(error).__name__}: {error}",
                        }
                        worker_errors.append(result)
                    print(
                        json.dumps({"progress": [completed, len(jobs)], **result}),
                        flush=True,
                    )
        if worker_errors:
            _atomic_json(args.output_root / "batch_worker_errors.json", worker_errors)
    return 0


def summarize(output_root: Path) -> dict[str, Any]:
    manifest_path = output_root / "batch_manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
    rows: list[dict[str, Any]] = []
    for path in sorted((output_root / "jobs").glob("*/*/repeat-*/result.json")):
        payload = _read_json(path)
        metrics = payload.get("metrics") or {}
        fixture = payload.get("fixture") or {}
        rows.append(
            {
                "fixture_id": fixture.get("fixture_id"),
                "record_id": fixture.get("record_id"),
                "arm": payload.get("arm"),
                "repeat": payload.get("repeat"),
                "status": payload.get("status"),
                "outcome": payload.get("outcome"),
                **{key: metrics.get(key, 0) for key in (
                    "repair_calls", "repair_turns", "recorded_responses",
                    "transport_attempts", "tokens",
                    "reasoning_tokens", "lean_compile_calls", "llm_seconds", "lean_seconds",
                    "observed_repair_seconds", "observed_total_seconds", "charged_time_seconds",
                )},
                "result_path": str(path),
            }
        )
    expected = int(manifest.get("expected_jobs", len(rows)))
    expected_jobs = manifest.get("job_order") or []
    arms = sorted(
        {str(job["arm"]) for job in expected_jobs if isinstance(job, dict)}
        if expected_jobs
        else {str(row["arm"]) for row in rows}
    )
    row_index = {
        (str(row["fixture_id"]), str(row["arm"]), int(row["repeat"])): row
        for row in rows
    }
    if expected_jobs:
        expected_keys = {
            (str(job["fixture_id"]), str(job["arm"]), int(job["repeat"]))
            for job in expected_jobs
            if isinstance(job, dict)
        }
        rows = [row for key, row in row_index.items() if key in expected_keys]
    candidate_groups: dict[tuple[str, str, int], list[str]] = {}
    source_jobs = expected_jobs or [
        {
            "fixture_id": row["fixture_id"],
            "arm": row["arm"],
            "repeat": row["repeat"],
        }
        for row in rows
    ]
    for job in source_jobs:
        if not isinstance(job, dict):
            continue
        fixture_id = str(job["fixture_id"])
        key = (
            str(job["arm"]),
            fixture_id.split(":", 1)[0],
            int(job["repeat"]),
        )
        candidate_groups.setdefault(key, []).append(fixture_id)
    candidate_rows: list[dict[str, Any]] = []
    for (arm, record_id, repeat), fixture_ids in sorted(candidate_groups.items()):
        selected = [
            row_index.get((fixture_id, arm, repeat)) for fixture_id in fixture_ids
        ]
        complete = all(
            row is not None and row["status"] == "completed" for row in selected
        )
        verified = bool(
            complete and all(row["outcome"] == "verified" for row in selected if row)
        )
        candidate_row: dict[str, Any] = {
            "record_id": record_id,
            "arm": arm,
            "repeat": repeat,
            "expected_obligations": len(fixture_ids),
            "completed": complete,
            "restored": verified,
        }
        if complete:
            complete_rows = [row for row in selected if row is not None]
            for key in (
                "repair_calls", "repair_turns", "tokens", "llm_seconds", "lean_seconds",
                "observed_repair_seconds", "charged_time_seconds",
            ):
                values = [float(row[key] or 0) for row in complete_rows]
                candidate_row[f"{key}_sum"] = round(sum(values), 6)
                candidate_row[f"{key}_max"] = round(max(values, default=0.0), 6)
        candidate_rows.append(candidate_row)
    by_arm: dict[str, Any] = {}
    for arm in arms:
        subset = [row for row in rows if row["arm"] == arm]
        experimental = [row for row in subset if row["status"] == "completed"]
        expected_for_arm = [
            job for job in expected_jobs
            if isinstance(job, dict) and str(job.get("arm")) == arm
        ]
        restored: dict[tuple[str, int], bool] = {}
        if expected_for_arm:
            for job in expected_for_arm:
                fixture_id = str(job["fixture_id"])
                repeat = int(job["repeat"])
                record_id = fixture_id.split(":", 1)[0]
                row = row_index.get((fixture_id, arm, repeat))
                succeeded = bool(
                    row is not None
                    and row["status"] == "completed"
                    and row["outcome"] == "verified"
                )
                key = (record_id, repeat)
                restored[key] = restored.get(key, True) and succeeded
        else:

            for row in subset:
                key = (str(row["record_id"]), int(row["repeat"]))
                succeeded = row["status"] == "completed" and row["outcome"] == "verified"
                restored[key] = restored.get(key, True) and succeeded
        numeric = (
            "repair_calls", "repair_turns", "recorded_responses", "transport_attempts", "tokens",
            "reasoning_tokens", "lean_compile_calls", "llm_seconds", "lean_seconds",
            "observed_repair_seconds", "observed_total_seconds", "charged_time_seconds",
        )
        arm_candidates = [row for row in candidate_rows if row["arm"] == arm]
        complete_candidates = [row for row in arm_candidates if row["completed"]]
        candidate_numeric = (
            "repair_calls_sum", "repair_turns_sum", "repair_turns_max",
            "tokens_sum", "llm_seconds_sum", "lean_seconds_sum",
            "observed_repair_seconds_sum", "observed_repair_seconds_max",
            "charged_time_seconds_sum", "charged_time_seconds_max",
        )
        by_arm[arm] = {
            "jobs_completed": len(subset),
            "experimental_jobs": len(experimental),
            "harness_errors": sum(row["status"] == "harness_error" for row in subset),
            "obligations_verified": sum(row["outcome"] == "verified" for row in experimental),
            "candidates_restored": sum(restored.values()),
            "candidate_trials": len(restored),
            "candidate_trials_complete": len(complete_candidates),
            "candidate_trial_averages": {
                key: round(
                    sum(float(row.get(key, 0)) for row in complete_candidates)
                    / len(complete_candidates),
                    6,
                )
                if complete_candidates else None
                for key in candidate_numeric
            },
            "totals": {
                key: round(sum(float(row[key] or 0) for row in experimental), 6)
                for key in numeric
            },
            "averages": {
                key: round(sum(float(row[key] or 0) for row in experimental) / len(experimental), 6)
                if experimental else None
                for key in numeric
            },
        }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "jobs_expected": expected,
        "jobs_completed": len(rows),
        "jobs_missing": max(0, expected - len(rows)),
        "by_arm": by_arm,
    }
    _atomic_json(output_root / "summary.json", summary)
    csv_path = output_root / "per_job_metrics.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with tempfile.NamedTemporaryFile(
            "w",
            newline="",
            encoding="utf-8",
            dir=csv_path.parent,
            delete=False,
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            temporary = Path(handle.name)
        os.replace(temporary, csv_path)
    candidate_csv_path = output_root / "per_candidate_trial_metrics.csv"
    if candidate_rows:
        fieldnames = sorted({key for row in candidate_rows for key in row})
        with tempfile.NamedTemporaryFile(
            "w",
            newline="",
            encoding="utf-8",
            dir=candidate_csv_path.parent,
            delete=False,
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(candidate_rows)
            temporary = Path(handle.name)
        os.replace(temporary, candidate_csv_path)
    return summary


def _common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source", type=Path, default=DEFAULT_SOURCE,
        help="frozen RQ1 experiment root",
    )
    parser.add_argument(
        "--cohort", type=Path, default=DEFAULT_COHORT,
        help="JSON containing rq3_repair_set",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    export_parser = sub.add_parser(
        "export-fixtures",
        help="maintainer-only: recreate the tracked sanitized bundle from raw RQ1",
    )
    export_parser.add_argument(
        "--source",
        type=Path,
        default=RAW_RQ1_SOURCE,
        help="full local RQ1 experiment root",
    )
    export_parser.add_argument(
        "--cohort",
        type=Path,
        default=RAW_RQ3_COHORT,
        help="raw result JSON containing rq3_repair_set",
    )
    export_parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_SOURCE,
        help="tracked compact fixture-bundle destination",
    )
    export_parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing bundle after moving it to a recoverable backup",
    )
    cohort_parser = sub.add_parser(
        "build-cohort",
        help="derive the RQ3 cohort JSON from the Full run (no model calls)",
    )
    cohort_parser.add_argument("--source", type=Path, default=RAW_RQ1_SOURCE)
    cohort_parser.add_argument("--output", type=Path, default=RAW_RQ3_COHORT)
    ablation_parser = sub.add_parser(
        "build-ablation-cohort",
        help="derive the 26-obligation RQ3 repair cohort, including unrepaired failures",
    )
    ablation_parser.add_argument("--source", type=Path, default=RAW_RQ1_SOURCE)
    ablation_parser.add_argument("--output", type=Path, default=ABLATION_COHORT)
    list_parser = sub.add_parser("list", help="list the frozen 19-system/26-obligation repair cohort")
    _common_paths(list_parser)
    validate_parser = sub.add_parser(
        "validate",
        help="validate all hashes and frozen responses without Lean or model calls",
    )
    _common_paths(validate_parser)
    one = sub.add_parser("run-one", help="run one isolated arm/obligation/repeat trajectory")
    _common_paths(one)
    one.add_argument("--fixture", required=True)
    one.add_argument("--arm", choices=ALL_ARMS, required=True)
    one.add_argument("--repeat", type=int, default=0)
    one.add_argument(
        "--timeout", type=float, default=900.0,
        help="charged repair/proof budget in seconds (maximum 900; hard deadline adds 60)",
    )
    one.add_argument(
        "--max-repair-calls",
        type=int,
        default=None,
        help="optional extra transport-call cap; omit to match the current RQ1 loop",
    )
    one.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    one.add_argument("--resume", action="store_true")
    one.add_argument("--force", action="store_true")
    one.add_argument("--dry-run", action="store_true")
    one.add_argument(
        "--execute", action="store_true",
        help="required acknowledgement before any model calls",
    )
    batch = sub.add_parser("batch", help="run a deterministic, interleaved batch")
    _common_paths(batch)
    batch.add_argument("--arms", default=",".join(DEFAULT_ARMS))
    batch.add_argument("--include-local-patch", action="store_true")
    batch.add_argument("--repeats", type=int, default=1)
    batch.add_argument("--workers", type=int, default=8)
    batch.add_argument(
        "--timeout", type=float, default=900.0,
        help="charged repair/proof budget in seconds (maximum 900; hard deadline adds 60)",
    )
    batch.add_argument(
        "--max-repair-calls",
        type=int,
        default=None,
        help="optional extra transport-call cap; omit to match the current RQ1 loop",
    )
    batch.add_argument("--seed", type=int, default=20260903)
    batch.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    batch.add_argument("--resume", action="store_true")
    batch.add_argument(
        "--allow-cohort-growth",
        action="store_true",
        help="with --resume: accept new fixtures (re-exported bundle); keep completed jobs",
    )
    batch.add_argument("--force", action="store_true")
    batch.add_argument("--dry-run", action="store_true")
    batch.add_argument(
        "--execute", action="store_true",
        help="required acknowledgement before any model calls",
    )
    summary_parser = sub.add_parser("summarize", help="aggregate completed atomic job artifacts")
    summary_parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "export-fixtures":
        print(
            json.dumps(
                export_frozen_bundle(
                    args.source,
                    args.cohort,
                    args.destination,
                    force=args.force,
                ),
                indent=2,
            )
        )
        return 0
    if args.command == "build-cohort":
        cohort = build_cohort(args.source)
        _atomic_json(args.output, cohort)
        print(json.dumps({"output": str(args.output), **cohort}, indent=2))
        return 0
    if args.command == "build-ablation-cohort":
        cohort = build_ablation_cohort(args.source)
        _atomic_json(args.output, cohort)
        repair_set = cohort["rq3_repair_set"]
        print(json.dumps({
            "output": str(args.output),
            "systems": repair_set["candidate_count"],
            "obligations": repair_set["obligation_count"],
            "repaired": repair_set["repaired_obligation_count"],
            "unrepaired": repair_set["unrepaired_obligation_count"],
        }, indent=2))
        return 0
    if args.command == "summarize":
        print(json.dumps(summarize(args.output_root), indent=2))
        return 0
    cohort_payload = _read_json(args.cohort)
    bundle = (
        validate_frozen_bundle(args.source, args.cohort)
        if cohort_payload.get("schema_version") == BUNDLE_SCHEMA_VERSION
        else None
    )
    fixtures = discover_fixtures(args.source, args.cohort)
    if args.command == "list":
        print(json.dumps({
            "candidate_count": len({item.record_id for item in fixtures}),
            "obligation_count": len(fixtures),
            "fixtures": [asdict(item) for item in fixtures],
        }, indent=2))
        return 0
    if args.command == "validate":
        print(
            json.dumps(
                {
                    "validated": len(fixtures),
                    "bundle": bundle,
                    "fixtures": [validate_fixture(item) for item in fixtures],
                },
                indent=2,
            )
        )
        return 0
    if args.command == "run-one":
        deadline_spec(args.timeout)
        if args.max_repair_calls is not None and args.max_repair_calls < 1:
            raise ValueError("max-repair-calls must be positive")
        if not args.dry_run and not args.execute:
            raise RuntimeError("run-one requires --execute before model calls")
        mapping = {item.fixture_id: item for item in fixtures}
        if args.fixture not in mapping:
            raise KeyError(f"unknown fixture {args.fixture!r}; run the list command")
        result = run_one(
            mapping[args.fixture], args.arm, args.repeat, args.output_root,
            args.timeout, args.max_repair_calls, resume=args.resume,
            force=args.force, dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return 0
    deadline_spec(args.timeout)
    if args.workers < 1:
        raise ValueError("workers must be positive")
    if args.max_repair_calls is not None and args.max_repair_calls < 1:
        raise ValueError("max-repair-calls must be positive")
    if not args.dry_run and not args.execute:
        raise RuntimeError("batch requires --execute before model calls")
    arms = _parse_arms(args.arms, args.include_local_patch)
    return run_batch(args, fixtures, arms)


if __name__ == "__main__":
    raise SystemExit(main())
