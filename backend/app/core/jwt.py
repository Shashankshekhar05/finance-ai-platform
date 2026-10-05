"""JWT creation + verification (HS256, PyJWT).

Claims (minimum necessary): sub=user_id, company_id=active tenant,
role=role in that tenant, type="access", iat, exp, jti. No password,
no hash, no personal data beyond what routing/tenancy requires.
Secrets come from Settings only; `decode_and_validate` enforces signature,
expiry, algorithm, and claim presence. Error mapping (401 invalid_token vs
token_expired) happens in the caller via these typed errors.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt

ALGORITHM = "HS256"
TOKEN_TYPE = "access"


class TokenInvalidError(Exception):
    pass


class TokenExpiredError(TokenInvalidError):
    pass


def create_access_token(
    *,
    user_id: str,
    company_id: str,
    role: str,
    secret_key: str,
    expires_minutes: int,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "company_id": company_id,
        "role": role,
        "type": TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def decode_and_validate(token: str, *, secret_key: str) -> dict[str, object]:
    """Return verified claims or raise TokenExpiredError/TokenInvalidError."""
    try:
        claims = jwt.decode(
            token,
            secret_key,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "company_id", "role", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError from exc
    except jwt.PyJWTError as exc:
        raise TokenInvalidError from exc
    if claims.get("type") != TOKEN_TYPE:
        raise TokenInvalidError("unexpected token type")
    return claims
