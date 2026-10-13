"""Record run inputs, model calls, proofs, and verification results."""
from __future__ import annotations

import json
import csv
import fcntl
import os
import platform
import tempfile
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel

from .s06_agents import AgentTransport
from .s02_expressions import canonical_json, content_hash


class ArtifactStore:
    def __init__(self, root: str | Path, run_id: str) -> None:
        self.root = Path(root) / run_id
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def deterministic_run_id(configuration: Mapping[str, Any]) -> str:
        return f"run-{content_hash(dict(configuration))[:16]}"

    def _value(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return self._value(value.model_dump(mode="json"))
        if is_dataclass(value) and not isinstance(value, type):
            return self._value(asdict(value))
        if isinstance(value, Mapping):
            return {str(key): self._value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._value(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        return value

    def write_json(self, category: str, name: str, value: Any) -> Path:
        directory = self.root / category
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{name}.json"
        payload = (
            json.dumps(self._value(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        )
        self._atomic_write(target, payload)
        return target

    def write_text(self, category: str, name: str, value: str, suffix: str = ".txt") -> Path:
        directory = self.root / category
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{name}{suffix}"
        self._atomic_write(target, value)
        return target

    @staticmethod
    def _atomic_write(target: Path, payload: str) -> None:
        with tempfile.NamedTemporaryFile(
            "w", dir=target.parent, delete=False, encoding="utf-8"
        ) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        os.replace(temporary, target)

    def record_environment(
        self,
        *,
        container_digests: Mapping[str, str],
        random_seed: int,
    ) -> Path:
        return self.write_json(
            "manifest",
            "environment",
            {
                "recorded_at_utc": datetime.now(UTC).isoformat(),
                "python": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "cpu_count": os.cpu_count(),
                "container_digests": dict(container_digests),
                "random_seed": random_seed,
            },
        )

    def record_agent_call(
        self,
        *,
        role: str,
        sequence: int,
        prompt_version: str,
        model_id: str,
        parameters: Mapping[str, Any],
        prompt: str,
        response: str = "",
        call_info: Mapping[str, Any] | None = None,
        status: str = "completed",
        error: str | None = None,
    ) -> Path:
        return self.write_json(
            "agents",
            f"{sequence:04d}-{role}",
            {
                "role": role,
                "prompt_version": prompt_version,
                "model_id": model_id,
                "parameters": dict(parameters),
                "call_info": dict(call_info) if call_info else None,
                "status": status,
                "prompt": prompt,
                "prompt_hash": content_hash(prompt),
                "response": response,
                "response_hash": content_hash(response) if response else None,
                "error": error,
            },
        )

    def write_candidate_timing(
        self,
        candidate_index: int,
        value: Mapping[str, Any],
    ) -> Path:
        return self.write_json("candidate_timing", f"{candidate_index:02d}", value)

    def human_review_report(
        self,
        *,
        problem_id: str,
        candidate_hash: str,
        reason: str,
        unresolved: list[str],
    ) -> Path:
        lines = [
            f"# Human review required: {problem_id}",
            "",
            f"Candidate SHA-256: `{candidate_hash}`",
            "",
            f"Reason: {reason}",
            "",
            "The v1 state machine is paused. It has no resume command.",
            "",
            "## Unresolved conditions",
            "",
        ]
        lines.extend(f"- {item}" for item in unresolved)
        lines.extend(
            (
                "",
                "Review the recorded prompts, queries, solver output, Lean attempts, compiler "
                "diagnostics, statement hashes, and axiom audit before starting a new run.",
                "",
            )
        )
        return self.write_text("reports", "needs_human_review", "\n".join(lines), ".md")


class RunBundleStore(ArtifactStore):


    schema_version = "dynacert-run.v2"

    def __init__(
        self,
        experiment_root: str | Path,
        *,
        problem_class: str,
        record_id: str,
        run_id: str,
    ) -> None:
        self.experiment_root = Path(experiment_root)
        self.problem_class = problem_class
        self.record_id = record_id
        self.run_id = run_id
        self._started_monotonic = time.monotonic()
        self._candidate_indices: dict[str, int] = {}
        self._context: ContextVar[dict[str, Any]] = ContextVar(
            f"run_bundle_context_{id(self)}", default={}
        )
        self._index_lock = threading.Lock()
        super().__init__(
            self.experiment_root / "runs" / problem_class / record_id,
            run_id,
        )

    @staticmethod
    def _safe_name(value: str) -> str:
        return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)

    def register_candidate(self, candidate_hash: str, index: int) -> Path:
        self._candidate_indices[candidate_hash] = index
        directory = self.root / "candidates" / f"{index:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _candidate_hash_from_prefix(self, prefix: str) -> str | None:
        matches = [digest for digest in self._candidate_indices if digest.startswith(prefix)]
        return matches[0] if len(matches) == 1 else None

    def candidate_dir(
        self,
        *,
        candidate_hash: str | None = None,
        candidate_index: int | None = None,
    ) -> Path:
        if candidate_index is None and candidate_hash is not None:
            candidate_index = self._candidate_indices.get(candidate_hash)
        if candidate_index is None:
            return self.root / "unassigned"
        return self.root / "candidates" / f"{candidate_index:02d}"

    def condition_dir(self, candidate_hash: str, condition_id: str) -> Path:
        parts = condition_id.split(":")
        label = "-".join(parts[1:]) if len(parts) > 1 else condition_id
        return self.candidate_dir(candidate_hash=candidate_hash) / "conditions" / self._safe_name(label)

    @contextmanager
    def scope(
        self,
        *,
        candidate_hash: str | None = None,
        candidate_index: int | None = None,
        condition_id: str | None = None,
        stage: str | None = None,
    ) -> Iterator[None]:
        current = dict(self._context.get())
        updates = {
            "candidate_hash": candidate_hash,
            "candidate_index": candidate_index,
            "condition_id": condition_id,
            "stage": stage,
        }
        current.update({key: value for key, value in updates.items() if value is not None})
        token = self._context.set(current)
        try:
            yield
        finally:
            self._context.reset(token)

    def current_context(self) -> dict[str, Any]:
        return dict(self._context.get())

    def initialize(
        self,
        *,
        experiment: Mapping[str, Any],
        manifest: Mapping[str, Any],
        source_record: Any,
        problem: Any,
    ) -> None:
        self.experiment_root.mkdir(parents=True, exist_ok=True)
        experiment_path = self.experiment_root / "experiment.json"
        expected_experiment = self._value(experiment)
        if experiment_path.exists():
            observed = json.loads(experiment_path.read_text(encoding="utf-8"))
            if observed != expected_experiment:
                raise ValueError(
                    f"experiment configuration changed for {self.experiment_root.name}; "
                    "use a new experiment_id"
                )
        else:
            payload = json.dumps(
                expected_experiment, ensure_ascii=False, sort_keys=True, indent=2
            ) + "\n"
            self._atomic_write(experiment_path, payload)
        self.write_json("manifest", "run", {**dict(manifest), "status": "running"})
        self.write_json("input", "source_record", source_record)
        self.write_json("input", "problem", problem)

    def update_manifest(self, **updates: Any) -> Path:
        path = self.root / "manifest.json"
        current: dict[str, Any] = {}
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
        current.update(self._value(updates))
        payload = json.dumps(current, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        self._atomic_write(path, payload)
        return path

    def write_condition_json(
        self,
        candidate_hash: str,
        condition_id: str,
        component: str,
        value: Any,
    ) -> Path:
        target = self.condition_dir(candidate_hash, condition_id) / f"{component}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._value(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        self._atomic_write(target, payload)
        return target

    def write_condition_text(
        self,
        candidate_hash: str,
        condition_id: str,
        component: str,
        value: str,
        suffix: str = ".txt",
    ) -> Path:
        target = self.condition_dir(candidate_hash, condition_id) / f"{component}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(target, value)
        return target

    def write_candidate_timing(
        self,
        candidate_index: int,
        value: Mapping[str, Any],
    ) -> Path:
        target = self.candidate_dir(candidate_index=candidate_index) / "timing.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            self._value(value), ensure_ascii=False, sort_keys=True, indent=2
        ) + "\n"
        self._atomic_write(target, payload)
        return target

    def write_json(self, category: str, name: str, value: Any) -> Path:
        if category == "manifest":
            target = self.root / "manifest.json"
        elif category == "problem":
            target = self.root / "input" / "problem.json"
        elif category == "lineage":
            digest = str(getattr(value, "candidate_hash", name.split("-")[-1]))
            index = int(getattr(value, "structure_index", int(name.split("-")[0])))
            target = self.register_candidate(digest, index) / "lineage.json"
        elif category in {"candidates", "fastcheck", "verdict"}:
            target = self.candidate_dir(candidate_hash=name) / f"{category.removesuffix('s')}.json"
        elif category == "search":
            target = self.root / "search" / f"{name}.json"
        elif category == "dataset_results":
            target = self.root / "result.json"
        elif category == "final":
            target = self.root / f"{name}.json"
        else:
            return super().write_json(category, name, value)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._value(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        self._atomic_write(target, payload)
        return target

    def record_agent_call(
        self,
        *,
        role: str,
        sequence: int,
        prompt_version: str,
        model_id: str,
        parameters: Mapping[str, Any],
        prompt: str,
        response: str = "",
        call_info: Mapping[str, Any] | None = None,
        status: str = "completed",
        error: str | None = None,
    ) -> Path:
        context = self.current_context()
        candidate = self.candidate_dir(
            candidate_hash=context.get("candidate_hash"),
            candidate_index=context.get("candidate_index"),
        )
        condition_id = context.get("condition_id")
        if condition_id and context.get("candidate_hash"):
            base = self.condition_dir(context["candidate_hash"], condition_id)
        else:
            base = candidate
        stage = self._safe_name(str(context.get("stage") or role))
        target = base / stage / "calls" / f"{sequence:04d}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "schema_version": "dynacert-agent-call.v2",
            "status": status,
            "role": role,
            "prompt_version": prompt_version,
            "model_id": model_id,
            "parameters": dict(parameters),
            "call_info": dict(call_info) if call_info else None,
            "prompt": prompt,
            "prompt_hash": content_hash(prompt),
            "response": response,
            "response_hash": content_hash(response) if response else None,
            "error": error,
            "updated_at_utc": datetime.now(UTC).isoformat(),
        }
        payload = json.dumps(self._value(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        self._atomic_write(target, payload)
        return target

    def metrics(self) -> dict[str, Any]:
        calls = []
        for path in self.root.glob("candidates/**/calls/*.json"):
            try:
                calls.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        input_tokens = output_tokens = total_tokens = 0
        llm_seconds = 0.0
        for call in calls:
            info = call.get("call_info") or {}
            usage = info.get("usage") or {}
            input_tokens += int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
            output_tokens += int(
                usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
            )
            total_tokens += int(usage.get("total_tokens", 0) or 0)
            llm_seconds += float(info.get("duration_seconds", 0) or 0)
        if total_tokens == 0:
            total_tokens = input_tokens + output_tokens
        completed_calls = [call for call in calls if call.get("status") == "completed"]
        format_repair_calls = sum(
            (call.get("call_info") or {}).get("request_kind")
            == "json_format_repair"
            for call in completed_calls
        )

        solver_results = []
        for path in self.root.glob("candidates/**/solver/*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if "duration_seconds" in value:
                solver_results.append(value)
        compiler_results = []
        for path in self.root.glob("candidates/**/compiler_attempts/**/result.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if value.get("status") == "completed":
                compiler_results.append(value)
        lean_results = []
        for path in self.root.glob("candidates/**/conditions/*/lean/result.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if "duration_seconds" in value:
                lean_results.append(value)
        fastcheck_results = []
        for path in self.root.glob("candidates/**/fastcheck.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if "duration_seconds" in value:
                fastcheck_results.append(value)
        candidate_timings = []
        for path in self.root.glob("candidates/*/timing.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if "duration_seconds" in value:
                candidate_timings.append(value)
        condition_timings = []
        for path in self.root.glob("candidates/**/conditions/*/timing.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if "duration_seconds" in value:
                condition_timings.append(value)
        lean_compile_seconds = sum(
            float(item.get("duration_seconds", 0) or 0) for item in compiler_results
        )
        solver_query_seconds = sum(
            float(item.get("duration_seconds", 0) or 0) for item in solver_results
        )
        return {
            "schema_version": "dynacert-metrics.v2",
            "total_wall_seconds": time.monotonic() - self._started_monotonic,
            "llm": {
                "calls": len(completed_calls),
                "failed_calls": len([call for call in calls if call.get("status") == "failed"]),
                "json_format_repair_calls": format_repair_calls,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "call_seconds_sum": llm_seconds,
            },
            "lean": {
                "condition_runs": len(lean_results),
                "condition_seconds_sum": sum(
                    float(item.get("duration_seconds", 0) or 0)
                    for item in lean_results
                ),
                "proof_rounds_sum": sum(
                    int(item.get("proof_rounds", 0) or 0) for item in lean_results
                ),
                "name_repair_rounds_sum": sum(
                    int(item.get("name_repair_rounds", 0) or 0)
                    for item in lean_results
                ),
                "agent_call_retries_sum": sum(
                    int(item.get("agent_call_retries", 0) or 0)
                    for item in lean_results
                ),
                "compile_calls": len(compiler_results),
                "compile_seconds_sum": lean_compile_seconds,
            },
            "solvers": {
                "calls": len(solver_results),
                "query_seconds_sum": solver_query_seconds,
            },
            "fastcheck": {
                "calls": len(fastcheck_results),
                "call_seconds_sum": sum(
                    float(item.get("duration_seconds", 0) or 0)
                    for item in fastcheck_results
                ),
            },
            "candidates": {
                "attempted_slots": len(candidate_timings),
                "wall_seconds_sum": sum(
                    float(item.get("duration_seconds", 0) or 0)
                    for item in candidate_timings
                ),
            },
            "conditions": {
                "calls": len(condition_timings),
                "wall_seconds_sum": sum(
                    float(item.get("duration_seconds", 0) or 0)
                    for item in condition_timings
                ),
            },
        }

    def finalize(
        self,
        *,
        status: str,
        result: Any,
        errors: list[str] | tuple[str, ...] = (),
    ) -> None:
        metrics = self.metrics()
        result_value = self._value(result)
        self.write_json("final", "result", {
            "schema_version": "dynacert-result.v2",
            "status": status,
            "record_id": self.record_id,
            "problem_class": self.problem_class,
            "result": result_value,
            "errors": list(errors),
        })
        self.write_json("final", "metrics", metrics)
        self.update_manifest(
            status=status,
            finished_at_utc=datetime.now(UTC).isoformat(),
            total_wall_seconds=metrics["total_wall_seconds"],
        )
        row = {
            "schema_version": "dynacert-index.v2",
            "record_id": self.record_id,
            "problem_class": self.problem_class,
            "run_id": self.run_id,
            "status": status,
            "run_path": str(self.root),
            "candidate_count": len((result_value or {}).get("candidates", []))
            if isinstance(result_value, dict)
            else 0,
            "verification_scope": (
                ((result_value or {}).get("verdict") or {}).get("scope")
                if isinstance(result_value, dict)
                else None
            ),
            "backend_profile": (
                ((result_value or {}).get("verdict") or {}).get("backend_profile")
                if isinstance(result_value, dict)
                else None
            ),
            "total_wall_seconds": metrics["total_wall_seconds"],
            "llm_calls": metrics["llm"]["calls"],
            "llm_failed_calls": metrics["llm"]["failed_calls"],
            "json_format_repair_calls": metrics["llm"]["json_format_repair_calls"],
            "input_tokens": metrics["llm"]["input_tokens"],
            "output_tokens": metrics["llm"]["output_tokens"],
            "total_tokens": metrics["llm"]["total_tokens"],
            "llm_seconds": metrics["llm"]["call_seconds_sum"],
            "fastcheck_calls": metrics["fastcheck"]["calls"],
            "fastcheck_seconds": metrics["fastcheck"]["call_seconds_sum"],
            "candidate_slots": metrics["candidates"]["attempted_slots"],
            "candidate_seconds": metrics["candidates"]["wall_seconds_sum"],
            "condition_calls": metrics["conditions"]["calls"],
            "condition_seconds": metrics["conditions"]["wall_seconds_sum"],
            "lean_compile_calls": metrics["lean"]["compile_calls"],
            "lean_compile_seconds": metrics["lean"]["compile_seconds_sum"],
            "lean_condition_runs": metrics["lean"]["condition_runs"],
            "lean_condition_seconds": metrics["lean"]["condition_seconds_sum"],
            "lean_proof_rounds": metrics["lean"]["proof_rounds_sum"],
            "lean_name_repair_rounds": metrics["lean"]["name_repair_rounds_sum"],
            "lean_agent_call_retries": metrics["lean"]["agent_call_retries_sum"],
            "solver_calls": metrics["solvers"]["calls"],
            "solver_seconds": metrics["solvers"]["query_seconds_sum"],
        }
        with self._index_lock:
            index = self.experiment_root / "index.jsonl"
            index.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.experiment_root / ".index.lock"
            with lock_path.open("a+", encoding="utf-8") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                rows = []
                if index.exists():
                    rows = [
                        json.loads(line)
                        for line in index.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                rows = [item for item in rows if item.get("run_id") != self.run_id]
                rows.append(self._value(row))
                index_payload = "".join(
                    json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                    for item in rows
                )
                self._atomic_write(index, index_payload)
                summary_payload = (
                    json.dumps(rows, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
                )
                self._atomic_write(self.experiment_root / "summary.json", summary_payload)
                csv_path = self.experiment_root / "summary.csv"
                with tempfile.NamedTemporaryFile(
                    "w",
                    dir=csv_path.parent,
                    delete=False,
                    encoding="utf-8",
                    newline="",
                ) as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(row))
                    writer.writeheader()
                    writer.writerows(rows)
                    temporary = Path(handle.name)
                os.replace(temporary, csv_path)
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        self.write_json("final", "index_row", row)


class RecordingTransport:
    def __init__(
        self,
        delegate: AgentTransport,
        store: ArtifactStore,
        *,
        role: str,
        prompt_version: str,
        model_id: str,
        parameters: Mapping[str, Any],
    ) -> None:
        self.delegate = delegate
        self.store = store
        self.role = role
        self.prompt_version = prompt_version
        self.model_id = model_id
        self.parameters = parameters
        self.sequence = 0
        self._lock = threading.Lock()

    def __call__(self, **kwargs: Any) -> str | Mapping[str, Any]:
        called_at = datetime.now(UTC).isoformat()
        request_kind = (
            "json_format_repair"
            if str(kwargs["prompt"]).startswith("Repair only the JSON shape")
            else "primary"
        )
        request_info = {
            "called_at_utc": called_at,
            "request_kind": request_kind,
            "schema_name": kwargs.get("schema_name"),
            "strict": bool(kwargs.get("strict")),
            "message_count": len(kwargs.get("messages") or ()),
        }
        with self._lock:
            sequence = self.sequence
            self.sequence += 1
        self.store.record_agent_call(
            role=self.role,
            sequence=sequence,
            prompt_version=self.prompt_version,
            model_id=self.model_id,
            parameters=self.parameters,
            prompt=kwargs["prompt"],
            status="started",
            call_info=request_info,
        )
        started = time.monotonic()
        try:
            response = self.delegate(**kwargs)
        except Exception as error:
            delegate_info = dict(getattr(self.delegate, "last_call_info", None) or {})
            delegate_info.update(request_info)
            delegate_info["finished_at_utc"] = datetime.now(UTC).isoformat()
            delegate_info.setdefault("duration_seconds", time.monotonic() - started)
            self.store.record_agent_call(
                role=self.role,
                sequence=sequence,
                prompt_version=self.prompt_version,
                model_id=self.model_id,
                parameters=self.parameters,
                prompt=kwargs["prompt"],
                status="failed",
                error=f"{type(error).__name__}: {error}",
                call_info=delegate_info,
            )
            raise
        response_text = response if isinstance(response, str) else canonical_json(response)
        call_info = dict(getattr(self.delegate, "last_call_info", None) or {})
        call_info.update(request_info)
        call_info["finished_at_utc"] = datetime.now(UTC).isoformat()
        self.store.record_agent_call(
            role=self.role,
            sequence=sequence,
            prompt_version=self.prompt_version,
            model_id=self.model_id,
            parameters=self.parameters,
            prompt=kwargs["prompt"],
            response=response_text,
            call_info=call_info,
            status="completed",
        )
        return response


class ReplayTransport:


    def __init__(self, records: list[Mapping[str, Any]]) -> None:
        self.records = records
        self.index = 0

    def __call__(self, **kwargs: Any) -> str:
        if self.index >= len(self.records):
            raise RuntimeError("prompt replay exhausted")
        record = self.records[self.index]
        self.index += 1
        observed = content_hash(kwargs["prompt"])
        if observed != record["prompt_hash"]:
            raise RuntimeError(
                f"prompt replay mismatch at index {self.index - 1}: "
                f"expected {record['prompt_hash']}, got {observed}"
            )
        response = str(record["response"])
        if content_hash(response) != record["response_hash"]:
            raise RuntimeError("recorded response hash mismatch")
        return response
