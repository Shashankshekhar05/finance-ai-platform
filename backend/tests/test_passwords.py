"""Password hashing: pure unit tests, no database."""

import pytest

from app.core.security import hash_password, verify_password


def test_hash_then_verify_correct_password() -> None:
    hashed = hash_password("CorrectHorse123")
    assert hashed != "CorrectHorse123"
    assert verify_password("CorrectHorse123", hashed) is True


def test_incorrect_password_rejected() -> None:
    hashed = hash_password("CorrectHorse123")
    assert verify_password("WrongPassword999", hashed) is False
    assert verify_password("", hashed) is False


def test_same_password_produces_different_hashes() -> None:
    assert hash_password("SamePassword123") != hash_password("SamePassword123")


def test_hash_format_is_bcrypt() -> None:
    assert hash_password("AnotherPass456").startswith("$2")


def test_malformed_hash_never_verifies_and_never_raises() -> None:
    assert verify_password("anything", "not-a-valid-hash") is False


def test_overlong_password_rejected_not_truncated() -> None:
    with pytest.raises(ValueError):
        hash_password("x" * 73)
