from __future__ import annotations

import logging
from urllib.parse import urljoin

import requests
from fastapi import APIRouter

from app.core.config import settings
from app.core.messages_ru import LLM_DISABLED, LLM_READY, LLM_STARTING, LLM_STATUS_CODE, LLM_TIMEOUT, LLM_UNAVAILABLE

router = APIRouter(prefix="/system", tags=["system"])
logger = logging.getLogger(__name__)


@router.get("/llm-status")
def get_llm_status() -> dict[str, str | bool]:
    if not settings.local_llm_enabled:
        return {
            "available": False,
            "status": "unavailable",
            "detail": LLM_DISABLED,
        }

    base_url = settings.local_llm_base_url.rstrip("/") + "/"
    health_url = urljoin(base_url, "health")
    timeout = min(2.0, max(1.0, float(settings.local_llm_timeout_sec)))

    try:
        response = requests.get(health_url, timeout=timeout)
        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        raw_status = str((payload or {}).get("status") or "").lower()
        if response.ok and raw_status in {"ok", "ready", "healthy"}:
            return {
                "available": True,
                "status": "ready",
                "detail": LLM_READY,
            }
        if response.ok:
            return {
                "available": False,
                "status": "starting",
                "detail": LLM_STARTING,
            }
        return {
            "available": False,
            "status": "starting",
            "detail": LLM_STATUS_CODE.format(status_code=response.status_code),
        }
    except requests.Timeout:
        logger.warning("llm status timed out", extra={"health_url": health_url})
        return {
            "available": False,
            "status": "starting",
            "detail": LLM_TIMEOUT,
        }
    except requests.RequestException as exc:
        logger.warning("llm status unavailable", extra={"health_url": health_url, "error": str(exc)})
        return {
            "available": False,
            "status": "unavailable",
            "detail": LLM_UNAVAILABLE,
        }
