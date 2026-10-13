"""Run model-assisted Lean proof generation and repair."""
from __future__ import annotations

import hashlib
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .s01_models import LeanAgentOutput, LeanAgentStatus, LeanAttempt, LeanResult
from .s02_expressions import content_hash
from .s10_lean_compiler import LeanCompiler
from .s10_lean_gen import LockedTheorem
from .s13_runtime import DEFAULT_FINALIZATION_RESERVE_SECONDS, RunDeadline

MAX_PROOF_ROUNDS = 6


MAX_NAME_REPAIR_ROUNDS = 3
MAX_PROOF_SECONDS = 900.0
MAX_DEFINITION_PREFLIGHT_SECONDS = 120.0
MAX_CACHED_DECLARATION_LINES = 120
MAX_CACHED_DECLARATION_CHARS = 8000
MAX_ERROR_BLOCKS = 8
MAX_ERROR_CHARS = 4000

FATAL_LEAN = re.compile(r"\b(axiom|unsafe|import|namespace|section|end)\b", re.IGNORECASE)

SORRY_LEAN = re.compile(r"\b(sorry|admit)\b", re.IGNORECASE)
_ERROR_START = re.compile(r"^(?:.*?:\d+:\d+:\s+)?error:", re.MULTILINE | re.IGNORECASE)
_WARN_OR_INFO = re.compile(r"^(?:.*?:\d+:\d+:\s+)?(?:warning|info):", re.IGNORECASE)
_AXIOM_PRINT = re.compile(
    r"'[^']+' (?:does not depend on any axioms|depends on axioms:\s*\[[^\]]*\])",
    re.DOTALL,
)
CORE_ALLOWED_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
LEAN_REPAIR_FEEDBACK_MODES = ("processed", "verbatim", "failure_only")
FAILURE_ONLY_SIGNAL = "Lean compilation failed."
_FIX_ALL = (
    "Fix every error below in this one proof body. Do not change the locked statement.\n\n"
)
_SORRY_MSG = "sorry/admit is not allowed. Replace it with a complete proof."
_RESTORE_MSG = "Locked statement was restored. Only submit a proof_body."
_AXIOM_PRINT_MSG = (
    "The proof compiled but #print axioms output was missing. Submit the same proof body again."
)
_CE_POINT_REQUIRED = (
    "You claimed the locked theorem is false but gave no counterexample field. "
    "Either return cannot_complete with counterexample = {variable: exact rational} "
    "so the harness can replay it, or keep proving."
)
_CE_REJECTED = (
    "Your claimed counterexample was replayed numerically and does NOT satisfy the "
    "counterexample query: {detail}. The locked theorem is not refuted by that point. "
    "Do not trust mental arithmetic; keep proving the locked statement."
)
_SURRENDER_REJECTED = (
    "cannot_complete is not accepted because the locked theorem has not been "
    "refuted. Continue proving the exact locked theorem. "
    "Do not discuss unrelated V/barrier/derivative conditions."
)
_REAL_NAME_GATE = (
    "Hard Real.* declaration gate: the proof was not elaborated. Every qualified "
    "Real.* name in the submitted helpers/body was checked directly by the pinned "
    "Lean environment, and at least one name is unknown. Do not guess a replacement "
    "Real.* name. On the next turn, use a declaration returned by the local source "
    "search, reuse an already verified name, or prove the needed fact from those "
    "ingredients in helper_lemmas. Any newly introduced Real.* name will be checked "
    "by this same gate before the full proof compile.\n\n"
)
_NEGATED_REFUTATION = re.compile(
    r"\b(?:not|never|no)\s+(?:been\s+)?(?:refut\w*|counterexamples?)\b",
    re.IGNORECASE,
)
_CLAIMS_FALSE = re.compile(
    r"\b(?:false|not\s+true|counterexamples?|refut\w*|disprov\w*)\b",
    re.IGNORECASE,
)


CounterexampleChecker = Callable[[dict[str, str]], tuple[bool, str]]

ProofAgent = Callable[[int, str, str], LeanAgentOutput]


def agent_repair_feedback(mode: str, *, processed: str, raw: str = "") -> str:


    if mode not in LEAN_REPAIR_FEEDBACK_MODES:
        raise ValueError(f"unsupported lean repair feedback: {mode!r}")
    if not processed and not raw:
        return ""
    if mode == "failure_only":
        return FAILURE_ONLY_SIGNAL
    if mode == "verbatim":
        return raw or processed
    return processed


def _claims_locked_theorem_false(reason: str) -> bool:


    without_negated_refutations = _NEGATED_REFUTATION.sub("", reason)
    return _CLAIMS_FALSE.search(without_negated_refutations) is not None


def _fatal_token(fragment: str) -> str | None:
    match = FATAL_LEAN.search(fragment)
    if match:
        return f"forbidden Lean token: {match.group(1)}"
    return None


def _has_sorry(fragment: str) -> bool:
    return SORRY_LEAN.search(fragment) is not None


def _strip_locked_redefinition(fragment: str, theorem_name: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf"^[ \t]*(?:theorem|lemma|def)\s+{re.escape(theorem_name)}\b[^\n]*"
        rf"(?:\n(?![ \t]*(?:theorem|lemma|def)\s).*)*",
        re.MULTILINE,
    )
    stripped, count = pattern.subn("", fragment)
    return stripped.strip(), count > 0


def _restore_locked_statement(
    output: LeanAgentOutput, theorem_name: str
) -> tuple[LeanAgentOutput, bool]:
    helpers: list[str] = []
    restored = False
    for lemma in output.helper_lemmas:
        cleaned, changed = _strip_locked_redefinition(lemma, theorem_name)
        restored = restored or changed
        if cleaned:
            helpers.append(cleaned)
    body, changed = _strip_locked_redefinition(output.proof_body, theorem_name)
    restored = restored or changed
    if not restored:
        return output, False
    return (
        output.model_copy(update={"helper_lemmas": tuple(helpers), "proof_body": body}),
        True,
    )


def _lean_error_blocks(stdout: str, stderr: str = "") -> str:
    text = _AXIOM_PRINT.sub("", f"{stdout}\n{stderr}")
    starts = [match.start() for match in _ERROR_START.finditer(text)]
    if not starts:
        lines = [line for line in text.splitlines() if line.strip()]
        return "\n".join(lines[-20:])
    blocks = []
    for start, end in zip(starts, starts[1:] + [len(text)]):
        lines: list[str] = []
        for line in text[start:end].splitlines():
            if _WARN_OR_INFO.match(line):
                break
            lines.append(line)
        block = "\n".join(lines).strip()
        if block:
            blocks.append(block)
    omitted = max(0, len(blocks) - MAX_ERROR_BLOCKS)
    joined = "\n\n".join(blocks[:MAX_ERROR_BLOCKS])
    if len(joined) > MAX_ERROR_CHARS:
        joined = joined[:MAX_ERROR_CHARS].rstrip() + "\n... truncated"
    if omitted:
        joined += f"\ntruncated, {omitted} more errors omitted"
    return joined


_UNKNOWN_NAME = re.compile(r"[Uu]nknown (?:constant|identifier)\s+`([^`\s]+)`")
_QUALIFIED_REAL_NAME = re.compile(
    r"(?<![A-Za-z0-9_'])Real\.([A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*)"
)


_DECLARATION = "^\\s*(?:protected\\s+)?(?:theorem|lemma)\\s+\\S*?(?<![A-Za-z]){token}(?![A-Za-z])"
_DECLARED_NAME = re.compile(
    r"^\s*(?:protected\s+)?(?:theorem|lemma)\s+([A-Za-z_][A-Za-z0-9_'.]*)"
)
_SEARCH_HITS = 8
_SEARCH_TIMEOUT = 10.0
_STOP_TOKENS = {"real", "abs", "le", "lt", "ge", "gt", "self", "of", "mpr", "mp", "iff", "neg", "pos", "nonneg", "nonpos", "sq", "mul", "add", "sub", "div", "two", "one", "zero"}


def _search_tokens(name: str) -> list[str]:
    parts = [part for part in re.split(r"[._']", name) if part]
    ranked = sorted(parts, key=len, reverse=True)
    return [part for part in ranked if len(part) >= 3 and part.lower() not in _STOP_TOKENS]


def _rg_declarations(token: str, mathlib_root: Path) -> list[str]:


    if not mathlib_root.is_dir():
        return []
    pattern = _DECLARATION.format(token=re.escape(token))
    try:
        completed = subprocess.run(
            [
                "rg", "-i", "-P", "--no-heading", "--no-line-number",
                "-m", "40", pattern, str(mathlib_root),
            ],
            text=True,
            capture_output=True,
            timeout=_SEARCH_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    hits: list[str] = []
    for line in completed.stdout.splitlines():
        _, _, declaration = line.partition(":")
        declaration = declaration.strip()
        if declaration:
            hits.append(declaration[:150])
    return hits


def mathlib_name_search(missing: str, mathlib_root: Path) -> list[str]:


    tokens = _search_tokens(missing)
    if not tokens:
        return []
    hits = _rg_declarations(tokens[0], mathlib_root)
    extras = [
        re.compile(rf"(?<![A-Za-z]){re.escape(part)}(?![A-Za-z])", re.IGNORECASE)
        for part in re.split(r"[._']", missing)
        if part and part.lower() != tokens[0].lower() and len(part) >= 2
    ]

    hits.sort(
        key=lambda text: (
            -sum(1 for expr in extras if expr.search(text)),
            len(text),
        )
    )
    seen: set[str] = set()
    unique = []
    for hit in hits:
        if hit not in seen:
            seen.add(hit)
            unique.append(hit)
    return unique[:_SEARCH_HITS]


_TRANSCENDENTAL_FAMILIES: dict[str, tuple[str, ...]] = {
    "exp": ("exp",),
    "log": ("log", "exp"),
    "tanh": ("tanh", "cosh", "sinh"),
    "cosh": ("cosh", "sinh"),
    "sinh": ("sinh", "cosh"),
    "sin": ("sin", "cos"),
    "cos": ("cos", "sin"),
    "tan": ("tan",),
    "sqrt": ("sqrt",),
    "atan": ("atan", "tan"),
}


def _replacement_candidates(
    missing_names: tuple[str, ...], mathlib_root: Path
) -> tuple[str, ...]:


    candidates: list[str] = []
    for missing in missing_names:
        namespace = missing.rsplit(".", 1)[0] if "." in missing else ""
        hits = list(mathlib_name_search(missing, mathlib_root))
        tokens = _search_tokens(missing)
        if tokens:
            family = _TRANSCENDENTAL_FAMILIES.get(tokens[0].lower(), ())
            for token in family:
                hits.extend(sorted(_rg_declarations(token, mathlib_root), key=len)[:12])
        for hit in hits:
            match = _DECLARED_NAME.match(hit)
            if match is None:
                continue
            declared = match.group(1)
            variants = [declared]
            if namespace and "." not in declared:
                variants.insert(0, f"{namespace}.{declared}")
            elif not namespace and "." not in declared:


                variants.insert(0, f"Real.{declared}")
            for variant in variants:
                if variant not in candidates:
                    candidates.append(variant)
    return tuple(candidates[:80])


def _augment_with_mathlib_search(errors: str, mathlib_root: Path | None) -> str:
    if mathlib_root is None:
        return errors
    missing = list(dict.fromkeys(_UNKNOWN_NAME.findall(errors)))
    if not missing:
        return errors
    sections: list[str] = []
    for name in missing[:3]:
        hits = mathlib_name_search(name, mathlib_root)
        if hits:
            found = "\n".join(f"  {hit}" for hit in hits)
            sections.append(
                f"`{name}` does not exist in Mathlib. Real declarations found by a "
                f"local Mathlib source search:\n{found}"
            )
        else:
            sections.append(
                f"`{name}` does not exist in Mathlib and no similar declaration was "
                "found. State and prove the fact you need in helper_lemmas."
            )
    if not sections:
        return errors
    return (
        errors
        + "\n\nMathlib name search:\n"
        + "\n\n".join(sections)
        + "\nUse only declarations shown above or basic lemmas you are sure of; "
        "otherwise prove the fact yourself in helper_lemmas."
    )


def _real_names(output: LeanAgentOutput) -> tuple[str, ...]:


    text = "\n".join((*output.helper_lemmas, output.proof_body))
    return tuple(
        dict.fromkeys(
            f"Real.{match.group(1)}"
            for match in _QUALIFIED_REAL_NAME.finditer(text)
        )
    )


def _real_name_check_source(names: tuple[str, ...]) -> str:
    return "\n".join(
        ("import LeanBarrier", "", *(f"#check {name}" for name in names), "")
    )


MAX_HEARTBEATS_OPTION = "set_option maxHeartbeats 1000000 in"


def _render_source(locked: LockedTheorem, output: LeanAgentOutput) -> str:
    helpers = "\n\n".join(output.helper_lemmas)
    return "\n".join(
        (
            "import LeanBarrier",
            "",
            "open scoped BigOperators",
            "",
            "namespace LeanBarrier.Generated",
            "",
            locked.definitions,
            "",
            helpers,
            "",
            MAX_HEARTBEATS_OPTION,
            f"{locked.statement} := {output.proof_body}",
            "",
            f"#print axioms {locked.theorem_name}",
            "",
            "end LeanBarrier.Generated",
            "",
        )
    )


_HELPER_DECLARATION = re.compile(
    r"^\s*(?:(?:private|protected)\s+)?(?:lemma|theorem)\s+"
    r"([A-Za-z_][A-Za-z0-9_']*)",
    re.MULTILINE,
)


def _generated_module_name(kind: str, source: str) -> str:
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return f"LeanBarrier.GeneratedCache.{kind}_{digest}"


def _context_module_source(locked: LockedTheorem) -> str:
    audit = (
        f"#print axioms {locked.definition_check_name}"
        if locked.definition_check_name is not None
        else ""
    )
    return "\n".join(
        (
            "import LeanBarrier",
            "",
            "open scoped BigOperators",
            "",
            "namespace LeanBarrier.Generated",
            "",
            locked.definitions,
            "",
            audit,
            "",
            "end LeanBarrier.Generated",
            "",
        )
    )


def _helper_module_source(
    dependency_module: str,
    helper: str,
    helper_name: str,
) -> str:
    return "\n".join(
        (
            f"import {dependency_module}",
            "",
            "open scoped BigOperators",
            "",
            "namespace LeanBarrier.Generated",
            "",
            MAX_HEARTBEATS_OPTION,
            helper,
            "",
            f"#print axioms {helper_name}",
            "",
            "end LeanBarrier.Generated",
            "",
        )
    )


def _render_imported_source(
    locked: LockedTheorem,
    output: LeanAgentOutput,
    dependency_module: str,
) -> str:
    return "\n".join(
        (
            f"import {dependency_module}",
            "",
            "open scoped BigOperators",
            "",
            "namespace LeanBarrier.Generated",
            "",
            MAX_HEARTBEATS_OPTION,
            f"{locked.statement} := {output.proof_body}",
            "",
            f"#print axioms {locked.theorem_name}",
            "",
            "end LeanBarrier.Generated",
            "",
        )
    )


def _proof_decomposition_diagnostic(output: LeanAgentOutput) -> str | None:
    oversized: list[str] = []
    fragments = (("proof_body", output.proof_body),) + tuple(
        (f"helper_lemmas[{index}]", helper)
        for index, helper in enumerate(output.helper_lemmas)
    )
    for label, fragment in fragments:
        lines = len(fragment.splitlines())
        chars = len(fragment)
        if lines > MAX_CACHED_DECLARATION_LINES or chars > MAX_CACHED_DECLARATION_CHARS:
            oversized.append(f"{label}: {lines} lines, {chars} characters")
    if not oversized:
        return None
    return (
        "The proof is too monolithic for independent compilation and caching:\n"
        + "\n".join(f"- {item}" for item in oversized)
        + "\nSplit algebraic identities, analytic bounds, and sign arguments into "
        "separate helper_lemmas entries (exactly one named declaration per entry). "
        "Keep proof_body as a short composition of those helpers."
    )


@dataclass(frozen=True)
class _PreparedLeanSource:
    source: str | None
    diagnostics: str = ""
    timed_out: bool = False


def parse_axioms(output: str, theorem_name: str) -> tuple[str, ...] | None:
    qualified_name = (
        re.escape(theorem_name)
        if "." in theorem_name
        else rf"(?:[A-Za-z_][A-Za-z0-9_']*\.)*{re.escape(theorem_name)}"
    )
    no_axioms = re.search(
        rf"'{qualified_name}' does not depend on any axioms", output
    )
    if no_axioms:
        return ()
    match = re.search(r"depends on axioms:\s*\[([^\]]*)\]", output, re.DOTALL)
    if not match:
        return None
    return tuple(part.strip() for part in match.group(1).split(",") if part.strip())


class LeanProofRunner:
    def __init__(
        self,
        compiler: LeanCompiler,
        *,
        allowed_axioms: frozenset[str] = CORE_ALLOWED_AXIOMS,
        deadline: RunDeadline | None = None,
        enforce_proof_size_limit: bool = True,
        repair_feedback: str = "processed",
    ) -> None:
        if repair_feedback not in LEAN_REPAIR_FEEDBACK_MODES:
            raise ValueError(f"unsupported lean repair feedback: {repair_feedback!r}")
        self.compiler = compiler
        self.allowed_axioms = allowed_axioms
        self.deadline = deadline
        self.enforce_proof_size_limit = enforce_proof_size_limit
        self.repair_feedback = repair_feedback
        self._verified_real_names: set[str] = set()
        self._verified_definition_hashes: set[str] = set()
        self._verified_definition_modules: dict[str, str] = {}
        self._verified_helper_modules: set[str] = set()

    def _feedback(self, processed: str, *, raw: str = "") -> str:
        return agent_repair_feedback(
            self.repair_feedback, processed=processed, raw=raw
        )

    def _cap_timeout(self, timeout_seconds: float) -> float:
        if self.deadline is None:
            return timeout_seconds
        return self.deadline.cap(
            timeout_seconds,
            reserve_seconds=DEFAULT_FINALIZATION_RESERVE_SECONDS,
        )

    def _mathlib_root(self) -> Path | None:
        project = getattr(self.compiler, "lean_project", None)
        if project is None:
            return None
        root = Path(project) / ".lake" / "packages" / "mathlib" / "Mathlib"
        return root if root.is_dir() else None

    def _ensure_context_module(
        self,
        locked: LockedTheorem,
        *,
        timeout_seconds: float,
    ) -> tuple[str | None, str, bool]:


        compile_module = getattr(self.compiler, "compile_module", None)
        if not callable(compile_module):
            return None, "", False
        source = _context_module_source(locked)
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        module_name = _generated_module_name("Context", source)
        if digest in self._verified_definition_modules:
            return self._verified_definition_modules[digest], "", False
        compiled = compile_module(
            module_name,
            source,
            timeout_seconds=timeout_seconds,
        )
        raw = f"{compiled.stdout}\n{compiled.stderr}".strip()
        if compiled.timed_out:
            return None, raw or "locked definition module timed out", True
        if compiled.returncode != 0:
            return None, raw or "locked definition module failed", False
        if "sorryAx" in raw:
            return None, "locked definition module depends on sorryAx", False
        self._verified_definition_modules[digest] = module_name
        self._verified_definition_hashes.add(content_hash(locked.definitions))
        return module_name, raw, False

    def _prepare_source(
        self,
        locked: LockedTheorem,
        output: LeanAgentOutput,
        *,
        timeout_seconds: float,
    ) -> _PreparedLeanSource:


        if not callable(getattr(self.compiler, "compile_module", None)):
            return _PreparedLeanSource(_render_source(locked, output))
        started = time.monotonic()

        def remaining() -> float:
            return max(0.1, timeout_seconds - (time.monotonic() - started))

        dependency, context_raw, timed_out = self._ensure_context_module(
            locked, timeout_seconds=remaining()
        )
        if dependency is None:
            return _PreparedLeanSource(
                None,
                "Lean definition module failed before the main proof:\n\n" + context_raw,
                timed_out,
            )
        compile_module = getattr(self.compiler, "compile_module")
        for index, helper in enumerate(output.helper_lemmas):
            names = _HELPER_DECLARATION.findall(helper)
            if len(names) != 1:
                return _PreparedLeanSource(
                    None,
                    "helper_lemmas[{index}] must contain exactly one top-level named "
                    "lemma or theorem so it can be compiled and cached independently; "
                    "found {count}. Split declarations into separate array entries.".format(
                        index=index, count=len(names)
                    ),
                )
            helper_name = names[0]
            helper_source = _helper_module_source(dependency, helper, helper_name)
            module_name = _generated_module_name("Helper", helper_source)
            if module_name not in self._verified_helper_modules:
                compiled = compile_module(
                    module_name,
                    helper_source,
                    timeout_seconds=remaining(),
                )
                raw = f"{compiled.stdout}\n{compiled.stderr}".strip()
                if compiled.timed_out:
                    return _PreparedLeanSource(
                        None,
                        f"helper_lemmas[{index}] ({helper_name}) timed out:\n\n{raw}",
                        True,
                    )
                if compiled.returncode != 0:
                    errors = _lean_error_blocks(compiled.stdout, compiled.stderr)
                    errors = _augment_with_mathlib_search(errors, self._mathlib_root())
                    return _PreparedLeanSource(
                        None,
                        f"helper_lemmas[{index}] ({helper_name}) failed its independent "
                        f"Lean compile:\n\n{errors}",
                    )
                axioms = parse_axioms(raw, helper_name)
                if axioms is None:
                    return _PreparedLeanSource(
                        None,
                        f"helper_lemmas[{index}] compiled, but its #print axioms output "
                        "was missing.",
                    )
                disallowed = set(axioms) - self.allowed_axioms
                if "sorryAx" in axioms or "sorryAx" in raw or disallowed:
                    return _PreparedLeanSource(
                        None,
                        f"helper_lemmas[{index}] failed the axiom audit: {sorted(disallowed)}",
                    )
                self._verified_helper_modules.add(module_name)
            dependency = module_name
        return _PreparedLeanSource(_render_imported_source(locked, output, dependency))

    def preflight_locked_definitions(self, locked: LockedTheorem) -> tuple[bool, str]:


        digest = content_hash(locked.definitions)
        if digest in self._verified_definition_hashes:
            return True, ""
        if callable(getattr(self.compiler, "compile_module", None)):
            _, raw, timed_out = self._ensure_context_module(
                locked, timeout_seconds=self._cap_timeout(MAX_DEFINITION_PREFLIGHT_SECONDS)
            )
            if timed_out:
                return False, raw or "locked definition preflight timed out"
            if content_hash(locked.definitions) not in self._verified_definition_hashes:
                return False, raw or "locked definition preflight failed"
            return True, raw
        if locked.definition_check_name is None:
            return True, ""
        source = "\n".join(
            (
                "import LeanBarrier",
                "",
                "namespace LeanBarrier.Generated",
                "",
                locked.definitions,
                "",
                f"#print axioms {locked.definition_check_name}",
                "",
                "end LeanBarrier.Generated",
                "",
            )
        )
        compiled = self.compiler.compile(
            source, timeout_seconds=self._cap_timeout(MAX_DEFINITION_PREFLIGHT_SECONDS)
        )
        raw = f"{compiled.stdout}\n{compiled.stderr}".strip()
        if compiled.timed_out:
            return False, raw or "locked definition preflight timed out"
        if compiled.returncode != 0:
            return False, raw or "locked definition preflight failed"
        if "sorryAx" in raw:
            return False, "locked definition preflight depends on sorryAx"
        self._verified_definition_hashes.add(digest)
        return True, raw

    def _verified_replacement_signatures(
        self,
        missing_names: tuple[str, ...],
        *,
        timeout_seconds: float,
    ) -> str:


        root = self._mathlib_root()
        if root is None:
            return ""
        candidates = _replacement_candidates(missing_names, root)
        if not candidates:
            return ""
        probe = self.compiler.compile(
            _real_name_check_source(candidates), timeout_seconds=timeout_seconds
        )
        if probe.timed_out:
            return ""
        raw = f"{probe.stdout}\n{probe.stderr}".strip()
        unknown = set(_UNKNOWN_NAME.findall(raw))
        valid = tuple(name for name in candidates if name not in unknown)
        if not valid:
            return ""
        self._verified_real_names.update(
            name for name in valid if name.startswith("Real.")
        )


        signatures = self.compiler.compile(
            _real_name_check_source(valid), timeout_seconds=timeout_seconds
        )
        if not signatures.timed_out and signatures.returncode == 0:
            rendered = f"{signatures.stdout}\n{signatures.stderr}".strip()
            if rendered:
                return rendered
        return "\n".join(valid)

    def _preflight_real_names(
        self,
        output: LeanAgentOutput,
        *,
        timeout_seconds: float,
    ) -> tuple[str, bool] | None:


        if self._mathlib_root() is None:
            return None
        names = tuple(
            name
            for name in _real_names(output)
            if name not in self._verified_real_names
        )
        if not names:
            return None
        checked = self.compiler.compile(
            _real_name_check_source(names), timeout_seconds=timeout_seconds
        )
        raw = f"{checked.stdout}\n{checked.stderr}".strip()
        if checked.timed_out:
            return raw or "Real.* declaration preflight timed out", True
        unknown = set(_UNKNOWN_NAME.findall(raw))
        if checked.returncode == 0:
            self._verified_real_names.update(names)
            return None


        if unknown:
            self._verified_real_names.update(name for name in names if name not in unknown)
        errors = _lean_error_blocks(checked.stdout, checked.stderr)
        if not unknown:
            return f"Real.* declaration preflight failed:\n\n{errors}", True
        errors = _augment_with_mathlib_search(errors, self._mathlib_root())
        verified = self._verified_replacement_signatures(
            tuple(sorted(unknown)), timeout_seconds=timeout_seconds
        )
        if verified:
            errors += (
                "\n\nLean-verified replacement whitelist (exact names and types from "
                "the pinned environment):\n"
                + verified
                + "\nUse only these verified declarations or prove the needed proposition "
                "as a local helper lemma."
            )
        return f"{_REAL_NAME_GATE}{errors}", False

    def _failed(
        self,
        condition_id: str,
        locked: LockedTheorem,
        *,
        rounds: int,
        started: float,
        diagnostics: str,
        last_blocker: str | None,
        attempts: list[LeanAttempt],
        proof_rounds: int = 0,
        name_repair_rounds: int = 0,
        agent_call_retries: int = 0,
        compiled: bool = False,
        printed_axioms: tuple[str, ...] = (),
        proof_body: str = "",
    ) -> LeanResult:
        return LeanResult(
            condition_id=condition_id,
            candidate_hash=locked.candidate_hash,
            statement_hash=locked.statement_hash,
            status=LeanAgentStatus.CANNOT_COMPLETE,
            compiled=compiled,
            rounds=rounds,
            proof_rounds=proof_rounds,
            name_repair_rounds=name_repair_rounds,
            agent_call_retries=agent_call_retries,
            duration_seconds=time.monotonic() - started,
            proof_body_hash=(
                hashlib.sha256(proof_body.encode()).hexdigest() if proof_body else None
            ),
            diagnostics=diagnostics,
            printed_axioms=printed_axioms,
            audit_passed=False,
            blocking_reason=last_blocker or "proof budget ended without a candidate proof",
            attempts=tuple(attempts),
        )

    def compile_once(
        self,
        condition_id: str,
        locked: LockedTheorem,
        output: LeanAgentOutput,
        *,
        note: str = "",
        origin: str = "pre-generated proof",
        timeout_seconds: float = MAX_PROOF_SECONDS,
    ) -> LeanResult | None:


        started = time.monotonic()
        timeout_seconds = self._cap_timeout(timeout_seconds)
        fragments = (*output.helper_lemmas, output.proof_body)
        if not output.proof_body.strip():
            return None
        if self.enforce_proof_size_limit and _proof_decomposition_diagnostic(output) is not None:
            return None
        if any(_fatal_token(fragment) for fragment in fragments):
            return None
        if any(_has_sorry(fragment) for fragment in fragments):
            return None
        if content_hash(locked.statement) != locked.statement_hash:
            return None
        prepared = self._prepare_source(
            locked, output, timeout_seconds=timeout_seconds
        )
        if prepared.source is None:
            return None
        source = prepared.source
        compiled = self.compiler.compile(source, timeout_seconds=timeout_seconds)
        raw = f"{compiled.stdout}\n{compiled.stderr}".strip()
        if compiled.timed_out or compiled.returncode != 0:
            return None
        axioms = parse_axioms(raw, locked.theorem_name)
        if axioms is None:
            return None
        if "sorryAx" in axioms or "sorryAx" in raw:
            return None
        if set(axioms) - self.allowed_axioms:
            return None
        diagnostics = f"[{origin}: {note}]\n{raw}" if note else raw
        return LeanResult(
            condition_id=condition_id,
            candidate_hash=locked.candidate_hash,
            statement_hash=locked.statement_hash,
            status=LeanAgentStatus.CANDIDATE_PROOF,
            compiled=True,
            rounds=0,
            duration_seconds=time.monotonic() - started,
            proof_body_hash=hashlib.sha256(output.proof_body.encode()).hexdigest(),
            diagnostics=diagnostics,
            printed_axioms=axioms,
            audit_passed=True,
            attempts=(
                LeanAttempt(
                    round_index=1,
                    agent_status=LeanAgentStatus.CANDIDATE_PROOF,
                    helper_lemmas=output.helper_lemmas,
                    proof_body=output.proof_body,
                    generated_source_hash=content_hash(source),
                    compiled=True,
                    diagnostics=diagnostics,
                    printed_axioms=axioms,
                ),
            ),
        )

    def run(
        self,
        condition_id: str,
        locked: LockedTheorem,
        agent: ProofAgent,
        *,
        counterexample_checker: CounterexampleChecker | None = None,
    ) -> LeanResult:
        started = time.monotonic()
        proof_budget = self._cap_timeout(MAX_PROOF_SECONDS)
        previous = ""
        diagnostics = ""
        rounds = 0
        proof_rounds = 0
        name_repair_rounds = 0
        last_blocker: str | None = None
        attempts: list[LeanAttempt] = []
        sorry_retries = 0
        agent_call_retries = 0
        while proof_rounds < MAX_PROOF_ROUNDS:
            elapsed = time.monotonic() - started
            if elapsed >= proof_budget:
                last_blocker = "proof time budget exhausted"
                break
            round_index = rounds + 1
            rounds = round_index
            try:
                output = agent(round_index, previous, diagnostics)
            except Exception as error:

                if agent_call_retries >= 2:
                    last_blocker = f"lean agent call failed: {error}"
                    break
                agent_call_retries += 1
                try:
                    output = agent(round_index, previous, diagnostics)
                except Exception as retry_error:
                    last_blocker = (
                        f"lean agent call failed twice in round {round_index}: "
                        f"{error}; retry: {retry_error}"
                    )
                    break
            if output.status == LeanAgentStatus.CANNOT_COMPLETE:
                proof_rounds += 1
                claims_false = _claims_locked_theorem_false(
                    output.blocking_reason or ""
                )
                if counterexample_checker is not None and output.counterexample:
                    confirmed, detail = counterexample_checker(dict(output.counterexample))
                    if confirmed:
                        last_blocker = (
                            "counterexample confirmed by numerical replay: "
                            f"{detail}; original claim: {output.blocking_reason}"
                        )
                        attempts.append(
                            LeanAttempt(
                                round_index=round_index,
                                agent_status=output.status,
                                helper_lemmas=output.helper_lemmas,
                                proof_body=output.proof_body,
                                diagnostics=last_blocker,
                            )
                        )
                        break
                    diagnostics = self._feedback(_CE_REJECTED.format(detail=detail))
                    last_blocker = output.blocking_reason
                    attempts.append(
                        LeanAttempt(
                            round_index=round_index,
                            agent_status=output.status,
                            helper_lemmas=output.helper_lemmas,
                            proof_body=output.proof_body,
                            diagnostics=diagnostics,
                        )
                    )
                    continue
                if claims_false:
                    diagnostics = self._feedback(_CE_POINT_REQUIRED)
                    last_blocker = output.blocking_reason
                    attempts.append(
                        LeanAttempt(
                            round_index=round_index,
                            agent_status=output.status,
                            helper_lemmas=output.helper_lemmas,
                            proof_body=output.proof_body,
                            diagnostics=diagnostics,
                        )
                    )
                    continue
                diagnostics = self._feedback(_SURRENDER_REJECTED)
                last_blocker = output.blocking_reason
                previous = output.proof_body
                attempts.append(
                    LeanAttempt(
                        round_index=round_index,
                        agent_status=output.status,
                        helper_lemmas=output.helper_lemmas,
                        proof_body=output.proof_body,
                        diagnostics=diagnostics,
                    )
                )
                continue
            fragments = (*output.helper_lemmas, output.proof_body)
            fatal = next(
                (issue for fragment in fragments if (issue := _fatal_token(fragment))),
                None,
            )
            if fatal:
                proof_rounds += 1
                last_blocker = fatal
                attempts.append(
                    LeanAttempt(
                        round_index=round_index,
                        agent_status=output.status,
                        helper_lemmas=output.helper_lemmas,
                        proof_body=output.proof_body,
                        diagnostics=fatal,
                    )
                )
                break
            output, restored = _restore_locked_statement(output, locked.theorem_name)
            if restored and not output.proof_body.strip():
                proof_rounds += 1
                diagnostics = self._feedback(_RESTORE_MSG)
                previous = ""
                last_blocker = diagnostics
                attempts.append(
                    LeanAttempt(
                        round_index=round_index,
                        agent_status=output.status,
                        helper_lemmas=output.helper_lemmas,
                        proof_body=output.proof_body,
                        diagnostics=diagnostics,
                    )
                )
                continue
            decomposition_error = (
                _proof_decomposition_diagnostic(output)
                if self.enforce_proof_size_limit else None
            )
            if decomposition_error is not None:
                proof_rounds += 1
                diagnostics = self._feedback(decomposition_error)
                previous = output.proof_body
                last_blocker = "proof decomposition required"
                attempts.append(
                    LeanAttempt(
                        round_index=round_index,
                        agent_status=output.status,
                        helper_lemmas=output.helper_lemmas,
                        proof_body=output.proof_body,
                        diagnostics=diagnostics,
                    )
                )
                continue
            remaining = max(0.1, proof_budget - (time.monotonic() - started))
            name_check = self._preflight_real_names(
                output, timeout_seconds=remaining
            )
            if name_check is not None:
                name_diagnostics, terminal = name_check
                last_blocker = (
                    "declaration preflight failed"
                    if terminal
                    else "unknown external declaration"
                )
                attempts.append(
                    LeanAttempt(
                        round_index=round_index,
                        agent_status=output.status,
                        helper_lemmas=output.helper_lemmas,
                        proof_body=output.proof_body,
                        diagnostics=name_diagnostics,
                    )
                )
                if terminal:
                    break
                name_repair_rounds += 1
                if name_repair_rounds >= MAX_NAME_REPAIR_ROUNDS:
                    last_blocker = "declaration name-repair budget exhausted"
                    break
                diagnostics = self._feedback(name_diagnostics)
                previous = output.proof_body
                continue
            proof_rounds += 1
            if any(_has_sorry(fragment) for fragment in (*output.helper_lemmas, output.proof_body)):
                sorry_retries += 1
                last_blocker = _SORRY_MSG
                attempts.append(
                    LeanAttempt(
                        round_index=round_index,
                        agent_status=output.status,
                        helper_lemmas=output.helper_lemmas,
                        proof_body=output.proof_body,
                        diagnostics=_SORRY_MSG,
                    )
                )
                if sorry_retries >= 2:
                    break
                diagnostics = self._feedback(_SORRY_MSG)
                previous = output.proof_body
                continue
            if content_hash(locked.statement) != locked.statement_hash:
                last_blocker = "locked statement hash changed"
                break
            remaining = max(0.1, proof_budget - (time.monotonic() - started))
            prepared = self._prepare_source(
                locked, output, timeout_seconds=remaining
            )
            if prepared.source is None:
                last_blocker = (
                    "Lean helper module timed out"
                    if prepared.timed_out
                    else "Lean helper module compilation failed"
                )
                diagnostics = self._feedback(
                    f"{_FIX_ALL}{prepared.diagnostics}",
                    raw=prepared.diagnostics,
                )
                previous = output.proof_body
                attempts.append(
                    LeanAttempt(
                        round_index=round_index,
                        agent_status=output.status,
                        helper_lemmas=output.helper_lemmas,
                        proof_body=output.proof_body,
                        diagnostics=diagnostics,
                    )
                )
                if prepared.timed_out:
                    break
                continue
            source = prepared.source
            remaining = max(0.1, proof_budget - (time.monotonic() - started))
            compiled = self.compiler.compile(source, timeout_seconds=remaining)
            raw = f"{compiled.stdout}\n{compiled.stderr}".strip()
            if compiled.timed_out:
                last_blocker = "Lean compiler timed out"
                attempts.append(
                    LeanAttempt(
                        round_index=round_index,
                        agent_status=output.status,
                        helper_lemmas=output.helper_lemmas,
                        proof_body=output.proof_body,
                        generated_source_hash=content_hash(source),
                        diagnostics=raw,
                    )
                )
                break
            if compiled.returncode != 0:
                errors = _lean_error_blocks(compiled.stdout, compiled.stderr)
                errors = _augment_with_mathlib_search(errors, self._mathlib_root())
                prefix = f"{_RESTORE_MSG}\n\n" if restored else ""
                diagnostics = self._feedback(
                    f"{prefix}{_FIX_ALL}{errors}",
                    raw=raw,
                )
                previous = output.proof_body
                last_blocker = "Lean compilation failed"
                attempts.append(
                    LeanAttempt(
                        round_index=round_index,
                        agent_status=output.status,
                        helper_lemmas=output.helper_lemmas,
                        proof_body=output.proof_body,
                        generated_source_hash=content_hash(source),
                        diagnostics=diagnostics,
                    )
                )
                continue
            axioms = parse_axioms(raw, locked.theorem_name)
            if axioms is None:
                previous = output.proof_body
                last_blocker = "#print axioms output was missing"
                diagnostics = self._feedback(_AXIOM_PRINT_MSG)
                attempts.append(
                    LeanAttempt(
                        round_index=round_index,
                        agent_status=output.status,
                        helper_lemmas=output.helper_lemmas,
                        proof_body=output.proof_body,
                        generated_source_hash=content_hash(source),
                        compiled=True,
                        diagnostics=diagnostics,
                    )
                )
                continue
            attempts.append(
                LeanAttempt(
                    round_index=round_index,
                    agent_status=output.status,
                    helper_lemmas=output.helper_lemmas,
                    proof_body=output.proof_body,
                    generated_source_hash=content_hash(source),
                    compiled=True,
                    diagnostics=raw,
                    printed_axioms=axioms,
                )
            )
            if "sorryAx" in axioms or "sorryAx" in raw:
                sorry_retries += 1
                last_blocker = _SORRY_MSG
                if sorry_retries >= 2:
                    return self._failed(
                        condition_id,
                        locked,
                        rounds=rounds,
                        started=started,
                        diagnostics=raw,
                        last_blocker=last_blocker,
                        attempts=attempts,
                        proof_rounds=proof_rounds,
                        name_repair_rounds=name_repair_rounds,
                        agent_call_retries=agent_call_retries,
                        compiled=True,
                        printed_axioms=axioms,
                        proof_body=output.proof_body,
                    )
                diagnostics = self._feedback(
                    f"{_SORRY_MSG}\n{raw}" if "sorryAx" in raw else _SORRY_MSG,
                    raw=raw,
                )
                previous = output.proof_body
                continue
            extra = set(axioms) - self.allowed_axioms
            if extra:
                last_blocker = "extra axiom: " + ", ".join(sorted(extra))
                return self._failed(
                    condition_id,
                    locked,
                    rounds=rounds,
                    started=started,
                    diagnostics=raw,
                    last_blocker=last_blocker,
                    attempts=attempts,
                    proof_rounds=proof_rounds,
                    name_repair_rounds=name_repair_rounds,
                    agent_call_retries=agent_call_retries,
                    compiled=True,
                    printed_axioms=axioms,
                    proof_body=output.proof_body,
                )
            return LeanResult(
                condition_id=condition_id,
                candidate_hash=locked.candidate_hash,
                statement_hash=locked.statement_hash,
                status=LeanAgentStatus.CANDIDATE_PROOF,
                compiled=True,
                rounds=rounds,
                proof_rounds=proof_rounds,
                name_repair_rounds=name_repair_rounds,
                agent_call_retries=agent_call_retries,
                duration_seconds=time.monotonic() - started,
                proof_body_hash=hashlib.sha256(output.proof_body.encode()).hexdigest(),
                diagnostics=raw,
                printed_axioms=axioms,
                audit_passed=True,
                attempts=tuple(attempts),
            )
        return self._failed(
            condition_id,
            locked,
            rounds=rounds,
            started=started,
            diagnostics=diagnostics,
            last_blocker=last_blocker,
            attempts=attempts,
            proof_rounds=proof_rounds,
            name_repair_rounds=name_repair_rounds,
            agent_call_retries=agent_call_retries,
        )
