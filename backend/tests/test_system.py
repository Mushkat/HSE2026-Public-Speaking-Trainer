from unittest.mock import Mock

import requests

from app.api.routes import system


def test_llm_status_ready(client, monkeypatch):
    response = Mock()
    response.ok = True
    response.status_code = 200
    response.headers = {"content-type": "application/json"}
    response.json.return_value = {"status": "ok"}
    monkeypatch.setattr(system.settings, "local_llm_enabled", True)
    monkeypatch.setattr(system.requests, "get", lambda *args, **kwargs: response)

    payload = client.get("/system/llm-status").json()

    assert payload == {
        "available": True,
        "status": "ready",
        "detail": "AI-разделы будут сгенерированы автоматически.",
    }


def test_llm_status_unavailable_when_disabled(client, monkeypatch):
    monkeypatch.setattr(system.settings, "local_llm_enabled", False)

    payload = client.get("/system/llm-status").json()

    assert payload["available"] is False
    assert payload["status"] == "unavailable"


def test_llm_status_starting_on_timeout(client, monkeypatch):
    monkeypatch.setattr(system.settings, "local_llm_enabled", True)

    def _raise_timeout(*args, **kwargs):
        raise requests.Timeout("slow")

    monkeypatch.setattr(system.requests, "get", _raise_timeout)

    payload = client.get("/system/llm-status").json()

    assert payload["available"] is False
    assert payload["status"] == "starting"
