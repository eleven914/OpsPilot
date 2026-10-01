from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from opspilot.security.rbac import Role, has_permission


@dataclass(frozen=True, slots=True)
class Identity:
    user_id: str
    role: Role


async def current_identity(
    user_id: Annotated[str, Header(alias="X-User-Id")] = "demo-operator",
    role_name: Annotated[str, Header(alias="X-Role")] = "operator",
) -> Identity:
    try:
        role = Role(role_name)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid role") from exc
    return Identity(user_id=user_id, role=role)


def require_permission(permission: str) -> Callable[[Identity], Awaitable[Identity]]:
    async def dependency(
        identity: Annotated[Identity, Depends(current_identity)],
    ) -> Identity:
        if not has_permission(identity.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )
        return identity

    return dependency
