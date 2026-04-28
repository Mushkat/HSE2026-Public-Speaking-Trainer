import httpx

from app.core.local_llm import LlamaCppHTTPClient, _extract_first_json_fragment, parse_json_strict


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = "{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


def test_extract_first_json_fragment_tolerates_prefix_and_suffix():
    fragment = _extract_first_json_fragment("prelude\n{\"items\":[\"a\"]}\npost")
    assert fragment == '{"items":["a"]}'


def test_parse_json_strict_extracts_first_object():
    text = "Вот ответ:\n{\"items\":[\"a\",\"b\"]}\nи хвост"
    parsed = parse_json_strict(text)
    assert parsed["items"] == ["a", "b"]


def test_llama_cpp_client_uses_chat_endpoint_and_request_id(monkeypatch):
    calls = {"n": 0}

    def _fake_post(self, url, json, headers):
        calls["n"] += 1
        assert url.endswith("/v1/chat/completions")
        assert headers.get("X-Request-ID") == "req-1"
        assert json.get("stream") is False
        return _Resp({"choices": [{"finish_reason": "stop", "message": {"content": '{"items": ["Что вы сделаете в первую очередь по плану запуска сервиса?"]}'}}]})

    monkeypatch.setattr("httpx.Client.post", _fake_post)
    client = LlamaCppHTTPClient("http://llm:8080")
    payload = client.generate_json(system_prompt="sys", user_prompt="usr", request_id="req-1")

    assert payload and isinstance(payload.get("items"), list)
    assert calls["n"] == 1
    assert client.last_call_meta["endpoint"] == "/v1/chat/completions"


def test_build_chat_body_does_not_use_double_newline_stop_sequence() -> None:
    client = LlamaCppHTTPClient("http://llm:8080")

    body = client._build_chat_body(
        system_prompt="sys",
        user_prompt="user",
        max_tokens=128,
        temperature=0.2,
    )

    assert body["stream"] is False
    assert "stop" not in body


def test_llama_cpp_client_records_timeout_failure_reason(monkeypatch):
    def _fake_post(self, url, json, headers):
        raise httpx.ReadTimeout("boom")

    monkeypatch.setattr("httpx.Client.post", _fake_post)
    client = LlamaCppHTTPClient("http://llm:8080")
    payload = client.generate_json(system_prompt="sys", user_prompt="usr", request_id="req-timeout")

    assert payload is None
    assert client.last_call_meta["failure_reason"] == "timeout"
    assert client.last_call_meta["error_type"] == "ReadTimeout"
