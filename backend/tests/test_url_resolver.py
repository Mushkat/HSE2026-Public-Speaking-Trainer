from __future__ import annotations

import socket

import pytest
from fastapi import HTTPException

from app.core.messages_ru import MEDIA_URL_NOT_SUPPORTED_PLATFORM, MEDIA_URL_UNSUPPORTED_HOST
from app.services.url_resolver import YANDEX_DISK_UNAVAILABLE, resolve_media_url


BLOCKED_HOSTS = {"localhost"}
BLOCKED_VIDEO_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "rutube.ru", "www.rutube.ru"}


def _ok_dns(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_resolver_returns_direct_url_unchanged(monkeypatch):
    monkeypatch.setattr("app.services.url_resolver.socket.getaddrinfo", _ok_dns)

    resolved = resolve_media_url(
        "https://example.com/media.mp4",
        blocked_hosts=BLOCKED_HOSTS,
        blocked_video_hosts=BLOCKED_VIDEO_HOSTS,
        url_max_length=2048,
    )

    assert resolved.provider == "direct"
    assert resolved.final_url == "https://example.com/media.mp4"


def test_resolver_yandex_uses_public_api(monkeypatch):
    monkeypatch.setattr("app.services.url_resolver.socket.getaddrinfo", _ok_dns)

    def _fake_get(url, params=None, timeout=None):
        assert "cloud-api.yandex.net" in url
        assert params and "disk.360.yandex.ru" in params.get("public_key", "")
        return _FakeResponse(200, {"href": "https://downloader.disk.yandex.ru/disk/abc123"})

    monkeypatch.setattr("app.services.url_resolver.httpx.get", _fake_get)

    resolved = resolve_media_url(
        "https://disk.360.yandex.ru/i/xjNJk-III9kzUQ",
        blocked_hosts=BLOCKED_HOSTS,
        blocked_video_hosts=BLOCKED_VIDEO_HOSTS,
        url_max_length=2048,
    )

    assert resolved.provider == "yandex_disk"
    assert resolved.final_url == "https://downloader.disk.yandex.ru/disk/abc123"


def test_resolver_rejects_blocked_video_hosts(monkeypatch):
    monkeypatch.setattr("app.services.url_resolver.socket.getaddrinfo", _ok_dns)

    with pytest.raises(HTTPException) as exc:
        resolve_media_url(
            "https://youtube.com/watch?v=1",
            blocked_hosts=BLOCKED_HOSTS,
            blocked_video_hosts=BLOCKED_VIDEO_HOSTS,
            url_max_length=2048,
        )

    assert exc.value.detail == MEDIA_URL_NOT_SUPPORTED_PLATFORM


def test_resolver_rejects_private_ip_resolution(monkeypatch):
    def _private_dns(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr("app.services.url_resolver.socket.getaddrinfo", _private_dns)

    with pytest.raises(HTTPException) as exc:
        resolve_media_url(
            "https://example.com/video.mp4",
            blocked_hosts=BLOCKED_HOSTS,
            blocked_video_hosts=BLOCKED_VIDEO_HOSTS,
            url_max_length=2048,
        )

    assert exc.value.detail == MEDIA_URL_UNSUPPORTED_HOST


def test_resolver_yandex_unavailable_returns_friendly_error(monkeypatch):
    monkeypatch.setattr("app.services.url_resolver.socket.getaddrinfo", _ok_dns)
    monkeypatch.setattr("app.services.url_resolver.httpx.get", lambda *args, **kwargs: _FakeResponse(404, {}))

    with pytest.raises(HTTPException) as exc:
        resolve_media_url(
            "https://disk.yandex.ru/d/some-public-id",
            blocked_hosts=BLOCKED_HOSTS,
            blocked_video_hosts=BLOCKED_VIDEO_HOSTS,
            url_max_length=2048,
        )

    assert exc.value.detail == YANDEX_DISK_UNAVAILABLE
