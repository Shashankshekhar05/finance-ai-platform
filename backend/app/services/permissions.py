"""Role hierarchy: pure logic, no HTTP, no DB. Directly unit-testable.

Cumulative order: admin > analyst > viewer. `role_satisfies(actual, required)`
is the single check; dependency factories in `app/api/deps.py` are thin
wrappers over it. Capabilities beyond the hierarchy (e.g., which endpoints
need analyst vs admin) are declared per-route, never inferred here.
"""

from app.models.user_role import ROLE_RANK, Role


def role_satisfies(actual: Role | str, required: Role | str) -> bool:
    actual_role = actual if isinstance(actual, Role) else Role(actual)
    required_role = required if isinstance(required, Role) else Role(required)
    return ROLE_RANK[actual_role] >= ROLE_RANK[required_role]
