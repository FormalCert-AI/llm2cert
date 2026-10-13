"""Search and screen certificate candidates."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .s15_artifacts import ArtifactStore
from .s13_runtime import (
    DEFAULT_FINALIZATION_RESERVE_SECONDS,
    RunDeadline,
    RunDeadlineExceeded,
)
from .s02_expressions import content_hash
from .s01_models import (
    CandidateRecord,
    CandidateSpec,
    CandidateStatus,
    CandidateVerdict,
    CounterexampleEvidence,
    EvidenceLevel,
    ProblemSpec,
)

if TYPE_CHECKING:
    from .s16_workflow import CandidateVerifier

MAX_CANDIDATES = 5

MAX_REGENERATIONS = 2


@dataclass(frozen=True)
class SynthesisContext:
    structure_index: int
    parent: CandidateRecord | None
    counterexample: CounterexampleEvidence | None
    errors: tuple[str, ...]

    history: tuple[dict[str, object], ...] = ()


SynthesisProvider = Callable[[ProblemSpec, SynthesisContext], CandidateSpec]


@dataclass(frozen=True)
class SearchResult:
    status: CandidateStatus
    verdict: CandidateVerdict | None
    candidates: tuple[CandidateRecord, ...]
    errors: tuple[str, ...]


def _structure(value: object) -> object:
    if isinstance(value, dict):
        if value.get("kind") == "const":
            return {"kind": "const", "value": "_coefficient_"}
        return {
            key: _structure(item)
            for key, item in sorted(value.items())
            if key != "construction_summary"
        }
    if isinstance(value, list):
        return [_structure(item) for item in value]
    return value


def structure_hash(candidate: CandidateSpec) -> str:
    payload = {
        "certificate_ast": candidate.certificate_ast.model_dump(mode="json"),
        "controller_ast": candidate.controller_ast.model_dump(mode="json"),
    }
    return content_hash(_structure(payload))


class CandidateSearch:
    def __init__(
        self,
        verifier: CandidateVerifier,
        synthesis_provider: SynthesisProvider,
        artifact_store: ArtifactStore | None = None,
        *,
        max_candidates: int = MAX_CANDIDATES,
        deadline: RunDeadline | None = None,
    ) -> None:
        if max_candidates < 1:
            raise ValueError("search limits must be positive")
        self.verifier = verifier
        self.synthesis_provider = synthesis_provider
        self.store = artifact_store or getattr(verifier, "store", None)
        self.max_candidates = max_candidates
        self.deadline = deadline

    def _timed_out(
        self,
        records: list[CandidateRecord],
        errors: list[str],
    ) -> SearchResult:
        seconds = self.deadline.timeout_seconds if self.deadline is not None else 0
        return self._finish(
            SearchResult(
                CandidateStatus.UNRESOLVED,
                None,
                tuple(records),
                tuple(errors + [f"single-problem {seconds:g}-second deadline exhausted"]),
            )
        )

    def _finish(self, result: SearchResult) -> SearchResult:
        if self.store:
            self.store.write_json("search", "result", result)
        return result

    def _record_candidate_timing(
        self,
        candidate_index: int,
        *,
        started_at_utc: str,
        started_monotonic: float,
        status: str,
        candidate_hash: str | None = None,
    ) -> None:
        if self.store is None:
            return
        self.store.write_candidate_timing(
            candidate_index,
            {
                "schema_version": "dynacert-candidate-timing.v1",
                "candidate_index": candidate_index,
                "candidate_hash": candidate_hash,
                "status": status,
                "started_at_utc": started_at_utc,
                "finished_at_utc": datetime.now(UTC).isoformat(),
                "duration_seconds": time.monotonic() - started_monotonic,
            },
        )

    def run(self, problem: ProblemSpec) -> SearchResult:
        records: list[CandidateRecord] = []
        errors: list[str] = []
        history: list[dict[str, object]] = []
        last_counterexample: CounterexampleEvidence | None = None
        parent: CandidateRecord | None = None
        for candidate_index in range(self.max_candidates):
            if self.deadline is not None and self.deadline.expired(
                reserve_seconds=DEFAULT_FINALIZATION_RESERVE_SECONDS
            ):
                return self._timed_out(records, errors)
            candidate_started_at_utc = datetime.now(UTC).isoformat()
            candidate_started_monotonic = time.monotonic()
            candidate: CandidateSpec | None = None
            for _attempt in range(1 + MAX_REGENERATIONS):
                context = SynthesisContext(
                    candidate_index,
                    parent,
                    last_counterexample,
                    tuple(errors),
                    tuple(history),
                )
                try:
                    generated = self.synthesis_provider(problem, context)
                except RunDeadlineExceeded:
                    self._record_candidate_timing(
                        candidate_index,
                        started_at_utc=candidate_started_at_utc,
                        started_monotonic=candidate_started_monotonic,
                        status="problem_timeout_during_synthesis",
                    )
                    return self._timed_out(records, errors)
                except Exception as error:
                    errors.append(f"candidate {candidate_index}: parse error: {error}")
                    continue
                candidate = generated
                break
            if candidate is None:
                self._record_candidate_timing(
                    candidate_index,
                    started_at_utc=candidate_started_at_utc,
                    started_monotonic=candidate_started_monotonic,
                    status="parse_regenerations_exhausted",
                )
                continue
            digest = content_hash(candidate)
            record = CandidateRecord(
                candidate_hash=digest,
                parent_hash=parent.candidate_hash if parent else None,
                structure_index=candidate_index,
                candidate=candidate,
            )
            records.append(record)
            if self.store:
                self.store.write_json(
                    "lineage",
                    f"{len(records) - 1:02d}-{digest[:12]}",
                    record,
                )
            if len(records) > self.max_candidates:
                raise AssertionError("candidate budget exceeded")
            try:
                verdict = self.verifier.verify(problem, candidate)
            except RunDeadlineExceeded:
                self._record_candidate_timing(
                    candidate_index,
                    started_at_utc=candidate_started_at_utc,
                    started_monotonic=candidate_started_monotonic,
                    status="problem_timeout_during_verification",
                    candidate_hash=digest,
                )
                return self._timed_out(records, errors)
            except (ValueError, TypeError) as error:
                errors.append(f"candidate {digest}: semantic error: {error}")
                parent = record
                self._record_candidate_timing(
                    candidate_index,
                    started_at_utc=candidate_started_at_utc,
                    started_monotonic=candidate_started_monotonic,
                    status="semantic_error",
                    candidate_hash=digest,
                )
                continue
            if verdict.status == CandidateStatus.VERIFIED:
                self._record_candidate_timing(
                    candidate_index,
                    started_at_utc=candidate_started_at_utc,
                    started_monotonic=candidate_started_monotonic,
                    status=verdict.status.value,
                    candidate_hash=digest,
                )
                return self._finish(
                    SearchResult(verdict.status, verdict, tuple(records), tuple(errors))
                )
            if verdict.status == CandidateStatus.NEEDS_HUMAN_REVIEW:
                self._record_candidate_timing(
                    candidate_index,
                    started_at_utc=candidate_started_at_utc,
                    started_monotonic=candidate_started_monotonic,
                    status=verdict.status.value,
                    candidate_hash=digest,
                )
                return self._finish(
                    SearchResult(verdict.status, verdict, tuple(records), tuple(errors))
                )
            if verdict.status == CandidateStatus.UNRESOLVED:
                if getattr(self.verifier, "smt_only", False):
                    errors.append(
                        f"candidate {digest}: SMT-only unresolved; stopping search"
                    )
                    self._record_candidate_timing(
                        candidate_index,
                        started_at_utc=candidate_started_at_utc,
                        started_monotonic=candidate_started_monotonic,
                        status=verdict.status.value,
                        candidate_hash=digest,
                    )
                    return self._finish(
                        SearchResult(
                            verdict.status, verdict, tuple(records), tuple(errors)
                        )
                    )
                errors.append(
                    f"candidate {digest}: unresolved; continuing with the next candidate"
                )
                parent = record
                self._record_candidate_timing(
                    candidate_index,
                    started_at_utc=candidate_started_at_utc,
                    started_monotonic=candidate_started_monotonic,
                    status=verdict.status.value,
                    candidate_hash=digest,
                )
                continue
            if verdict.status == CandidateStatus.REJECTED and verdict.counterexample:
                if verdict.counterexample.level not in {
                    EvidenceLevel.INTERVAL_VALIDATED,
                    EvidenceLevel.EXACT_MODEL_REPLAY,
                }:
                    self._record_candidate_timing(
                        candidate_index,
                        started_at_utc=candidate_started_at_utc,
                        started_monotonic=candidate_started_monotonic,
                        status=CandidateStatus.NEEDS_HUMAN_REVIEW.value,
                        candidate_hash=digest,
                    )
                    return self._finish(
                        SearchResult(
                            CandidateStatus.NEEDS_HUMAN_REVIEW,
                            verdict,
                            tuple(records),
                            tuple(
                                errors
                                + ["non-authoritative evidence cannot drive synthesis feedback"]
                            ),
                        )
                    )
                confirmed = verdict.counterexamples or (verdict.counterexample,)
                history.append(
                    {
                        "candidate_hash": digest,
                        "construction_summary": candidate.construction_summary,
                        "counterexamples": [
                            evidence.model_dump(mode="json") for evidence in confirmed
                        ],
                    }
                )
                last_counterexample = verdict.counterexample
                parent = record
                self._record_candidate_timing(
                    candidate_index,
                    started_at_utc=candidate_started_at_utc,
                    started_monotonic=candidate_started_monotonic,
                    status=verdict.status.value,
                    candidate_hash=digest,
                )
                continue
            self._record_candidate_timing(
                candidate_index,
                started_at_utc=candidate_started_at_utc,
                started_monotonic=candidate_started_monotonic,
                status=CandidateStatus.NEEDS_HUMAN_REVIEW.value,
                candidate_hash=digest,
            )
            return self._finish(
                SearchResult(
                    CandidateStatus.NEEDS_HUMAN_REVIEW,
                    verdict,
                    tuple(records),
                    tuple(errors + ["formal unresolved result stopped search"]),
                )
            )
        return self._finish(
            SearchResult(
                CandidateStatus.SEARCH_EXHAUSTED,
                None,
                tuple(records),
                tuple(errors),
            )
        )
