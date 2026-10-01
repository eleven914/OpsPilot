from typing import Any


class SandboxActionExecutor:
    """Execute only predefined simulated operations; never accepts shell text."""

    _known_instances = {
        "gateway": {"gateway-1", "gateway-2"},
        "order": {"order-1", "order-2"},
        "payment": {"payment-1", "payment-2"},
        "inventory": {"inventory-1"},
        "notification": {"notification-1"},
    }

    def restart_service(
        self, service: str, instance_ids: list[str], reason: str
    ) -> dict[str, Any]:
        known = self._known_instances.get(service)
        if known is None or not set(instance_ids).issubset(known):
            raise ValueError("Service or instance is not present in CMDB")
        return {
            "operation": "restart_service",
            "service": service,
            "instances": instance_ids,
            "status": "succeeded",
            "message": "Sandbox restart completed",
        }

    def rollback_deployment(
        self, service: str, target_version: str, reason: str
    ) -> dict[str, Any]:
        if service not in self._known_instances:
            raise ValueError("Service is not present in CMDB")
        return {
            "operation": "rollback_deployment",
            "service": service,
            "target_version": target_version,
            "status": "succeeded",
            "message": "Sandbox rollback completed",
        }
