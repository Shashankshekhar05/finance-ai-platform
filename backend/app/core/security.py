"""Password hashing: bcrypt only. No custom crypto, ever.

- `hash_password` returns the hash string for storage.
- `verify_password` uses constant-time comparison internally (bcrypt.checkpw).
- Plaintext passwords are never logged, returned, or persisted here.
- 72-byte bcrypt limit is enforced at the schema layer (auth.RegisterRequest),
  so this module can assert rather than silently truncate.
"""

import bcrypt


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("Password exceeds bcrypt's 72-byte limit.")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash or input: reject, never raise internals outward.
        return False
