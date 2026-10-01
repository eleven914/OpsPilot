from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"


PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.VIEWER: frozenset({"incident:read", "approval:read"}),
    Role.OPERATOR: frozenset(
        {"incident:read", "incident:create", "approval:read"}
    ),
    Role.APPROVER: frozenset(
        {"incident:read", "approval:read", "approval:decide"}
    ),
    Role.ADMIN: frozenset(
        {
            "incident:read",
            "incident:create",
            "approval:read",
            "approval:decide",
            "settings:manage",
        }
    ),
}


def has_permission(role: Role, permission: str) -> bool:
    return permission in PERMISSIONS[role]
