from __future__ import annotations

from dataclasses import dataclass
import socket
from ipaddress import ip_address
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, status

from app.core.messages_ru import (
    MEDIA_URL_FETCH_FAILED,
    MEDIA_URL_INVALID,
    MEDIA_URL_NOT_SUPPORTED_PLATFORM,
    MEDIA_URL_REQUIRED,
    MEDIA_URL_UNSUPPORTED_HOST,
)

YANDEX_DISK_UNAVAILABLE = "Ссылка Яндекс.Диска недоступна или закрыта."
_YANDEX_API = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
_YANDEX_HOSTS = {
    "disk.yandex.ru",
    "yadi.sk",
    "disk.360.yandex.ru",
}


@dataclass(frozen=True)
class ResolvedUrlResult:
    final_url: str
    provider: str
    filename_hint: str | None = None
    content_type_hint: str | None = None


def _is_blocked_ip(value: str) -> bool:
    try:
        address = ip_address(value)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _host_matches(host: str, items: set[str]) -> bool:
    return any(host == item or host.endswith(f".{item}") for item in items)


def validate_public_media_url(
    raw_url: str,
    *,
    blocked_hosts: set[str],
    blocked_video_hosts: set[str],
    url_max_length: int,
) -> str:
    url = (raw_url or "").strip()
    if not url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_REQUIRED)
    if len(url) > url_max_length:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_INVALID)

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_INVALID)

    host = parsed.hostname.lower()
    if _host_matches(host, blocked_hosts):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_UNSUPPORTED_HOST)
    if _host_matches(host, blocked_video_hosts):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_NOT_SUPPORTED_PLATFORM)
    if _is_blocked_ip(host):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_UNSUPPORTED_HOST)

    try:
        resolved = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_FETCH_FAILED)
    for info in resolved:
        if _is_blocked_ip(info[4][0]):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_UNSUPPORTED_HOST)

    return url


def _resolve_yandex_disk_url(
    public_url: str,
    *,
    blocked_hosts: set[str],
    blocked_video_hosts: set[str],
    url_max_length: int,
) -> ResolvedUrlResult:
    try:
        response = httpx.get(
            _YANDEX_API,
            params={"public_key": public_url},
            timeout=8.0,
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=YANDEX_DISK_UNAVAILABLE)

    if response.status_code in {403, 404}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=YANDEX_DISK_UNAVAILABLE)
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_FETCH_FAILED)

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    href = payload.get("href") if isinstance(payload, dict) else None
    if not isinstance(href, str) or not href.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=YANDEX_DISK_UNAVAILABLE)

    final_url = validate_public_media_url(
        href,
        blocked_hosts=blocked_hosts,
        blocked_video_hosts=blocked_video_hosts,
        url_max_length=url_max_length,
    )
    return ResolvedUrlResult(final_url=final_url, provider="yandex_disk")


def resolve_media_url(
    input_url: str,
    *,
    blocked_hosts: set[str],
    blocked_video_hosts: set[str],
    url_max_length: int,
) -> ResolvedUrlResult:
    normalized = validate_public_media_url(
        input_url,
        blocked_hosts=blocked_hosts,
        blocked_video_hosts=blocked_video_hosts,
        url_max_length=url_max_length,
    )
    host = (urlparse(normalized).hostname or "").lower()

    if _host_matches(host, _YANDEX_HOSTS):
        return _resolve_yandex_disk_url(
            normalized,
            blocked_hosts=blocked_hosts,
            blocked_video_hosts=blocked_video_hosts,
            url_max_length=url_max_length,
        )

    return ResolvedUrlResult(final_url=normalized, provider="direct")
