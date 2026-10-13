"""Send model requests through configured provider transports."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Iterable

from .s06_agents import JSON_TURN
from .s13_runtime import (
    DEFAULT_FINALIZATION_RESERVE_SECONDS,
    RunDeadline,
    RunDeadlineExceeded,
)

RETRY_DELAYS = (2.0, 5.0, 10.0, 20.0, 40.0)
DEFAULT_MAX_TOKENS = 16384
DEFAULT_THINKING_BUDGET = 16000
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_BETA = "interleaved-thinking-2025-05-14"
_INVISIBLE_CONTENT_CHARS = str.maketrans(
    "", "", "\ufeff\u200b\u200c\u200d\u2060"
)


def _has_visible_content(text: str) -> bool:


    return bool(str(text).translate(_INVISIBLE_CONTENT_CHARS).strip())


def _default_messages(prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": JSON_TURN},
    ]


def split_system_and_messages(
    messages: list[dict[str, str]],
) -> tuple[str, list[dict[str, str]]]:


    system_parts: list[str] = []
    turns: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        turns.append({"role": role, "content": content})
    if not turns:
        turns = [{"role": "user", "content": JSON_TURN}]
    return "\n\n".join(system_parts), turns


def _iter_sse_events(response: Iterable[bytes]) -> Iterable[dict[str, Any]]:
    for raw in response:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            event = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def ingest_stream_event(
    event: dict[str, Any],
    content_parts: list[str],
    reasoning_parts: list[str],
) -> dict[str, Any] | None:


    event_type = event.get("type")
    if event_type == "content_block_delta":
        delta = event.get("delta") or {}
        delta_type = delta.get("type")
        if delta_type == "text_delta" and delta.get("text"):
            content_parts.append(str(delta["text"]))
        elif delta_type == "thinking_delta" and delta.get("thinking"):
            reasoning_parts.append(str(delta["thinking"]))
        return event.get("usage")
    if event_type == "content_block_start":
        block = event.get("content_block") or {}
        if block.get("type") == "text" and block.get("text"):
            content_parts.append(str(block["text"]))
        elif block.get("type") == "thinking" and block.get("thinking"):
            reasoning_parts.append(str(block["thinking"]))
        return None
    if event_type == "message_delta":
        usage = event.get("usage")
        return usage if isinstance(usage, dict) else None
    if event_type == "message_start":
        message = event.get("message") or {}
        usage = message.get("usage")
        return usage if isinstance(usage, dict) else None

    if event.get("usage") and isinstance(event["usage"], dict):
        usage = event["usage"]
    else:
        usage = None
    choices = event.get("choices") or []
    if choices:
        delta = choices[0].get("delta") or choices[0].get("message") or {}
        if delta.get("reasoning_content"):
            reasoning_parts.append(str(delta["reasoning_content"]))
        if delta.get("content"):
            content_parts.append(str(delta["content"]))
        thinking = delta.get("thinking")
        if isinstance(thinking, str) and thinking:
            reasoning_parts.append(thinking)
    return usage


def extract_message_text(body: dict[str, Any]) -> tuple[str, str, dict[str, Any] | None]:


    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
    for block in body.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            content_parts.append(str(block["text"]))
        elif block.get("type") == "thinking" and block.get("thinking"):
            reasoning_parts.append(str(block["thinking"]))
    if not content_parts:
        choices = body.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            if message.get("content"):
                content_parts.append(str(message["content"]))
            if message.get("reasoning_content"):
                reasoning_parts.append(str(message["reasoning_content"]))
    return "".join(content_parts), "".join(reasoning_parts), usage


def _strip_json_fence(text: str) -> str:
    return str(text).strip().removeprefix("```json").removesuffix("```").strip()


def _transport_failure_class(
    error: BaseException, attempt: dict[str, Any] | None = None
) -> str:


    attempt = attempt or {}
    detail = str(error).lower()
    reasoning_chars = int(attempt.get("reasoning_chars", 0) or 0)
    content_chars = int(attempt.get("content_chars", 0) or 0)
    response_opened = attempt.get("response_open_seconds") is not None
    if isinstance(error, RunDeadlineExceeded):
        return "run_deadline_exhausted"
    if "call exceeded" in detail:
        if content_chars:
            return "generation_timeout_after_content"
        if reasoning_chars:
            return "generation_timeout_after_reasoning"
        if response_opened:
            return "generation_timeout_before_tokens"
        return "request_timeout_before_response"
    if isinstance(error, urllib.error.HTTPError):
        return (
            "http_transient_error"
            if error.code == 429 or error.code >= 500
            else "http_client_error"
        )
    if isinstance(error, (urllib.error.URLError, TimeoutError)):
        if content_chars:
            return "stream_interrupted_after_content"
        if reasoning_chars:
            return "stream_interrupted_after_reasoning"
        if response_opened:
            return "stream_interrupted_before_tokens"
        return "connection_error_before_response"
    return "transport_error"


def _proxy_map() -> dict[str, str]:


    proxy = os.getenv("DYNACERT_HTTP_PROXY", "").strip()
    return {"http": proxy, "https": proxy} if proxy else {}


def _open(request: urllib.request.Request, timeout: float = 900):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(_proxy_map()))
    return opener.open(request, timeout=timeout)


def stream_post_with_retry(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    schema_name: str,
    label: str,
    retry_delays: tuple[float, ...] = RETRY_DELAYS,
    call_timeout_seconds: float = 600.0,
    deadline: RunDeadline | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any] | None, int, float]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    started = time.monotonic()
    content = ""
    reasoning = ""
    usage: dict[str, Any] | None = None
    attempts = 0
    trace = diagnostics if diagnostics is not None else {}
    trace.clear()
    trace.update(
        {
            "call_timeout_seconds": float(call_timeout_seconds),
            "attempt_details": [],
            "failure_class": None,
        }
    )

    def elapsed() -> float:
        return time.monotonic() - started

    def remaining() -> float:
        local = call_timeout_seconds - elapsed()
        if deadline is not None:
            local = min(
                local,
                deadline.remaining(
                    reserve_seconds=DEFAULT_FINALIZATION_RESERVE_SECONDS
                ),
            )
        if local <= 0:
            if deadline is not None and deadline.expired(
                reserve_seconds=DEFAULT_FINALIZATION_RESERVE_SECONDS
            ):
                raise RunDeadlineExceeded("single-problem wall-clock budget exhausted")
            raise TimeoutError(f"{label} call exceeded {call_timeout_seconds:g}s")
        return local

    try:
        for delay in (*retry_delays, None):
            remaining()
            attempts += 1
            attempt: dict[str, Any] = {
                "attempt": attempts,
                "started_seconds": round(elapsed(), 3),
                "event_count": 0,
                "reasoning_chars": 0,
                "content_chars": 0,
            }
            trace["attempt_details"].append(attempt)
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                content_parts: list[str] = []
                reasoning_parts: list[str] = []
                usage = None
                last_report = started
                with _open(request, timeout=min(900.0, remaining())) as response:
                    attempt["response_open_seconds"] = round(elapsed(), 3)
                    status = getattr(response, "status", None)
                    if status is not None:
                        attempt["http_status"] = int(status)
                    for event in _iter_sse_events(response):
                        remaining()
                        now_elapsed = elapsed()
                        attempt["event_count"] += 1
                        attempt.setdefault("first_event_seconds", round(now_elapsed, 3))
                        attempt["last_event_seconds"] = round(now_elapsed, 3)
                        before_content = sum(len(part) for part in content_parts)
                        before_reasoning = sum(len(part) for part in reasoning_parts)
                        seen_usage = ingest_stream_event(
                            event, content_parts, reasoning_parts
                        )
                        if seen_usage:
                            usage = seen_usage
                            attempt["usage_received"] = True
                        content_chars = sum(len(part) for part in content_parts)
                        reasoning_chars = sum(len(part) for part in reasoning_parts)
                        attempt["content_chars"] = content_chars
                        attempt["reasoning_chars"] = reasoning_chars
                        if reasoning_chars > before_reasoning:
                            attempt.setdefault(
                                "first_reasoning_seconds", round(now_elapsed, 3)
                            )
                            attempt["last_reasoning_seconds"] = round(now_elapsed, 3)
                        if content_chars > before_content:
                            attempt.setdefault(
                                "first_content_seconds", round(now_elapsed, 3)
                            )
                            attempt["last_content_seconds"] = round(now_elapsed, 3)
                        now = time.monotonic()
                        if now - last_report >= 30:
                            print(
                                f"[{schema_name}] still thinking "
                                f"{round(now - started, 1)}s "
                                f"reasoning_chars={reasoning_chars} "
                                f"content_chars={content_chars}",
                                flush=True,
                            )
                            last_report = now
                    attempt["stream_closed_seconds"] = round(elapsed(), 3)
                content = "".join(content_parts)
                reasoning = "".join(reasoning_parts)
                if _has_visible_content(content):
                    attempt["outcome"] = "completed"
                    trace["failure_class"] = None
                    break
                attempt["outcome"] = "empty_response"
                trace["failure_class"] = "empty_response"
                if delay is None:
                    raise RuntimeError(
                        f"{label} returned empty content for {schema_name}"
                    )
                print(
                    f"[{schema_name}] empty_response; retrying in {delay}s",
                    flush=True,
                )
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                transient = error.code == 429 or error.code >= 500
                attempt["outcome"] = _transport_failure_class(error, attempt)
                attempt["error_type"] = type(error).__name__
                attempt["error"] = f"HTTP {error.code}: {detail}"
                trace["failure_class"] = attempt["outcome"]
                if delay is None or not transient:
                    raise RuntimeError(f"{label} HTTP {error.code}: {detail}") from error
                print(
                    f"[{schema_name}] {attempt['outcome']}; retrying in {delay}s",
                    flush=True,
                )
            except RunDeadlineExceeded as error:
                attempt["outcome"] = _transport_failure_class(error, attempt)
                attempt["error_type"] = type(error).__name__
                attempt["error"] = str(error)
                trace["failure_class"] = attempt["outcome"]
                raise
            except (urllib.error.URLError, TimeoutError) as error:
                attempt["outcome"] = _transport_failure_class(error, attempt)
                attempt["error_type"] = type(error).__name__
                attempt["error"] = str(getattr(error, "reason", error))
                trace["failure_class"] = attempt["outcome"]
                if delay is None:
                    detail = getattr(error, "reason", str(error))
                    raise RuntimeError(f"{label} connection failed: {detail}") from error
                print(
                    f"[{schema_name}] {attempt['outcome']}; retrying in {delay}s",
                    flush=True,
                )
            finally:
                attempt["finished_seconds"] = round(elapsed(), 3)
                attempt["duration_seconds"] = round(
                    attempt["finished_seconds"] - attempt["started_seconds"], 3
                )
            if delay is not None:
                trace["retry_sleep_seconds"] = round(
                    float(trace.get("retry_sleep_seconds", 0.0)) + delay, 3
                )
                time.sleep(min(delay, remaining()))
        if not _has_visible_content(content):
            raise RuntimeError(f"{label} returned empty content for {schema_name}")
        duration = round(elapsed(), 3)
        return content, reasoning, usage, attempts, duration
    finally:
        trace["duration_seconds"] = elapsed()
        trace["attempts"] = attempts
        if trace.get("attempt_details"):
            last = trace["attempt_details"][-1]
            trace["event_count"] = sum(
                int(item.get("event_count", 0) or 0)
                for item in trace["attempt_details"]
            )
            trace["reasoning_chars"] = int(last.get("reasoning_chars", 0) or 0)
            trace["content_chars"] = int(last.get("content_chars", 0) or 0)
            trace["last_event_seconds"] = last.get("last_event_seconds")
            if last.get("last_event_seconds") is not None:
                trace["seconds_since_last_event"] = max(
                    0.0, elapsed() - float(last["last_event_seconds"])
                )


class ChatCompletionsTransport:


    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        thinking: bool = True,
        reasoning_effort: str = "medium",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        json_object: bool = False,
        json_schema: bool = False,
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
        label: str = "chat",
        call_timeout_seconds: float = 600.0,
        deadline: RunDeadline | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        self.json_object = json_object
        self.json_schema = json_schema
        self.retry_delays = retry_delays
        self.label = label
        self.call_timeout_seconds = call_timeout_seconds
        self.deadline = deadline
        self.last_call_info: dict[str, Any] = {}

    def _payload(
        self,
        messages: list[dict[str, str]],
        *,
        schema_name: str | None = None,
        schema: dict[str, Any] | None = None,
        strict: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "thinking": {"type": "enabled" if self.thinking else "disabled"},
            "stream": True,
        }
        if self.json_schema and strict and schema_name and schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            }
        elif self.json_object:
            payload["response_format"] = {"type": "json_object"}
        if self.thinking:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    def __call__(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        strict: bool,
        messages: list[dict[str, str]] | None = None,
    ) -> str:
        payload = self._payload(
            messages or _default_messages(prompt),
            schema_name=schema_name,
            schema=schema,
            strict=strict,
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter.ai" in self.base_url:
            headers.update(
                {
                    "HTTP-Referer": "https://openrouter.ai/",
                    "X-Title": "DynaCertBench <REMOTE_HOST> Comparison",
                }
            )
        diagnostics: dict[str, Any] = {}
        try:
            content, reasoning, usage, attempts, duration = stream_post_with_retry(
                url=f"{self.base_url}/chat/completions",
                headers=headers,
                payload=payload,
                schema_name=schema_name,
                label=self.label,
                retry_delays=self.retry_delays,
                call_timeout_seconds=self.call_timeout_seconds,
                deadline=self.deadline,
                diagnostics=diagnostics,
            )
        except Exception as error:
            self.last_call_info = {
                **diagnostics,
                "error_type": type(error).__name__,
                "error": str(error),
                "conversation_messages": len(payload["messages"]),
                "protocol": "chat.completions",
            }
            raise
        self.last_call_info = {
            **diagnostics,
            "usage": usage,
            "duration_seconds": duration,
            "attempts": attempts,
            "reasoning_content": reasoning or None,
            "conversation_messages": len(payload["messages"]),
            "protocol": "chat.completions",
        }
        print(
            f"[{schema_name}] thinking={self.thinking} effort={self.reasoning_effort} "
            f"duration={duration}s reasoning_chars={len(reasoning)} content_chars={len(content)}",
            flush=True,
        )
        return _strip_json_fence(content)


class ClaudeMessagesTransport:


    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        thinking: bool = True,
        reasoning_effort: str = "medium",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        thinking_budget: int = DEFAULT_THINKING_BUDGET,
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
        label: str = "claude",
        call_timeout_seconds: float = 600.0,
        deadline: RunDeadline | None = None,
    ) -> None:
        del reasoning_effort
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.thinking = thinking
        self.max_tokens = max_tokens
        self.thinking_budget = thinking_budget
        self.retry_delays = retry_delays
        self.label = label
        self.call_timeout_seconds = call_timeout_seconds
        self.deadline = deadline
        self.last_call_info: dict[str, Any] = {}

    def _payload(self, prompt: str, messages: list[dict[str, str]] | None) -> dict[str, Any]:
        system, turns = split_system_and_messages(messages or _default_messages(prompt))
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": turns,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if self.thinking:

            budget = max(1024, int(self.thinking_budget))
            payload["max_tokens"] = max(int(self.max_tokens), budget + 8192)
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
        return payload

    def __call__(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        strict: bool,
        messages: list[dict[str, str]] | None = None,
    ) -> str:
        del schema, strict
        payload = self._payload(prompt, messages)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "anthropic-beta": ANTHROPIC_BETA,
            "Content-Type": "application/json",
        }
        diagnostics: dict[str, Any] = {}
        try:
            content, reasoning, usage, attempts, duration = stream_post_with_retry(
                url=f"{self.base_url}/messages",
                headers=headers,
                payload=payload,
                schema_name=schema_name,
                label=self.label,
                retry_delays=self.retry_delays,
                call_timeout_seconds=self.call_timeout_seconds,
                deadline=self.deadline,
                diagnostics=diagnostics,
            )
        except Exception as error:
            self.last_call_info = {
                **diagnostics,
                "error_type": type(error).__name__,
                "error": str(error),
                "conversation_messages": len(payload["messages"]),
                "protocol": "messages",
            "thinking": payload.get("thinking"),
            }
            raise
        self.last_call_info = {
            **diagnostics,
            "usage": usage,
            "duration_seconds": duration,
            "attempts": attempts,
            "reasoning_content": reasoning or None,
            "conversation_messages": len(payload["messages"]),
            "protocol": "messages",
            "thinking": payload.get("thinking"),
        }
        print(
            f"[{schema_name}] thinking={self.thinking} budget={payload.get('thinking')} "
            f"duration={duration}s reasoning_chars={len(reasoning)} content_chars={len(content)}",
            flush=True,
        )
        return _strip_json_fence(content)


def make_http_transport(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    thinking: bool = True,
    reasoning_effort: str = "medium",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    thinking_budget: int = DEFAULT_THINKING_BUDGET,
    json_object: bool | None = None,
    json_schema: bool = False,
    call_timeout_seconds: float = 600.0,
    deadline: RunDeadline | None = None,
) -> ChatCompletionsTransport | ClaudeMessagesTransport:


    if not api_key:
        raise RuntimeError("API key is empty")
    if not model:
        raise RuntimeError("model name is empty")
    if provider == "claude":
        return ClaudeMessagesTransport(
            api_key=api_key,
            base_url=base_url,
            model=model,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            call_timeout_seconds=call_timeout_seconds,
            deadline=deadline,
        )
    if json_object is None:
        json_object = provider == "deepseek"
    return ChatCompletionsTransport(
        api_key=api_key,
        base_url=base_url,
        model=model,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
        json_object=json_object,
        json_schema=json_schema,
        label=provider,
        call_timeout_seconds=call_timeout_seconds,
        deadline=deadline,
    )
