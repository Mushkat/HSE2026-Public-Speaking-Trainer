from __future__ import annotations

import json
import re
from typing import Any, Callable

from app.core.local_llm import get_local_llm_client, is_llm_enabled


SchemaValidator = Callable[[dict[str, Any]], bool]


def is_russian_text(text: str, *, min_cyrillic_chars: int = 30) -> bool:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", str(text or ""))
    if not letters:
        return False
    cyrillic = re.findall(r"[А-Яа-яЁё]", text)
    english_words = re.findall(r"\b[A-Za-z]{3,}\b", text)
    cyr_ratio = len(cyrillic) / max(1, len(letters))
    if len(cyrillic) >= min_cyrillic_chars:
        return len(english_words) <= 3
    return cyr_ratio >= 0.60 and len(english_words) <= 2


def generate_json_block(
    *,
    block_name: str,
    system_prompt: str,
    user_prompt: str,
    schema_validator: SchemaValidator,
    max_tokens: int,
    temperature: float,
    request_id: str,
    session_id: str,
    client: Any | None = None,
    llm_enabled: bool | None = None,
) -> dict[str, Any]:
    enabled = is_llm_enabled() if llm_enabled is None else bool(llm_enabled)
    if not enabled:
        return {"ok": False, "reason": "llm_disabled", "request_id": request_id, "llm_latency_ms": None, "content_snippet": ""}

    client = client or get_local_llm_client()
    if client is None:
        return {"ok": False, "reason": "llm_unreachable", "request_id": request_id, "llm_latency_ms": None, "content_snippet": ""}

    def _extract_json_fragment(content: str) -> str:
        stripped = (content or "").strip()
        first = stripped.find("{")
        last = stripped.rfind("}")
        if first < 0 or last < 0 or first >= last:
            raise ValueError("json_extract_failed")
        return stripped[first : last + 1]

    def _call(prompt: str, req_id: str) -> tuple[dict[str, Any] | None, str, int | None, str | None]:
        try:
            content, _, _ = client.call_llm(
                system_prompt=system_prompt,
                user_prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                request_id=req_id,
                session_id=session_id,
            )
            snippet = (content or "").strip()[:240]
            parsed = json.loads(_extract_json_fragment(content))
            latency = (client.last_call_meta or {}).get("elapsed_ms")
            return parsed if isinstance(parsed, dict) else None, snippet, latency if isinstance(latency, int) else None, None
        except ValueError as exc:
            reason = str(exc) if str(exc) == "json_extract_failed" else "json_parse_failed"
            return None, ((client.last_call_meta or {}).get("raw_response") or "")[:240], None, reason
        except Exception:
            failure = str((client.last_call_meta or {}).get("failure_reason") or "http_error")
            if "timeout" in failure:
                reason = "timeout"
            elif failure in {"request_exception", "connection_error"}:
                reason = "llm_unreachable"
            elif failure in {"json_fragment_not_found"}:
                reason = "json_extract_failed"
            elif failure in {"json_decode_error", "json_object_expected", "json_parse_failure"}:
                reason = "json_parse_failed"
            elif failure in {"empty_response", "empty_content"}:
                reason = "empty_content"
            elif "http" in failure or "status" in failure:
                reason = "http_error"
            else:
                reason = "http_error"
            latency = (client.last_call_meta or {}).get("elapsed_ms")
            return None, ((client.last_call_meta or {}).get("raw_response") or "")[:240], latency if isinstance(latency, int) else None, reason

    parsed, snippet, latency_ms, reason = _call(user_prompt, request_id)
    if isinstance(parsed, dict) and schema_validator(parsed):
        return {
            "ok": True,
            "payload": parsed,
            "request_id": request_id,
            "llm_latency_ms": latency_ms,
            "content_snippet": snippet,
            "reason": None,
        }

    if reason in {"json_extract_failed", "json_parse_failed"}:
        repair_prompt = f"{user_prompt}\n\nВерни только JSON без любого дополнительного текста."
        repaired_id = f"{request_id}-repair"
        repaired, repaired_snippet, repaired_latency, repaired_reason = _call(repair_prompt, repaired_id)
        if isinstance(repaired, dict) and schema_validator(repaired):
            return {
                "ok": True,
                "payload": repaired,
                "request_id": repaired_id,
                "llm_latency_ms": repaired_latency,
                "content_snippet": repaired_snippet,
                "reason": None,
            }
        if repaired_reason in {"json_extract_failed", "json_parse_failed"}:
            return {
                "ok": False,
                "reason": "json_parse_failed",
                "request_id": repaired_id,
                "llm_latency_ms": repaired_latency,
                "content_snippet": repaired_snippet,
            }
        if repaired_reason:
            return {
                "ok": False,
                "reason": repaired_reason,
                "request_id": repaired_id,
                "llm_latency_ms": repaired_latency,
                "content_snippet": repaired_snippet,
            }
        return {"ok": False, "reason": "schema_invalid", "request_id": repaired_id, "llm_latency_ms": repaired_latency, "content_snippet": repaired_snippet}

    return {
        "ok": False,
        "reason": reason or "schema_invalid",
        "request_id": request_id,
        "llm_latency_ms": latency_ms,
        "content_snippet": snippet,
    }
