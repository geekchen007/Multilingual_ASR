"""Qwen-ASR request and error handling checks without remote API calls."""

import base64

import pytest
import requests

from asr_eval.providers import transcribe


@pytest.fixture
def qwen(tmp_path, monkeypatch):
    """Provide a local audio file and an isolated API credential."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    path = tmp_path / "clip.wav"
    path.write_bytes(b"wave-audio")
    return {
        "kind": "qwen_asr",
        "model": "qwen3-asr-flash",
        "url": "https://example.test/chat/completions",
        "key_env": "DASHSCOPE_API_KEY",
        "params": {"asr_options": {"enable_itn": False}},
    }, path


@pytest.mark.parametrize(
    "language, hint",
    [
        ("auto", None),
        ("ms+en", None),
        ("zh", "zh"),
        ("tl", "fil"),
    ],
)
def test_qwen_request(qwen, monkeypatch, language, hint):
    snapshot, path = qwen
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"choices":[{"message":{"content":"recognized"}}]}'
        return response

    monkeypatch.setattr("asr_eval.providers.requests.post", post)
    assert transcribe(snapshot, path, language) == "recognized"
    url, request = calls[0]
    assert url == snapshot["url"]
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["allow_redirects"] is False
    payload = request["json"]
    assert payload["model"] == snapshot["model"]
    assert payload["stream"] is False
    content = payload["messages"][0]["content"][0]
    prefix, encoded = content["input_audio"]["data"].split(",", 1)
    assert content["type"] == "input_audio"
    assert prefix == "data:audio/wav;base64"
    assert base64.b64decode(encoded) == path.read_bytes()
    assert payload["asr_options"].get("language") == hint
    assert snapshot["params"] == {"asr_options": {"enable_itn": False}}


def test_qwen_requires_key(qwen, monkeypatch):
    snapshot, path = qwen
    monkeypatch.delenv("DASHSCOPE_API_KEY")
    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        transcribe(snapshot, path, "auto")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": None}}]},
    ],
)
def test_qwen_rejects_invalid_response(qwen, monkeypatch, body):
    snapshot, path = qwen

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return body

    monkeypatch.setattr("asr_eval.providers.requests.post", lambda *a, **kw: Response())
    with pytest.raises(ValueError, match="no text"):
        transcribe(snapshot, path, "auto")


def test_qwen_preserves_http_failure(qwen, monkeypatch):
    snapshot, path = qwen

    def post(*args, **kwargs):
        response = requests.Response()
        response.status_code = 401
        return response

    monkeypatch.setattr("asr_eval.providers.requests.post", post)
    with pytest.raises(requests.HTTPError):
        transcribe(snapshot, path, "auto")


@pytest.fixture
def fun(qwen):
    """Reuse isolated audio and credentials for the native DashScope protocol."""
    snapshot, path = qwen
    snapshot.update(kind="fun_asr", model="fun-asr-flash-2026-06-15", params={})
    return snapshot, path


@pytest.mark.parametrize(
    "language, send_language, hint",
    [
        ("auto", True, None),
        ("ms+en", True, None),
        ("zh", True, ["zh"]),
        ("tl", True, ["tl"]),
        ("zh", False, None),
    ],
)
def test_fun_request(fun, monkeypatch, language, send_language, hint):
    snapshot, path = fun
    snapshot["send_language"] = send_language
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs)
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"output":{"text":"recognized by Fun-ASR"}}'
        return response

    monkeypatch.setattr("asr_eval.providers.requests.post", post)
    assert transcribe(snapshot, path, language) == "recognized by Fun-ASR"
    request = calls[0]
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["headers"]["X-DashScope-SSE"] == "disable"
    assert request["allow_redirects"] is False
    payload = request["json"]
    content = payload["input"]["messages"][0]["content"][0]
    assert (
        base64.b64decode(content["input_audio"]["data"].split(",")[1])
        == path.read_bytes()
    )
    assert payload["model"] == snapshot["model"]
    assert payload["parameters"]["format"] == "wav"
    assert payload["parameters"].get("language_hints") == hint
    assert snapshot["params"] == {}


@pytest.mark.parametrize("body", [{}, {"output": None}, {"output": {"text": None}}])
def test_fun_rejects_invalid_response(fun, monkeypatch, body):
    snapshot, path = fun

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return body

    monkeypatch.setattr("asr_eval.providers.requests.post", lambda *a, **kw: Response())
    with pytest.raises(ValueError, match="no text"):
        transcribe(snapshot, path, "auto")


def test_fun_requires_key(fun, monkeypatch):
    snapshot, path = fun
    monkeypatch.delenv("DASHSCOPE_API_KEY")
    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        transcribe(snapshot, path, "auto")


def test_fun_preserves_http_failure(fun, monkeypatch):
    snapshot, path = fun

    def post(*args, **kwargs):
        response = requests.Response()
        response.status_code = 429
        return response

    monkeypatch.setattr("asr_eval.providers.requests.post", post)
    with pytest.raises(requests.HTTPError):
        transcribe(snapshot, path, "auto")
