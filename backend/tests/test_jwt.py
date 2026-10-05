"""JWT create/verify: pure unit tests, no database."""

import time

import pytest

from app.core.jwt import (
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    decode_and_validate,
)

_SECRET = "unit-test-secret-that-is-long-enough-123456"
_OTHER_SECRET = "a-different-secret-that-is-also-long-enough"


def _mint(**overrides) -> str:
    args = {
        "user_id": "11111111-1111-1111-1111-111111111111",
        "company_id": "22222222-2222-2222-2222-222222222222",
        "role": "viewer",
        "secret_key": _SECRET,
        "expires_minutes": 60,
    }
    args.update(overrides)
    return create_access_token(**args)  # type: ignore[arg-type]


def test_valid_token_decodes_with_expected_claims() -> None:
    claims = decode_and_validate(_mint(), secret_key=_SECRET)
    assert claims["sub"] == "11111111-1111-1111-1111-111111111111"
    assert claims["company_id"] == "22222222-2222-2222-2222-222222222222"
    assert claims["role"] == "viewer"
    assert claims["type"] == "access"
    assert "password" not in claims and "password_hash" not in claims


def test_expired_token_rejected() -> None:
    token = _mint(expires_minutes=-1)
    with pytest.raises(TokenExpiredError):
        decode_and_validate(token, secret_key=_SECRET)


def test_wrong_secret_rejected_as_invalid_not_expired() -> None:
    with pytest.raises(TokenInvalidError):
        decode_and_validate(_mint(), secret_key=_OTHER_SECRET)


def test_malformed_token_rejected() -> None:
    for bad in ("", "not.a.token", "eyJhbGciOiJIUzI1NiJ9.e30."):
        with pytest.raises(TokenInvalidError):
            decode_and_validate(bad, secret_key=_SECRET)


def test_tampered_payload_rejected() -> None:
    token = _mint()
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload[:-2]}XX.{signature}"
    with pytest.raises(TokenInvalidError):
        decode_and_validate(tampered, secret_key=_SECRET)


def test_expiry_is_in_the_future_by_default() -> None:
    claims = decode_and_validate(_mint(), secret_key=_SECRET)
    assert float(claims["exp"]) > time.time()
