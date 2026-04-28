from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)
_CHAT_ENDPOINT = "/v1/chat/completions"


def _build_semaphore() -> threading.BoundedSemaphore:
    size = max(1, int(settings.local_llm_max_parallel_requests))
    return threading.BoundedSemaphore(value=size)


_REQUEST_SEMAPHORE = _build_semaphore()


@dataclass
class LocalLLMOptions:
    temperature: float | None = None
    max_tokens: int | None = None


class LLMJSONParseError(ValueError):
    pass


def _truncate(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _extract_first_json_fragment(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        raise LLMJSONParseError("empty_response")
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first < 0 or last < 0 or first >= last:
        raise LLMJSONParseError("json_fragment_not_found")
    return stripped[first : last + 1]


def parse_json_strict(text: str) -> dict[str, Any]:
    fragment = _extract_first_json_fragment(text)
    parsed = json.loads(fragment)
    if not isinstance(parsed, dict):
        raise LLMJSONParseError("json_object_expected")
    return parsed


def _normalize_failure_reason(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, LLMJSONParseError):
        return str(exc) or "json_parse_failure"
    if isinstance(exc, httpx.HTTPStatusError):
        return "http_error"
    if isinstance(exc, httpx.RequestError):
        return "request_exception"
    if isinstance(exc, RuntimeError):
        return str(exc) or "runtime_error"
    return exc.__class__.__name__.lower() or "unknown_error"


class LlamaCppHTTPClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._last_call_meta: dict[str, Any] = {}

    @property
    def last_call_meta(self) -> dict[str, Any]:
        return dict(self._last_call_meta)

    @staticmethod
    def _extract_chat_text(payload: dict[str, Any]) -> tuple[str, str | None]:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("chat_choices_missing")

        first = choices[0] if isinstance(choices[0], dict) else {}
        finish_reason = first.get("finish_reason") if isinstance(first.get("finish_reason"), str) else None
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = message.get("content")
        if isinstance(content, str):
            return content, finish_reason
        raise RuntimeError("chat_message_content_missing")

    def _dump_debug_files(
        self,
        *,
        session_id: str,
        request_id: str,
        request_body: dict[str, Any],
        response_payload: dict[str, Any] | None,
        extracted_content: str,
    ) -> None:
        if not settings.debug_llm:
            return
        base_dir = Path(settings.storage_root) / "debug" / "llm" / str(session_id)
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / f"{request_id}_request.json").write_text(
            json.dumps(request_body, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (base_dir / f"{request_id}_response.json").write_text(
            json.dumps(response_payload or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (base_dir / f"{request_id}_content.txt").write_text(extracted_content or "", encoding="utf-8")

    def _post(self, *, endpoint: str, body: dict[str, Any], request_id: str) -> tuple[dict[str, Any], int, str]:
        if endpoint != _CHAT_ENDPOINT:
            logger.error("local_llm unsupported endpoint requested", extra={"request_id": request_id, "endpoint": endpoint})
            raise RuntimeError("unsupported_llm_endpoint")

        connect_timeout = 5.0
        read_timeout = max(120.0, float(settings.local_llm_timeout_sec))
        write_timeout = 30.0
        pool_timeout = 5.0
        self._last_call_meta.update(
            {
                "request_id": request_id,
                "endpoint": endpoint,
                "status_code": None,
                "timeout_connect_sec": connect_timeout,
                "timeout_read_sec": read_timeout,
                "timeout_write_sec": write_timeout,
                "timeout_pool_sec": pool_timeout,
                "request_body": body,
                "response_payload": None,
                "raw_response": "",
                "raw_bytes": 0,
                "failure_reason": None,
                "error_type": None,
                "error_message": None,
            }
        )
        try:
            with httpx.Client(timeout=httpx.Timeout(connect=connect_timeout, read=read_timeout, write=write_timeout, pool=pool_timeout)) as client:
                response = client.post(
                    f"{self.base_url}{endpoint}",
                    json=body,
                    headers={"X-Request-ID": request_id},
                )
            raw_text = response.text or ""
            status_code = int(response.status_code)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("llm_payload_not_object")
            self._last_call_meta.update(
                {
                    "status_code": status_code,
                    "raw_response": raw_text,
                    "raw_bytes": len(raw_text.encode("utf-8", errors="ignore")),
                    "response_payload": payload,
                }
            )
            return payload, status_code, raw_text
        except Exception as exc:
            raw_text = getattr(locals().get("response", None), "text", "") or ""
            status_code = getattr(locals().get("response", None), "status_code", None)
            self._last_call_meta.update(
                {
                    "status_code": int(status_code) if isinstance(status_code, int) else status_code,
                    "raw_response": raw_text,
                    "raw_bytes": len(raw_text.encode("utf-8", errors="ignore")),
                    "failure_reason": _normalize_failure_reason(exc),
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                }
            )
            raise

    def _build_chat_body(self, *, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float) -> dict[str, Any]:
        safe_temperature = max(0.0, min(1.0, float(temperature)))
        safe_tokens = max(32, int(max_tokens))
        return {
            "model": "local",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": safe_temperature,
            "max_tokens": safe_tokens,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "stream": False,
        }

    def call_llm(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        request_id: str,
        session_id: str,
    ) -> tuple[str, str | None, dict[str, Any]]:
        endpoint = _CHAT_ENDPOINT
        body = self._build_chat_body(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        acquire_started = time.perf_counter()
        acquired = _REQUEST_SEMAPHORE.acquire(timeout=120.0)
        queue_wait_ms = int((time.perf_counter() - acquire_started) * 1000)
        if not acquired:
            raise RuntimeError("llm_parallel_limit_timeout")

        call_started = time.perf_counter()
        try:
            payload, status_code, raw_response = self._post(endpoint=endpoint, body=body, request_id=request_id)
            text, finish_reason = self._extract_chat_text(payload)
            elapsed_ms = int((time.perf_counter() - call_started) * 1000)
            self._last_call_meta.update(
                {
                    "queue_wait_ms": queue_wait_ms,
                    "elapsed_ms": elapsed_ms,
                    "finish_reason": finish_reason,
                    "stream": False,
                    "request_body": body,
                    "input_chars": len(user_prompt),
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "extracted_text_chars": len(text),
                    "response_chars": len(raw_response),
                }
            )
            self._dump_debug_files(
                session_id=session_id,
                request_id=request_id,
                request_body=body,
                response_payload=payload,
                extracted_content=text,
            )
            return text, finish_reason, body
        finally:
            _REQUEST_SEMAPHORE.release()

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        options: LocalLLMOptions | None = None,
        trace_id: str | None = None,
        purpose: str = "generic",
        request_id: str,
        session_id: str = "unknown_session",
    ) -> dict[str, Any] | None:
        opts = options or LocalLLMOptions()
        temperature = settings.local_llm_temperature if opts.temperature is None else float(opts.temperature)
        max_tokens = settings.local_llm_max_tokens if opts.max_tokens is None else int(opts.max_tokens)
        retries = max(0, int(settings.local_llm_max_retries))

        working_user_prompt = user_prompt
        for attempt in range(retries + 1):
            try:
                raw_text, finish_reason, request_body = self.call_llm(
                    system_prompt=system_prompt,
                    user_prompt=working_user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    request_id=request_id,
                    session_id=session_id,
                )
                if len((raw_text or "").strip()) < 2:
                    raise LLMJSONParseError("empty_content")
                parsed = parse_json_strict(raw_text)
                logger.warning(
                    "local_llm generate_json success",
                    extra={
                        "request_id": request_id,
                        "trace_id": trace_id,
                        "purpose": purpose,
                        "attempt": attempt,
                        "endpoint": self._last_call_meta.get("endpoint"),
                        "elapsed_ms": self._last_call_meta.get("elapsed_ms"),
                        "status_code": self._last_call_meta.get("status_code"),
                        "raw_bytes": self._last_call_meta.get("raw_bytes"),
                        "finish_reason": finish_reason,
                    },
                )
                if settings.debug_llm:
                    logger.warning(
                        "debug_llm call success",
                        extra={
                            "request_id": request_id,
                            "trace_id": trace_id,
                            "purpose": purpose,
                            "attempt": attempt,
                            "endpoint": self._last_call_meta.get("endpoint"),
                            "timeout_connect_sec": self._last_call_meta.get("timeout_connect_sec"),
                            "timeout_read_sec": self._last_call_meta.get("timeout_read_sec"),
                            "timeout_total_sec": self._last_call_meta.get("timeout_total_sec"),
                            "stream": False,
                            "status_code": self._last_call_meta.get("status_code"),
                            "elapsed_ms": self._last_call_meta.get("elapsed_ms"),
                            "input_chars": len(working_user_prompt),
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                            "raw_bytes": self._last_call_meta.get("raw_bytes"),
                            "content_chars": len(raw_text),
                            "content_preview": _truncate(raw_text, 300),
                            "request_preview": _truncate(json.dumps(request_body, ensure_ascii=False), 300),
                            "parse_result": "success",
                        },
                    )
                return parsed if isinstance(parsed, dict) else None
            except Exception as exc:
                failure_reason = _normalize_failure_reason(exc)
                self._last_call_meta.update(
                    {
                        "failure_reason": failure_reason,
                        "error_type": exc.__class__.__name__,
                        "error_message": str(exc),
                        "parse_result": "failed",
                    }
                )
                logger.warning(
                    "local_llm generate_json failed: %s",
                    exc,
                    extra={
                        "request_id": request_id,
                        "trace_id": trace_id,
                        "purpose": purpose,
                        "attempt": attempt,
                        "endpoint": self._last_call_meta.get("endpoint", _CHAT_ENDPOINT),
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                        "failure_reason": failure_reason,
                    },
                )
                if settings.debug_llm:
                    logger.warning(
                        "debug_llm call failed",
                        extra={
                            "request_id": request_id,
                            "trace_id": trace_id,
                            "purpose": purpose,
                            "attempt": attempt,
                            "endpoint": self._last_call_meta.get("endpoint", _CHAT_ENDPOINT),
                            "status_code": self._last_call_meta.get("status_code"),
                            "raw_bytes": self._last_call_meta.get("raw_bytes", 0),
                            "raw_preview": _truncate(self._last_call_meta.get("raw_response", ""), 300),
                            "error_type": exc.__class__.__name__,
                            "error_message": str(exc),
                            "parse_result": "failed",
                        },
                    )
                if attempt < retries:
                    max_tokens = max(64, int(max_tokens * 0.8))
                    working_user_prompt = user_prompt[:700] + "\n\nВерни только JSON без текста."
                    continue

        return None


def is_llm_enabled() -> bool:
    return bool(settings.local_llm_enabled)


def get_local_llm_client() -> LlamaCppHTTPClient | None:
    if not is_llm_enabled():
        return None
    return LlamaCppHTTPClient(settings.local_llm_base_url)
