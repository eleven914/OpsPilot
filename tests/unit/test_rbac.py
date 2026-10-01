import pytest

from opspilot.security.rbac import Role, has_permission


@pytest.mark.parametrize("role", [Role.APPROVER, Role.ADMIN])
def test_only_approval_roles_can_decide(role: Role) -> None:
    assert has_permission(role, "approval:decide")


@pytest.mark.parametrize("role", [Role.VIEWER, Role.OPERATOR])
def test_non_approval_roles_cannot_decide(role: Role) -> None:
    assert not has_permission(role, "approval:decide")


def test_viewer_cannot_create_incident() -> None:
    assert not has_permission(Role.VIEWER, "incident:create")
