"""Compile Lean sources and record compiler results."""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .s13_runtime import ExecutionResult
from .s02_expressions import content_hash
from .s15_artifacts import RunBundleStore


class LeanCompiler(Protocol):
    formal: bool

    def compile(self, source: str, *, timeout_seconds: float) -> ExecutionResult: ...


class DevelopmentLeanCompiler:


    formal = True

    def __init__(self, lean_project: str | Path) -> None:
        self.lean_project = Path(lean_project).resolve()

    @property
    def module_cache_root(self) -> Path:
        return self.lean_project.parent / "work" / "lean-module-cache"

    def _module_object_path(self, module_name: str) -> Path:
        relative = Path(*module_name.split("."))
        return (
            self.lean_project / ".lake" / "build" / "lib" / "lean" / relative
        ).with_suffix(".olean")

    def _cached_module_is_current(self, object_path: Path, source: str) -> bool:


        object_mtime = object_path.stat().st_mtime_ns
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped.startswith("import "):
                continue
            for dependency in stripped.removeprefix("import ").split():
                dependency_path = self._module_object_path(dependency)
                if (
                    not dependency_path.is_file()
                    or dependency_path.stat().st_mtime_ns > object_mtime
                ):
                    return False
        return True

    def compile_module(
        self,
        module_name: str,
        source: str,
        *,
        timeout_seconds: float,
    ) -> ExecutionResult:


        started = time.monotonic()
        relative = Path(*module_name.split("."))
        source_path = self.module_cache_root / relative.with_suffix(".lean")
        audit_path = self.module_cache_root / relative.with_suffix(".audit")
        object_path = self._module_object_path(module_name)
        source_digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if source_path.is_file() and object_path.is_file() and audit_path.is_file():
            cached_source = source_path.read_text(encoding="utf-8")
            cached_audit = audit_path.read_text(encoding="utf-8")
            if (
                cached_source == source
                and cached_audit.startswith(source_digest + "\n")
                and self._cached_module_is_current(object_path, source)
            ):
                return ExecutionResult(
                    0,
                    cached_audit.split("\n", 1)[1],
                    f"[cached Lean module {module_name}]",
                    time.monotonic() - started,
                )

        source_path.parent.mkdir(parents=True, exist_ok=True)
        object_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(source, encoding="utf-8")
        try:
            completed = subprocess.run(
                [
                    "lake",
                    "env",
                    "lean",
                    "-R",
                    str(self.module_cache_root),
                    "-o",
                    str(object_path),
                    str(source_path),
                ],
                cwd=self.lean_project,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            if completed.returncode == 0:
                audit_path.write_text(
                    source_digest + "\n" + completed.stdout + "\n" + completed.stderr,
                    encoding="utf-8",
                )
            else:
                object_path.unlink(missing_ok=True)
                audit_path.unlink(missing_ok=True)
            return ExecutionResult(
                completed.returncode,
                completed.stdout,
                completed.stderr,
                time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as error:
            object_path.unlink(missing_ok=True)
            audit_path.unlink(missing_ok=True)
            stdout = (
                error.stdout.decode() if isinstance(error.stdout, bytes) else error.stdout or ""
            )
            stderr = (
                error.stderr.decode() if isinstance(error.stderr, bytes) else error.stderr or ""
            )
            return ExecutionResult(124, stdout, stderr, time.monotonic() - started, True)

    def compile(self, source: str, *, timeout_seconds: float) -> ExecutionResult:
        started = time.monotonic()
        build_dir = self.lean_project.parent / "work" / "lean-dev"
        build_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".lean", prefix="Proof_", dir=build_dir, delete=False, encoding="utf-8"
        ) as handle:
            handle.write(source)
            source_path = Path(handle.name)
        try:
            completed = subprocess.run(
                ["lake", "env", "lean", str(source_path)],
                cwd=self.lean_project,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            return ExecutionResult(
                completed.returncode,
                completed.stdout,
                completed.stderr,
                time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as error:
            stdout = (
                error.stdout.decode() if isinstance(error.stdout, bytes) else error.stdout or ""
            )
            stderr = (
                error.stderr.decode() if isinstance(error.stderr, bytes) else error.stderr or ""
            )
            return ExecutionResult(124, stdout, stderr, time.monotonic() - started, True)
        finally:
            source_path.unlink(missing_ok=True)


class RecordingLeanCompiler:


    def __init__(self, delegate: DevelopmentLeanCompiler, store: RunBundleStore) -> None:
        self.delegate = delegate
        self.store = store
        self.formal = delegate.formal
        self.lean_project = delegate.lean_project
        self._sequences: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    @property
    def module_cache_root(self) -> Path:
        return self.delegate.module_cache_root

    def _next(self, candidate_hash: str, condition_id: str) -> int:
        key = (candidate_hash, condition_id)
        with self._lock:
            sequence = self._sequences.get(key, 0)
            self._sequences[key] = sequence + 1
        return sequence

    def _run(
        self,
        source: str,
        *,
        timeout_seconds: float,
        module_name: str | None = None,
    ) -> ExecutionResult:
        context = self.store.current_context()
        candidate_hash = context.get("candidate_hash")
        condition_id = context.get("condition_id")
        if not candidate_hash or not condition_id:
            if module_name is None:
                return self.delegate.compile(source, timeout_seconds=timeout_seconds)
            return self.delegate.compile_module(
                module_name, source, timeout_seconds=timeout_seconds
            )
        sequence = self._next(candidate_hash, condition_id)
        component = f"lean/compiler_attempts/{sequence:02d}"
        started_at_utc = datetime.now(UTC).isoformat()
        self.store.write_condition_text(
            candidate_hash,
            condition_id,
            component + "/source",
            source,
            ".lean",
        )
        self.store.write_condition_json(
            candidate_hash,
            condition_id,
            component + "/result",
            {
                "schema_version": "dynacert-lean-compile.v2",
                "status": "started",
                "source_hash": content_hash(source),
                "module_name": module_name,
                "timeout_seconds": timeout_seconds,
                "started_at_utc": started_at_utc,
            },
        )
        try:
            result = (
                self.delegate.compile(source, timeout_seconds=timeout_seconds)
                if module_name is None
                else self.delegate.compile_module(
                    module_name, source, timeout_seconds=timeout_seconds
                )
            )
        except Exception as error:
            self.store.write_condition_json(
                candidate_hash,
                condition_id,
                component + "/result",
                {
                    "schema_version": "dynacert-lean-compile.v2",
                    "status": "failed",
                    "source_hash": content_hash(source),
                    "module_name": module_name,
                    "error": f"{type(error).__name__}: {error}",
                    "started_at_utc": started_at_utc,
                    "finished_at_utc": datetime.now(UTC).isoformat(),
                },
            )
            raise
        self.store.write_condition_json(
            candidate_hash,
            condition_id,
            component + "/result",
            {
                "schema_version": "dynacert-lean-compile.v2",
                "status": "completed",
                "source_hash": content_hash(source),
                "module_name": module_name,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_seconds": result.duration_seconds,
                "timed_out": result.timed_out,
                "started_at_utc": started_at_utc,
                "finished_at_utc": datetime.now(UTC).isoformat(),
            },
        )
        return result

    def compile(self, source: str, *, timeout_seconds: float) -> ExecutionResult:
        return self._run(source, timeout_seconds=timeout_seconds)

    def compile_module(
        self,
        module_name: str,
        source: str,
        *,
        timeout_seconds: float,
    ) -> ExecutionResult:
        return self._run(
            source,
            timeout_seconds=timeout_seconds,
            module_name=module_name,
        )
