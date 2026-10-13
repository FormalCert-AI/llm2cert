"""Validate structured model responses and maintain agent conversations."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .s02_expressions import desugar_json


_SCHEMA_DESCRIPTIONS = json.loads(
    Path(__file__).with_name("schema_descriptions.json").read_text(encoding="utf-8")
)

def _model_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    for node in [schema, *schema.get("$defs", {}).values()]:
        title = node.get("title")
        if title not in _SCHEMA_DESCRIPTIONS:
            continue
        description = _SCHEMA_DESCRIPTIONS[title]
        if description is None:
            node.pop("description", None)
        else:
            node["description"] = description
    return schema


_INVISIBLE_CHARS = dict.fromkeys(map(ord, "\ufeff\u200b\u200c\u200d\u2060"), None)


MAX_FORMAT_REPAIRS = 3


class AgentFormatError(RuntimeError):
    pass


JSON_TURN = (
    "Return exactly one JSON object matching the requested schema. "
    "Do not include reasoning, commentary, Markdown, code fences, or wrapper fields."
)


class AgentTransport(Protocol):
    def __call__(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        strict: bool,
        messages: list[dict[str, str]] | None = None,
    ) -> str | Mapping[str, Any]: ...


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class AgentCallRecord:
    prompt: str
    schema_name: str
    strict_api_mode: bool
    raw_response: str
    repaired_once: bool


def _assert_strict_shape(value: Any, schema: dict[str, Any]) -> None:
    root = schema

    def check(item: Any, node: dict[str, Any], path: str) -> None:
        reference = node.get("$ref")
        if isinstance(reference, str):
            if not reference.startswith("#/"):
                raise AgentFormatError(f"unsupported schema reference at {path}: {reference}")
            target: Any = root
            for part in reference[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
            check(item, target, path)
            return
        alternatives = node.get("anyOf")
        if isinstance(alternatives, list):
            failures: list[str] = []
            for alternative in alternatives:
                try:
                    check(item, alternative, path)
                    return
                except AgentFormatError as error:
                    failures.append(str(error))
            raise AgentFormatError(f"no union branch matched at {path}: {'; '.join(failures)}")
        if "const" in node and item != node["const"]:
            raise AgentFormatError(f"wrong constant at {path}")
        expected = node.get("type")
        if expected == "null":
            if item is not None:
                raise AgentFormatError(f"expected null at {path}")
            return
        if expected == "object" or "properties" in node or "patternProperties" in node:
            if not isinstance(item, dict):
                raise AgentFormatError(f"expected object at {path}")
            properties = node.get("properties", {})
            missing = [name for name in properties if name not in item]
            pattern_properties = node.get("patternProperties", {})
            extra: list[str] = []
            matched_patterns: dict[str, dict[str, Any]] = {}
            for name in item:
                if name in properties:
                    continue
                matched = next(
                    (
                        child
                        for pattern, child in pattern_properties.items()
                        if re.fullmatch(pattern, name)
                    ),
                    None,
                )
                if matched is None:
                    extra.append(name)
                else:
                    matched_patterns[name] = matched
            if missing or extra:
                raise AgentFormatError(
                    f"object fields differ at {path}; missing={missing}, extra={extra}"
                )
            for name, child in properties.items():
                check(item[name], child, f"{path}.{name}")
            for name, child in matched_patterns.items():
                check(item[name], child, f"{path}.{name}")
            return
        if expected == "array":
            if not isinstance(item, list):
                raise AgentFormatError(f"expected array at {path}")
            child = node.get("items")
            if isinstance(child, dict):
                for index, element in enumerate(item):
                    check(element, child, f"{path}[{index}]")

    check(value, schema, "$")


def _normalize_agent_text(raw_text: str) -> str:
    text = raw_text.translate(_INVISIBLE_CHARS).strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```JSON").removeprefix("```")
        if "```" in text:
            text = text.rsplit("```", 1)[0]
        text = text.strip()
    return text


def _extract_json_values(text: str) -> list[Any]:
    decoder = json.JSONDecoder()
    values: list[Any] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index] not in "{[":
            index += 1
        if index >= len(text):
            break
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index += 1
            continue
        values.append(value)
        index = end
    return values


def _required_object_fields(output_model: type[BaseModel]) -> frozenset[str]:
    schema = _model_schema(output_model)
    required = schema.get("required")
    if isinstance(required, list) and required:
        return frozenset(str(name) for name in required)
    properties = schema.get("properties")
    if isinstance(properties, dict):
        return frozenset(properties)
    return frozenset()


def _has_schema_shaped_object(raw_text: str, output_model: type[BaseModel]) -> bool:
    required = _required_object_fields(output_model)
    if not required:
        return False
    return any(
        isinstance(value, dict) and required.issubset(value)
        for value in _extract_json_values(_normalize_agent_text(raw_text))
    )


def _apply_model_defaults(value: Any, model: type[BaseModel]) -> Any:


    if not isinstance(value, dict):
        return value
    filled = dict(value)
    for name, field in model.model_fields.items():
        if name in filled or field.is_required():
            continue
        default = field.get_default(call_default_factory=True)
        if default is None:
            filled[name] = None
        elif hasattr(default, "model_dump"):
            filled[name] = default.model_dump(mode="json")
        elif isinstance(default, tuple):
            filled[name] = list(default)
        else:
            filled[name] = default
    return filled


def _parse_agent_output(raw_text: str, output_model: type[T]) -> T:
    text = _normalize_agent_text(raw_text)
    values = _extract_json_values(text)
    if not values:
        raise json.JSONDecodeError("Expecting value", text or raw_text, 0)
    errors: list[str] = []
    schema = openai_strict_json_schema(output_model)
    for value in values:
        try:
            prepared = desugar_json(_apply_model_defaults(value, output_model))
            _assert_strict_shape(prepared, schema)
            return output_model.model_validate_json(json.dumps(prepared))
        except (ValidationError, AgentFormatError, TypeError) as error:
            errors.append(str(error))
    raise AgentFormatError(
        f"no extracted JSON object matched {output_model.__name__}: {'; '.join(errors)}"
    )


class StructuredAgentRunner:


    def __init__(
        self,
        transport: AgentTransport,
        *,
        supports_structured_outputs: bool,
        repair_transport: AgentTransport | None = None,
    ) -> None:
        self._transport = transport
        self._strict = supports_structured_outputs
        self._repair_transport = repair_transport or transport
        self.last_record: AgentCallRecord | None = None
        self.conversation: list[dict[str, str]] = []
        self.system_prompt: str | None = None

    def fresh(self) -> StructuredAgentRunner:


        return StructuredAgentRunner(
            self._transport,
            supports_structured_outputs=self._strict,
            repair_transport=self._repair_transport,
        )

    def _messages(self, prompt: str) -> tuple[list[dict[str, str]], str]:
        if self.system_prompt is None:
            self.system_prompt = prompt
            user_turn = JSON_TURN
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_turn},
            ]
            return messages, user_turn
        user_turn = prompt
        messages = [
            {"role": "system", "content": self.system_prompt},
            *self.conversation,
            {"role": "user", "content": user_turn},
        ]
        return messages, user_turn

    def _remember(self, user_turn: str, assistant_text: str) -> None:
        self.conversation.append({"role": "user", "content": user_turn})
        self.conversation.append({"role": "assistant", "content": assistant_text})

    def run(self, prompt: str, output_model: type[T]) -> T:
        schema = (
            openai_strict_json_schema(output_model)
            if self._strict
            else _model_schema(output_model)
        )
        messages, user_turn = self._messages(prompt)
        raw = self._transport(
            prompt=prompt,
            schema_name=output_model.__name__,
            schema=schema,
            strict=self._strict,
            messages=messages,
        )
        raw_text = raw if isinstance(raw, str) else json.dumps(raw, sort_keys=True)
        try:
            value = _parse_agent_output(raw_text, output_model)
            self.last_record = AgentCallRecord(
                prompt, output_model.__name__, self._strict, raw_text, False
            )
            self._remember(user_turn, raw_text)
            return value
        except (ValidationError, json.JSONDecodeError, AgentFormatError) as first_error:
            if self._strict:
                raise AgentFormatError(
                    f"strict structured output was invalid: {first_error}"
                ) from first_error
            extracted = _extract_json_values(_normalize_agent_text(raw_text))
            if extracted and not _has_schema_shaped_object(raw_text, output_model):
                raise AgentFormatError(
                    f"response contained no {output_model.__name__} object: {first_error}"
                ) from first_error
            last_error: Exception = first_error
            invalid_text = raw_text
            for _repair_round in range(MAX_FORMAT_REPAIRS):
                repair_prompt = (
                    "Repair only the JSON shape of the response below. "
                    "If a schema-matching object is already present, extract that object. "
                    "Do not preserve commentary or wrapper fields. "
                    "Return one object matching the supplied schema and no other text.\n\n"
                    f"Schema name: {output_model.__name__}\n"
                    f"Schema:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
                    f"Invalid response:\n{invalid_text}\n\nValidation error:\n{last_error}"
                )
                try:
                    repair_messages = [
                        *messages,
                        {"role": "assistant", "content": invalid_text},
                        {"role": "user", "content": repair_prompt},
                    ]
                    repaired = self._repair_transport(
                        prompt=repair_prompt,
                        schema_name=output_model.__name__,
                        schema=schema,
                        strict=False,
                        messages=repair_messages,
                    )
                except Exception as transport_error:
                    last_error = transport_error
                    continue
                repaired_text = (
                    repaired
                    if isinstance(repaired, str)
                    else json.dumps(repaired, sort_keys=True)
                )
                try:
                    value = _parse_agent_output(repaired_text, output_model)
                except (ValidationError, json.JSONDecodeError, AgentFormatError) as error:
                    last_error = error
                    invalid_text = repaired_text
                    continue
                self.last_record = AgentCallRecord(
                    prompt, output_model.__name__, False, repaired_text, True
                )
                self._remember(user_turn, repaired_text)
                return value
            raise AgentFormatError(
                f"agent output remained invalid after {MAX_FORMAT_REPAIRS} format "
                f"repairs: {last_error}"
            ) from last_error


def responses_api_text_format(model: type[BaseModel]) -> dict[str, Any]:


    return {
        "format": {
            "type": "json_schema",
            "name": model.__name__,
            "schema": openai_strict_json_schema(model),
            "strict": True,
        }
    }


def openai_strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:


    schema = deepcopy(_model_schema(model))

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return

        node.pop("default", None)

        node.pop("discriminator", None)
        if "oneOf" in node:
            node["anyOf"] = node.pop("oneOf")
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["additionalProperties"] = False
            node["required"] = list(properties)
        for value in node.values():
            visit(value)

    visit(schema)
    return schema
