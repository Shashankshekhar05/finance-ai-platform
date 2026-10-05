"""Groq HTTP client tests: real client code, mocked transport, no network."""

import httpx
import pytest

from app.services.groq_client import (
    GroqAuthError,
    GroqBadRequestError,
    GroqMalformedError,
    GroqModelError,
    GroqNetworkError,
    GroqRateLimitError,
    GroqServerError,
    GroqTimeoutError,
    HttpGroqClient,
)

CALL = dict(
    messages=[{"role": "user", "content": "hi"}],
    model="llama-3.3-70b-versatile",
    temperature=0.0,
    max_tokens=64,
    timeout_s=5.0,
)


def _client() -> HttpGroqClient:
    client = HttpGroqClient.__new__(HttpGroqClient)
    client._api_key = "sk-test"
    client._url = "https://unit.test/chat/completions"
    return client


def _run(handler):
    import app.services.groq_client as module

    real = module._shared_http
    module._shared_http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        return _client().complete(**CALL)
    finally:
        module._shared_http = real


def _ok(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Bearer sk-test"
    assert request.url.path == "/chat/completions"
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "Grounded. [DOC-1]"}}],
            "usage": {"total_tokens": 9},
        },
    )


def test_valid_answer() -> None:
    response = _run(_ok)
    assert response.text == "Grounded. [DOC-1]"
    assert response.model == "llama-3.3-70b-versatile"
    assert response.usage == {"total_tokens": 9}


def test_empty_answer_rejected() -> None:
    with pytest.raises(GroqMalformedError):
        _run(
            lambda request: httpx.Response(
                200, json={"choices": [{"message": {"content": "   "}}]}
            )
        )


def test_malformed_response_rejected() -> None:
    with pytest.raises(GroqMalformedError):
        _run(lambda request: httpx.Response(200, json={"nope": []}))


def test_timeout_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    with pytest.raises(GroqTimeoutError):
        _run(handler)


def test_auth_error_mapped() -> None:
    with pytest.raises(GroqAuthError):
        _run(lambda request: httpx.Response(401, json={"error": "bad key"}))


def test_rate_limit_mapped() -> None:
    with pytest.raises(GroqRateLimitError):
        _run(lambda request: httpx.Response(429, json={"error": "slow down"}))


def test_model_unavailable_mapped() -> None:
    with pytest.raises(GroqModelError):
        _run(lambda request: httpx.Response(404, json={"error": "no such model"}))


def test_network_failure_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns", request=request)

    with pytest.raises(GroqNetworkError):
        _run(handler)


def test_server_error_mapped() -> None:
    with pytest.raises(GroqServerError):
        _run(lambda request: httpx.Response(500, json={"error": "boom"}))


def test_bad_request_mapped() -> None:
    with pytest.raises(GroqBadRequestError):
        _run(lambda request: httpx.Response(400, json={"error": "bad input"}))
