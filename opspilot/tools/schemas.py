from datetime import datetime

from pydantic import BaseModel, Field


class TimeRangeQuery(BaseModel):
    service: str = Field(min_length=1, max_length=64)
    scenario_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")
    start: datetime
    end: datetime


class MetricsQuery(TimeRangeQuery):
    metric: str = Field(min_length=1, max_length=64)


class LogsQuery(TimeRangeQuery):
    keywords: list[str] = Field(default_factory=list, max_length=10)
    level: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class ServiceInfoQuery(BaseModel):
    service: str = Field(min_length=1, max_length=64)
    scenario_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")


class SearchQuery(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    service: str = Field(min_length=1, max_length=64)
    scenario_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")
    top_k: int = Field(default=3, ge=1, le=10)


class RestartServiceQuery(BaseModel):
    service: str = Field(min_length=1, max_length=64)
    instance_ids: list[str] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=5, max_length=500)


class RollbackDeploymentQuery(BaseModel):
    service: str = Field(min_length=1, max_length=64)
    target_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    reason: str = Field(min_length=5, max_length=500)
