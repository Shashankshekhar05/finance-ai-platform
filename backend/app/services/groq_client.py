"""Groq provider boundary: one protocol, one HTTP implementation.

No SDK dependency: plain httpx against Groq's OpenAI-compatible
`/chat/completions` endpoint (fewer moving parts, fully controlled).
The API key travels per-request in the Authorization header and is NEVER
stored on shared objects, logged, or returned. Typed errors let the answer
layer map failures safely (503 vs 502) without leaking provider internals.
"""

from dataclasses import dataclass, field
from typing import Protocol

import httpx


class GroqError(Exception):
    pass


class GroqTimeoutError(GroqError):
    pass


class GroqNetworkError(GroqError):
    pass


class GroqServerError(GroqError):
    pass


class GroqAuthError(GroqError):
    pass


class GroqRateLimitError(GroqError):
    pass


class GroqModelError(GroqError):
    pass


class GroqBadRequestError(GroqError):
    pass


class GroqMalformedError(GroqError):
    pass


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0


class GroqClient(Protocol):
    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
    ) -> LLMResponse: ...


_shared_http = httpx.Client()


class HttpGroqClient:
    """Production implementation. Shared transport, per-call credentials."""

    def __init__(self, *, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
    ) -> LLMResponse:
        import time

        started = time.perf_counter()
        try:
            response = _shared_http.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
                timeout=timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise GroqTimeoutError("provider timed out") from exc
        except httpx.RequestError as exc:
            raise GroqNetworkError("provider unreachable") from exc
        status = response.status_code
        if status == 401:
            raise GroqAuthError("provider rejected credentials")
        if status == 429:
            raise GroqRateLimitError("provider rate limit exceeded")
        if status == 404:
            raise GroqModelError("provider model not found")
        if 500 <= status <= 599:
            raise GroqServerError("provider server error")
        if 400 <= status <= 499:
            raise GroqBadRequestError("provider rejected the request")
        try:
            payload = response.json()
            text = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GroqMalformedError(
                "provider returned an unreadable response"
            ) from exc
        if not isinstance(text, str) or not text.strip():
            raise GroqMalformedError("provider returned an empty answer")
        usage = payload.get("usage") if isinstance(payload, dict) else None
        return LLMResponse(
            text=text,
            model=model,
            usage=dict(usage) if isinstance(usage, dict) else {},
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
