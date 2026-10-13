"""Apply constrained local edits to Lean proofs."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .s01_models import (
    LeanAgentOutput,
    LeanLocalPatch,
    LeanLocalPatchStatus,
)


_UNKNOWN_NAME = re.compile(r"Unknown (?:constant|identifier) `([^`]+)`", re.IGNORECASE)
_HELPER_INDEX = re.compile(r"helper_lemmas\[(\d+)\]")
_ERROR_LOCATION = re.compile(r"\.lean:(\d+):(\d+):\s*(?:error(?:\([^)]*\))?:|error:)")
_LOCAL_ERROR = re.compile(
    r"unknown (?:constant|identifier)|hard real\.\* declaration gate|"
    r"(?:application )?type mismatch|has type\s+.*expected to have type|"
    r"function expected at|expected a function because|"
    r"unexpected token|parser error|invalid syntax",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDDEN = re.compile(
    r"\b(sorry|admit|axiom|unsafe|set_option\s+pp\.universes)\b|^\s*import\b",
    re.IGNORECASE | re.MULTILINE,
)
@dataclass(frozen=True)
class LocalRepairRequest:
    base_output_hash: str
    patch_id: str
    target_kind: str
    target_index: int
    line_index: int
    indentation: str
    old_text: str
    source_window: str
    compiler_context: str
    verified_declarations: str


def lean_output_hash(output: LeanAgentOutput) -> str:
    payload = "\n\0\n".join((*output.helper_lemmas, output.proof_body))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _window(lines: list[str], index: int, radius: int = 3) -> str:
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    return "\n".join(
        f"{line_index + 1:>4}{'>' if line_index == index else ' '} | {lines[line_index]}"
        for line_index in range(start, end)
    )


def _verified_section(diagnostics: str) -> str:
    marker = "Lean-verified replacement whitelist"
    if marker not in diagnostics:
        return ""
    section = diagnostics.split(marker, 1)[1]
    return (marker + section)[:6000]


def _diagnostic_excerpt(diagnostics: str) -> str:


    head = diagnostics.split("Mathlib name search:", 1)[0]
    if len(head) <= 6000:
        return head
    return head[-6000:]


def _request_for_line(
    output: LeanAgentOutput,
    diagnostics: str,
    *,
    target_kind: str,
    target_index: int,
    line_index: int,
) -> LocalRepairRequest | None:
    text = (
        output.helper_lemmas[target_index]
        if target_kind == "helper"
        else output.proof_body
    )
    lines = text.splitlines()
    if line_index < 0 or line_index >= len(lines):
        return None
    line = lines[line_index]
    if not line.strip():
        return None
    indentation = line[: len(line) - len(line.lstrip())]
    digest = lean_output_hash(output)
    patch_id = f"{digest[:16]}:{target_kind}:{target_index}:{line_index + 1}"
    return LocalRepairRequest(
        base_output_hash=digest,
        patch_id=patch_id,
        target_kind=target_kind,
        target_index=target_index,
        line_index=line_index,
        indentation=indentation,
        old_text=line[len(indentation) :],
        source_window=_window(lines, line_index),
        compiler_context=_diagnostic_excerpt(diagnostics),
        verified_declarations=_verified_section(diagnostics),
    )


def localize_lean_error(
    output: LeanAgentOutput,
    diagnostics: str,
    locked_statement: str,
) -> LocalRepairRequest | None:


    if not _LOCAL_ERROR.search(diagnostics):
        return None

    unknown = tuple(dict.fromkeys(_UNKNOWN_NAME.findall(diagnostics)))
    if unknown:
        occurrences: list[tuple[str, int, int]] = []
        for helper_index, helper in enumerate(output.helper_lemmas):
            for line_index, line in enumerate(helper.splitlines()):
                if any(name in line for name in unknown):
                    occurrences.append(("helper", helper_index, line_index))
        for line_index, line in enumerate(output.proof_body.splitlines()):
            if any(name in line for name in unknown):
                occurrences.append(("proof_body", 0, line_index))
        if len(occurrences) != 1:
            return None
        kind, index, line = occurrences[0]
        return _request_for_line(
            output,
            diagnostics,
            target_kind=kind,
            target_index=index,
            line_index=line,
        )

    locations = _ERROR_LOCATION.findall(diagnostics)
    if not locations:
        return None
    source_line = int(locations[0][0])
    helper_match = _HELPER_INDEX.search(diagnostics)
    if helper_match is not None:
        helper_index = int(helper_match.group(1))
        if helper_index >= len(output.helper_lemmas):
            return None

        return _request_for_line(
            output,
            diagnostics,
            target_kind="helper",
            target_index=helper_index,
            line_index=source_line - 8,
        )


    body_line = source_line - 7 - len(locked_statement.splitlines())
    return _request_for_line(
        output,
        diagnostics,
        target_kind="proof_body",
        target_index=0,
        line_index=body_line,
    )


def failed_helper_index(diagnostics: str) -> int | None:
    match = _HELPER_INDEX.search(diagnostics)
    return None if match is None else int(match.group(1))


def apply_local_patch(
    output: LeanAgentOutput,
    request: LocalRepairRequest,
    patch: LeanLocalPatch,
) -> LeanAgentOutput | None:


    if patch.status != LeanLocalPatchStatus.PATCH:
        return None
    if patch.patch_id != request.patch_id:
        return None
    if lean_output_hash(output) != request.base_output_hash:
        return None
    replacement = patch.replacement_code.strip("\n")
    if not replacement or len(replacement.splitlines()) > 20 or _FORBIDDEN.search(replacement):
        return None
    replacement_lines = [
        request.indentation + line if line else ""
        for line in replacement.splitlines()
    ]
    if request.target_kind == "helper":
        helpers = list(output.helper_lemmas)
        lines = helpers[request.target_index].splitlines()
        if lines[request.line_index] != request.indentation + request.old_text:
            return None
        lines[request.line_index : request.line_index + 1] = replacement_lines
        helpers[request.target_index] = "\n".join(lines)
        return output.model_copy(update={"helper_lemmas": tuple(helpers)})
    lines = output.proof_body.splitlines()
    if lines[request.line_index] != request.indentation + request.old_text:
        return None
    lines[request.line_index : request.line_index + 1] = replacement_lines
    return output.model_copy(update={"proof_body": "\n".join(lines)})


def targets_replacement_span(
    original: LocalRepairRequest,
    current: LocalRepairRequest | None,
    replacement_line_count: int,
) -> bool:


    if current is None or replacement_line_count < 1:
        return False
    return (
        current.target_kind == original.target_kind
        and current.target_index == original.target_index
        and original.line_index
        <= current.line_index
        < original.line_index + replacement_line_count
    )
