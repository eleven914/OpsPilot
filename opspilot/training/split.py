from collections.abc import Iterable

from opspilot.training.schemas import DatasetSplit

DEFAULT_SERVICE_SPLITS: dict[str, DatasetSplit] = {
    "gateway": "train",
    "order": "train",
    "payment": "train",
    "notification": "validation",
    "inventory": "test",
}


def build_service_split(services: Iterable[str]) -> dict[str, DatasetSplit]:
    unique = set(services)
    unknown = unique - DEFAULT_SERVICE_SPLITS.keys()
    if unknown:
        raise ValueError(f"Services are missing an isolated split: {sorted(unknown)}")
    return {service: DEFAULT_SERVICE_SPLITS[service] for service in sorted(unique)}
