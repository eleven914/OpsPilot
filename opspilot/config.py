from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSPILOT_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./opspilot.db"
    redis_url: str = "redis://localhost:6379/0"
    service_name: str = "opspilot-api"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"
    metrics_enabled: bool = True
    metrics_port: int = Field(default=9100, ge=1024, le=65535)
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4318/v1/traces"
    task_mode: Literal["inline", "celery"] = "inline"
    task_soft_time_limit_seconds: int = Field(default=240, ge=30, le=3600)
    task_time_limit_seconds: int = Field(default=300, ge=60, le=3600)
    worker_concurrency: int = Field(default=2, ge=1, le=64)
    broker_visibility_timeout_seconds: int = Field(default=60, ge=10, le=86400)
    chaos_task_delay_seconds: float = Field(default=0.0, ge=0, le=300)
    chaos_ignore_soft_time_limit: bool = False
    model_provider: Literal["mock", "openai_compatible"] = "mock"
    model_base_url: str = "http://model:8000/v1"
    model_api_key: SecretStr = SecretStr("")
    model_name: str = "Qwen/Qwen3-4B-Instruct-2507"
    model_version: str = "opspilot-sft-dpo-v0.2"
    model_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    model_max_tokens: int = Field(default=1024, ge=64, le=8192)
    model_input_cost_per_million_tokens: float = Field(default=0.0, ge=0)
    model_output_cost_per_million_tokens: float = Field(default=0.0, ge=0)
    model_fallback_to_mock: bool = True
    max_model_turns: int = 8
    max_tool_calls: int = 12
    max_run_seconds: int = 180
    alertmanager_webhook_token: str = "change-me"
    approval_ttl_seconds: int = 1800

    @model_validator(mode="after")
    def validate_task_time_limits(self) -> Self:
        if self.task_soft_time_limit_seconds >= self.task_time_limit_seconds:
            raise ValueError("task soft time limit must be lower than hard time limit")
        if self.env == "production" and (
            self.chaos_task_delay_seconds or self.chaos_ignore_soft_time_limit
        ):
            raise ValueError("chaos task controls must be disabled in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
