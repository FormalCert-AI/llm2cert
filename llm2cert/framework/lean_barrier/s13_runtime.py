"""Configure local executables and enforce execution deadlines."""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .s01_models import Backend

IMMUTABLE_IMAGE = re.compile(r"(?:@sha256:|^sha256:)[0-9a-f]{64}$")
DEFAULT_FINALIZATION_RESERVE_SECONDS = 60.0


class RunDeadlineExceeded(TimeoutError):
    pass


class RunDeadline:


    def __init__(self, timeout_seconds: float) -> None:
        if timeout_seconds <= 0:
            raise ValueError("run timeout must be positive")
        self.timeout_seconds = float(timeout_seconds)
        self.started = time.monotonic()
        self.deadline = self.started + self.timeout_seconds

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def remaining(self, *, reserve_seconds: float = 0.0) -> float:
        return max(0.0, self.deadline - time.monotonic() - reserve_seconds)

    def expired(self, *, reserve_seconds: float = 0.0) -> bool:
        return self.remaining(reserve_seconds=reserve_seconds) <= 0

    def cap(self, local_timeout: float, *, reserve_seconds: float = 0.0) -> float:
        remaining = self.remaining(reserve_seconds=reserve_seconds)
        if remaining <= 0:
            raise RunDeadlineExceeded("single-problem wall-clock budget exhausted")
        return max(0.1, min(float(local_timeout), remaining))

    def check(self, *, reserve_seconds: float = 0.0) -> None:
        if self.expired(reserve_seconds=reserve_seconds):
            raise RunDeadlineExceeded("single-problem wall-clock budget exhausted")


class RuntimeLockError(RuntimeError):
    pass


class LockedRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    expected_version: str
    image: str
    version_command: tuple[str, ...]
    query_command: tuple[str, ...]

    @model_validator(mode="after")
    def immutable_image(self) -> LockedRuntime:
        if not IMMUTABLE_IMAGE.search(self.image):
            raise ValueError("image must use @sha256:<digest> or a local sha256:<id>")
        return self


class RuntimeLock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^lean-barrier.runtime-lock.v1$")
    runtimes: dict[str, LockedRuntime]


class LocalRuntime(BaseModel):


    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    expected_version: str
    transport: Literal["host", "docker"]
    version_command: tuple[str, ...]
    query_command: tuple[str, ...] = ()
    image: str | None = None
    platform: str | None = None

    @model_validator(mode="after")
    def transport_fields(self) -> LocalRuntime:
        if not self.version_command:
            raise ValueError("version_command cannot be empty")
        if self.transport == "host":
            if self.image is not None or self.platform is not None:
                raise ValueError("host runtime cannot declare image or platform")
            for command in (self.version_command, self.query_command):
                if command and not Path(command[0]).is_absolute():
                    raise ValueError("host commands must start with an absolute path")
        else:
            if self.image is None or not IMMUTABLE_IMAGE.search(self.image):
                raise ValueError("docker runtime requires an immutable image digest")
        return self


class LocalRuntimeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^lean-barrier.local-runtime.v1$")
    profile_name: str
    runtimes: dict[str, LocalRuntime]


type RuntimeEntry = LockedRuntime | LocalRuntime
type RuntimeManifest = RuntimeLock | LocalRuntimeManifest


def load_runtime_lock(path: str | Path) -> RuntimeLock:
    try:
        return RuntimeLock.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as error:
        raise RuntimeLockError(f"invalid or unlocked runtime lock: {error}") from error


def load_local_runtime_manifest(path: str | Path) -> LocalRuntimeManifest:
    try:
        return LocalRuntimeManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as error:
        raise RuntimeLockError(f"invalid local runtime manifest: {error}") from error


@dataclass(frozen=True)
class ExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


class Executor(Protocol):
    def version(self, runtime: RuntimeEntry, *, timeout_seconds: float = 10) -> ExecutionResult: ...

    def query(
        self,
        runtime: RuntimeEntry,
        payload: str,
        *,
        timeout_seconds: float,
    ) -> ExecutionResult: ...


class LocalExecutor:


    formal = True

    def __init__(self, docker_binary: str = "docker") -> None:
        self.docker_binary = docker_binary

    def _run(
        self,
        runtime: RuntimeEntry,
        command: tuple[str, ...],
        payload: str | None,
        timeout_seconds: float,
    ) -> ExecutionResult:
        if isinstance(runtime, LockedRuntime) or runtime.transport == "docker":
            image = runtime.image
            if image is None:
                raise RuntimeLockError("docker runtime has no image")
            argv = [self.docker_binary, "run", "--rm"]
            if isinstance(runtime, LocalRuntime) and runtime.platform:
                argv.extend(("--platform", runtime.platform))
            argv.extend(
                (
                    "--network=none",
                    "--read-only",
                    "--pids-limit=256",
                    "--memory=2g",
                    "--cpus=1",
                    "--tmpfs=/tmp:rw,noexec,nosuid,size=256m",
                    "-i",
                    image,
                    *command,
                )
            )
        else:
            argv = list(command)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                input=payload,
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
            return ExecutionResult(
                124,
                stdout,
                stderr,
                time.monotonic() - started,
                timed_out=True,
            )

    def version(self, runtime: RuntimeEntry, *, timeout_seconds: float = 10) -> ExecutionResult:
        return self._run(runtime, runtime.version_command, None, timeout_seconds)

    def query(
        self,
        runtime: RuntimeEntry,
        payload: str,
        *,
        timeout_seconds: float,
    ) -> ExecutionResult:
        if not runtime.query_command:
            raise RuntimeLockError(f"{runtime.name} has no query command")
        return self._run(runtime, runtime.query_command, payload, timeout_seconds)


EXPECTED_SOLVER_VERSIONS = {
    Backend.Z3: "4.15.1",
    Backend.CVC5: "1.3.1",
    Backend.YICES: "2.6.4",
    Backend.DREAL: "4.21.06.2",
}
EXPECTED_LEAN_VERSION = "4.32.2"


def has_exact_version_token(output: str, expected: str) -> bool:


    return (
        re.search(
            rf"(?<![0-9.]){re.escape(expected)}(?![0-9.])",
            output,
        )
        is not None
    )


def runtime_for_backend(lock: RuntimeManifest, backend: Backend) -> RuntimeEntry:
    try:
        runtime = lock.runtimes[backend.value]
    except KeyError as error:
        raise RuntimeLockError(f"runtime lock has no {backend.value} entry") from error
    if isinstance(lock, RuntimeLock):
        expected = EXPECTED_SOLVER_VERSIONS[backend]
        if runtime.expected_version != expected:
            raise RuntimeLockError(
                f"{backend.value} lock expects {runtime.expected_version}; "
                f"paper profile requires {expected}"
            )
    if not runtime.query_command:
        raise RuntimeLockError(f"runtime manifest has no query command for {backend.value}")
    return runtime
