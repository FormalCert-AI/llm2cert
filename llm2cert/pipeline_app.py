"""Configure and run the certificate pipeline."""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
FRAMEWORK = ROOT / "framework"
sys.path.insert(0, str(FRAMEWORK))

from config import (
    API_KEY,
    BASE_URL,
    JSON_OBJECT_MODE,
    MODEL,
    PROVIDER,
    STRUCTURED_OUTPUTS,
)
from lean_barrier.s06_agent_suite import PromptedAgentSuite
from lean_barrier.s06_agents import (
    MAX_FORMAT_REPAIRS,
    StructuredAgentRunner,
)
from lean_barrier.s06_transport import (
    ChatCompletionsTransport as DeepSeekTransport,
    make_http_transport,
)
from lean_barrier.s15_artifacts import (
    ArtifactStore,
    RecordingTransport,
    RunBundleStore,
)
from lean_barrier.s03_case_io import import_case, resolve_case_path
from lean_barrier.s05_prompts import PROMPT_VERSION, is_indexed_family_problem
from lean_barrier.s02_expressions import content_hash
from lean_barrier.s10_lean_backend import (
    DevelopmentLeanCompiler,
    LeanProofRunner,
    MAX_PROOF_ROUNDS,
    MAX_PROOF_SECONDS,
)
from lean_barrier.s10_lean_runner import MAX_NAME_REPAIR_ROUNDS
from lean_barrier.s10_lean_compiler import RecordingLeanCompiler
from lean_barrier.s07_search import (
    MAX_CANDIDATES as SEARCH_MAX_CANDIDATES,
    MAX_REGENERATIONS,
)
from lean_barrier.s08_fastcheck import (
    ANALYSIS_AND_BOUNDARY_SAMPLES,
    MAX_COUNTEREXAMPLES,
    TOTAL_SAMPLES,
    XI_SAMPLES,
    XU_SAMPLES,
)
from lean_barrier.s17_pipeline import AgentRoles, BarrierPipeline, PipelineConfig
from lean_barrier.s10_lean_runner import LEAN_REPAIR_FEEDBACK_MODES
from lean_barrier.s13_runtime import (
    LocalExecutor,
    DEFAULT_FINALIZATION_RESERVE_SECONDS,
    RunDeadline,
    RunDeadlineExceeded,
    load_local_runtime_manifest,
)
from lean_barrier.s12_smt_backend import (
    SOLVER_TIMEOUT_SECONDS,
    SolverRunner,
)
from lean_barrier.s16_workflow import (
    CandidateVerifier,
    ProofAgentProvider,
    VerificationRouterProvider,
)


THINKING = True
REASONING_EFFORT = "high"
MAX_TOKENS = 16384
MAX_CANDIDATES = SEARCH_MAX_CANDIDATES
SMT_ENABLED = True


SMT_RUNTIME_MANIFEST = Path(
    os.environ.get("DYNACERT_RUNTIME_MANIFEST", str(ROOT / "config" / "runtime.json"))
).expanduser()
RUN_TIMEOUT_SECONDS = 2400.0
FINALIZATION_RESERVE_SECONDS = DEFAULT_FINALIZATION_RESERVE_SECONDS

def _manifest_dimension(problem: Any) -> int | dict[str, Any]:


    family = problem.indexed_family
    if family is not None:
        return {
            "kind": "symbolic",
            "expression": family.state_dimension,
            "parameter": family.parameter.name,
            "parameter_domain": family.parameter.domain,
        }
    assert problem.system is not None
    return len(problem.system.state_vars)


ROLE_PARAMS: dict[str, dict[str, Any]] = {
    "synthesis": {
        "thinking": True,
        "thinking_budget": 16000,
        "call_timeout_seconds": 300.0,
    },
    "verification_router": {
        "thinking": True,
        "thinking_budget": 4096,
        "call_timeout_seconds": 120.0,
    },
    "lean": {
        "thinking": True,
        "thinking_budget": 16000,
        "call_timeout_seconds": 600.0,
    },
}


def _effective_role_parameters(role: str) -> dict[str, Any]:
    params = {
        "thinking": THINKING,
        "reasoning_effort": REASONING_EFFORT,
        "max_tokens": MAX_TOKENS,
    }
    params.update(ROLE_PARAMS.get(role, {}))
    return params


def _select_executable_record(raw: dict[str, Any], record_id: str | None) -> dict[str, Any]:


    if "records" not in raw:
        if record_id is not None:
            raise ValueError("record_id is only valid for an executable dataset")
        return raw
    if record_id is None:
        raise ValueError("an executable dataset path requires a record_id")
    matches = [record for record in raw["records"] if record.get("record_id") == record_id]
    if len(matches) != 1:
        raise ValueError(f"expected one executable record {record_id!r}, found {len(matches)}")
    return matches[0]


def load_case(
    path: Path | None = None,
    *,
    bench_id: int = 24,
    record_id: str | None = None,
):
    problem, _, _ = load_case_record(path, bench_id=bench_id, record_id=record_id)
    return problem


def load_case_record(
    path: Path | None = None,
    *,
    bench_id: int = 24,
    record_id: str | None = None,
):
    if path is None:
        raise ValueError("provide a case path or the executable dataset and record ID")
    case_path = Path(path)
    if not case_path.is_absolute():
        case_path = ROOT / case_path
    case_path = resolve_case_path(case_path)
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    raw = _select_executable_record(payload, record_id)
    return import_case(raw, bench_id=bench_id).problem, raw, case_path


def make_roles(
    store: ArtifactStore,
    *,
    contextual_local_repair: bool = False,
    deadline: RunDeadline | None = None,
) -> AgentRoles:
    native_structured_outputs = STRUCTURED_OUTPUTS and PROVIDER != "claude"

    def runner(role: str) -> StructuredAgentRunner:
        params = _effective_role_parameters(role)
        http = make_http_transport(
            provider=PROVIDER,
            api_key=API_KEY,
            base_url=BASE_URL,
            model=MODEL,
            deadline=deadline,
            json_object=JSON_OBJECT_MODE if PROVIDER == "gpt" else None,
            json_schema=native_structured_outputs,
            **params,
        )
        transport = RecordingTransport(
            http,
            store,
            role=role,
            prompt_version=PROMPT_VERSION,
            model_id=MODEL,
            parameters={
                "provider": PROVIDER,
                "json_object_mode": (
                    JSON_OBJECT_MODE if PROVIDER == "gpt" else PROVIDER == "deepseek"
                ),
                "structured_outputs": native_structured_outputs,
                **params,
            },
        )
        return StructuredAgentRunner(
            transport,
            supports_structured_outputs=native_structured_outputs,
        )

    suite = PromptedAgentSuite(
        synthesis_runner=runner("synthesis"),
        verification_router_runner=runner("verification_router"),
        lean_runner=runner("lean"),
        contextual_local_repair=contextual_local_repair,
    )
    base = AgentRoles.from_suite(suite)
    if not isinstance(store, RunBundleStore):
        return base

    def synthesize(problem, context):
        with store.scope(candidate_index=context.structure_index, stage="synthesis"):
            return base.synthesizer(problem, context)

    def route(condition, capabilities):
        with store.scope(
            candidate_hash=condition.candidate_hash,
            condition_id=condition.condition_id,
            stage="routing",
        ):
            return base.verification_router(condition, capabilities)

    def proof_provider(problem, candidate, condition, locked, mode):
        prove = base.lean_prover(problem, candidate, condition, locked, mode)

        def scoped_prove(round_index, previous, diagnostics):
            with store.scope(
                candidate_hash=condition.candidate_hash,
                condition_id=condition.condition_id,
                stage="lean",
            ):
                return prove(round_index, previous, diagnostics)

        return scoped_prove

    return AgentRoles(
        synthesizer=synthesize,
        verification_router=route,
        lean_prover=proof_provider,
    )


def make_solver_runner(*, deadline: RunDeadline | None = None) -> SolverRunner | None:


    if not SMT_ENABLED or not SMT_RUNTIME_MANIFEST.exists():
        return None
    manifest = load_local_runtime_manifest(SMT_RUNTIME_MANIFEST)
    return SolverRunner(manifest, LocalExecutor(), deadline=deadline)


def make_lean_runner(
    *,
    deadline: RunDeadline | None = None,
    store: RunBundleStore | None = None,
) -> LeanProofRunner:
    compiler = DevelopmentLeanCompiler(ROOT / "formalization" / "lean")
    if store is not None:
        compiler = RecordingLeanCompiler(compiler, store)
    return LeanProofRunner(compiler, deadline=deadline)


def _unused_proof_agent(*_args: object):
    return None


def _problem_class(task_type: str) -> str:
    mapping = {
        "stability": "P1_stability",
        "roa": "P2_roa",
        "invariant": "P3_invariant",
        "safety": "P4_safety",
    }
    return mapping[task_type]


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)


def _take_value_option(args: list[str], name: str) -> tuple[list[str], str | None]:


    remaining: list[str] = []
    value: str | None = None
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == name:
            if value is not None:
                raise SystemExit(f"{name} may be supplied only once")
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise SystemExit(f"{name} requires a value")
            value = args[index + 1]
            index += 2
            continue
        if argument.startswith(f"{name}="):
            if value is not None:
                raise SystemExit(f"{name} may be supplied only once")
            value = argument.split("=", 1)[1]
            index += 1
            continue
        remaining.append(argument)
        index += 1
    if value is not None and not value.strip():
        raise SystemExit(f"{name} requires a non-empty value")
    return remaining, value


def _git_metadata() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT.parent,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT.parent,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        return {
            "git_commit": commit,
            "git_dirty": bool(dirty),
            "git_dirty_hash": hashlib.sha256(dirty.encode()).hexdigest(),
        }
    except (OSError, subprocess.SubprocessError):
        return {"git_commit": None, "git_dirty": None, "git_dirty_hash": None}


def _source_snapshot() -> dict[str, Any]:


    patterns = (
        "pipeline_app.py",
        "config.py",
        "run_dataset.py",
        "run_pipeline.py",
        "framework/lean_barrier/**/*.py",
        "formalization/lean/**/*.lean",
        "formalization/lean/lakefile.toml",
        "formalization/lean/lake-manifest.json",
    )
    files = sorted(
        {
            path.resolve()
            for pattern in patterns
            for path in ROOT.glob(pattern)
            if path.is_file()
        }
    )
    if SMT_RUNTIME_MANIFEST.is_file():
        files.append(SMT_RUNTIME_MANIFEST.resolve())
    files = sorted(set(files))
    repository_root = ROOT.parent.resolve()
    entries = []
    for path in files:
        try:
            display_path = str(path.relative_to(repository_root))
        except ValueError:


            display_path = str(path)
        entries.append(
            {
                "path": display_path,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
        )
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": "dynacert-source-snapshot.v1",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "file_count": len(entries),
        "files": entries,
    }


def make_verifier(
    store: ArtifactStore | None = None,
    *,
    solver_runner: SolverRunner | None = None,
    router: VerificationRouterProvider | None = None,
    lean_runner: LeanProofRunner | None | object = ...,
    proof_agent_provider: ProofAgentProvider | None = None,
    kernel_first: bool = False,
    deadline: RunDeadline | None = None,
) -> CandidateVerifier:


    roles = make_roles(store, deadline=deadline) if store is not None else None
    if lean_runner is ...:
        lean_runner = make_lean_runner(
            deadline=deadline,
            store=store if isinstance(store, RunBundleStore) else None,
        )
    if router is None:
        if roles is None:
            raise ValueError("make_verifier requires router when store is omitted")
        router = roles.verification_router
    if proof_agent_provider is None:
        if roles is None:
            proof_agent_provider = _unused_proof_agent
        else:
            proof_agent_provider = roles.lean_prover
    return CandidateVerifier(
        solver_runner=solver_runner,
        lean_runner=lean_runner,
        verification_router_provider=router,
        proof_agent_provider=proof_agent_provider,
        common_core_audited=True,
        kernel_first=kernel_first,
        artifact_store=store,
        deadline=deadline,
    )


USAGE = (
    "usage: pipeline_app.py [CASE.json [RECORD_ID]] "
    "[--contextual-local-repair] [--kernel-first] [--smt-only] [--lean-only] "
    "[--lean-repair-feedback MODE] [--experiment-id ID] [--output-root DIR]"
)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if "-h" in args or "--help" in args:
        print(USAGE)
        return
    if not API_KEY or API_KEY.startswith("<REDACTED>"):
        raise SystemExit("set DYNACERT_API_KEY (see .env.example) to run model-backed cases")
    args, experiment_id_override = _take_value_option(args, "--experiment-id")
    args, output_root_override = _take_value_option(args, "--output-root")
    args, lean_repair_feedback = _take_value_option(args, "--lean-repair-feedback")
    lean_repair_feedback = lean_repair_feedback or "processed"
    if lean_repair_feedback not in LEAN_REPAIR_FEEDBACK_MODES:
        raise SystemExit(
            "--lean-repair-feedback must be one of "
            + ", ".join(LEAN_REPAIR_FEEDBACK_MODES)
        )
    contextual_local_repair = "--contextual-local-repair" in args
    args = [arg for arg in args if arg != "--contextual-local-repair"]
    kernel_first = "--kernel-first" in args
    args = [arg for arg in args if arg != "--kernel-first"]
    smt_only = "--smt-only" in args
    args = [arg for arg in args if arg != "--smt-only"]
    lean_only = "--lean-only" in args
    args = [arg for arg in args if arg != "--lean-only"]
    if smt_only and lean_only:
        raise SystemExit("--smt-only and --lean-only cannot be combined")
    if not 1 <= len(args) <= 2:
        raise SystemExit(USAGE)
    case_path = Path(args[0])
    record_id = args[1] if len(args) == 2 else None
    problem, source_record, resolved_case_path = load_case_record(
        case_path, record_id=record_id
    )
    policy = "contextual" if contextual_local_repair else "baseline"
    kernel_tag = "-kernel-first" if kernel_first else ""
    smt_tag = "-onlysmt" if smt_only else ""
    lean_tag = "-onlylean" if lean_only else ""
    feedback_tag = (
        f"-{lean_repair_feedback.replace('_', '-')}"
        if lean_repair_feedback != "processed"
        else ""
    )
    record_key = record_id or problem.problem_id
    experiment_prefix = "dynacertbench" if record_id is not None else "case"
    experiment_id = _safe_id(
        experiment_id_override
        or f"{experiment_prefix}-{MODEL}-{policy}{kernel_tag}{smt_tag}{lean_tag}{feedback_tag}-v2"
    )
    experiment_root = (
        Path(output_root_override).resolve()
        if output_root_override
        else ROOT.parent / "benchmark" / "experiments" / experiment_id
    )
    run_id = (
        "run-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid4().hex[:8]
    )
    store = RunBundleStore(
        experiment_root,
        problem_class=_problem_class(problem.task_type.value),
        record_id=record_key,
        run_id=run_id,
    )
    deadline = RunDeadline(RUN_TIMEOUT_SECONDS)
    source_sha256 = hashlib.sha256(resolved_case_path.read_bytes()).hexdigest()
    source_snapshot = _source_snapshot()
    strategy = {
        "policy": policy,
        "kernel_first": kernel_first,
        "smt_only": smt_only,
        "lean_only": lean_only,
        "lean_repair_feedback": lean_repair_feedback,
        "contextual_local_repair": contextual_local_repair,
        "json_object_mode": JSON_OBJECT_MODE,
        "structured_outputs": STRUCTURED_OUTPUTS and PROVIDER != "claude",
        "max_candidates": MAX_CANDIDATES,
        "candidate_parse_regenerations": MAX_REGENERATIONS,
        "json_format_repairs": MAX_FORMAT_REPAIRS,
        "lean_proof_rounds": MAX_PROOF_ROUNDS,
        "lean_name_repair_rounds": MAX_NAME_REPAIR_ROUNDS,
        "smt_enabled": SMT_ENABLED,
        "fastcheck": {
            "initial_samples": XI_SAMPLES,
            "unsafe_samples": XU_SAMPLES,
            "analysis_and_boundary_samples": ANALYSIS_AND_BOUNDARY_SAMPLES,
            "total_samples": TOTAL_SAMPLES,
            "max_counterexamples": MAX_COUNTEREXAMPLES,
        },
    }
    model_parameters = {
        role: _effective_role_parameters(role)
        for role in ("synthesis", "verification_router", "lean")
    }
    timeouts = {
        "problem_run_seconds": RUN_TIMEOUT_SECONDS,
        "finalization_reserve_seconds": FINALIZATION_RESERVE_SECONDS,
        "synthesis_llm_call_seconds": ROLE_PARAMS["synthesis"]["call_timeout_seconds"],
        "router_llm_call_seconds": ROLE_PARAMS["verification_router"][
            "call_timeout_seconds"
        ],
        "lean_llm_call_seconds": ROLE_PARAMS["lean"]["call_timeout_seconds"],
        "lean_condition_seconds": MAX_PROOF_SECONDS,
        "solver_query_seconds": SOLVER_TIMEOUT_SECONDS,
    }
    transport_info = {
        "base_url": BASE_URL,
        "proxy_enabled": bool(os.getenv("DYNACERT_HTTP_PROXY", "").strip()),
    }
    store.initialize(
        experiment={
            "schema_version": "dynacert-experiment.v2",
            "experiment_id": experiment_id,
            "dataset_path": str(resolved_case_path) if record_id is not None else None,
            "dataset_sha256": source_sha256 if record_id is not None else None,
            "provider": PROVIDER,
            "model": MODEL,
            "model_parameters": model_parameters,
            "transport": transport_info,
            "strategy": strategy,
            "timeouts": timeouts,
            "source_tree_sha256": source_snapshot["sha256"],
        },
        manifest={
            "schema_version": RunBundleStore.schema_version,
            "experiment_id": experiment_id,
            "record_id": record_key,
            "problem_id": problem.problem_id,
            "problem_class": _problem_class(problem.task_type.value),
            "dynamics_kind": (
                problem.indexed_family.time_domain
                if problem.indexed_family is not None
                else problem.system.kind.value
            ),
            "dimension": _manifest_dimension(problem),
            "run_id": run_id,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_path": str(resolved_case_path),
            "source_sha256": source_sha256,
            "provider": PROVIDER,
            "model": MODEL,
            "model_parameters": model_parameters,
            "transport": transport_info,
            "strategy": strategy,
            "timeouts": timeouts,
            "source_tree_sha256": source_snapshot["sha256"],
            **_git_metadata(),
        },
        source_record=source_record,
        problem=problem,
    )
    store.write_json("input", "source_snapshot", source_snapshot)
    if is_indexed_family_problem(problem):
        assert problem.indexed_family is not None
        store.write_json(
            "input",
            "symbolic_family_contract",
            {
                "problem_id": problem.problem_id,
                "dimension": _manifest_dimension(problem),
                "contract_sha256": content_hash(problem.indexed_family),
                "contract": problem.indexed_family,
                "verification_route": "direct_lean",
                "finite_importer_instance_used_for_theorem": False,
            },
        )
    compiler = RecordingLeanCompiler(
        DevelopmentLeanCompiler(ROOT / "formalization" / "lean"), store
    )
    pipeline = BarrierPipeline(
        roles=make_roles(
            store,
            contextual_local_repair=contextual_local_repair,
            deadline=deadline,
        ),
        compiler=compiler,
        solver_runner=make_solver_runner(deadline=deadline),
        store=store,
        config=PipelineConfig(
            max_candidates=MAX_CANDIDATES,
            kernel_first=kernel_first,
            smt_only=smt_only,
            lean_only=lean_only,
            lean_repair_feedback=lean_repair_feedback,
        ),
        deadline=deadline,
    )
    try:
        result = pipeline.run(problem)
    except RunDeadlineExceeded as error:
        store.finalize(status="timed_out", result=None, errors=[str(error)])
        print("status= timed_out")
        print("errors=", [str(error)])
        print("artifact_dir=", store.root)
        return
    except Exception as error:
        store.finalize(
            status="infrastructure_error",
            result=None,
            errors=[f"{type(error).__name__}: {error}"],
        )
        raise
    timed_out = deadline.expired() or any(
        "deadline exhausted" in error for error in result.errors
    )
    final_status = "timed_out" if timed_out else result.status.value
    store.finalize(status=final_status, result=result, errors=result.errors)
    print("status=", final_status)
    print("candidates=", len(result.candidates))
    print("errors=", list(result.errors))
    print("artifact_dir=", store.root)


if __name__ == "__main__":
    main()
