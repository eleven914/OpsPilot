from collections.abc import Sequence
from time import perf_counter
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from opspilot.model_gateway.schemas import ChatMessage, ModelResponse, ModelUsage
from opspilot.observability.metrics import (
    MODEL_DURATION,
    MODEL_REQUESTS,
    MODEL_TOKENS,
)


class ModelGatewayError(RuntimeError):
    """Base error for model transport and response failures."""


class ModelGatewayTimeoutError(ModelGatewayError):
    """The model did not respond before the configured deadline."""


class ModelGatewayUpstreamError(ModelGatewayError):
    """The OpenAI-compatible server returned an unsuccessful status."""


class ModelGatewayResponseError(ModelGatewayError):
    """The server response did not contain a valid assistant message."""


class DecisionClient(Protocol):
    model_name: str

    async def complete(self, messages: Sequence[ChatMessage]) -> ModelResponse: ...


class _ResponseMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str = Field(min_length=1)


class _Choice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: _ResponseMessage


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)


class _CompletionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str | None = None
    choices: list[_Choice] = Field(min_length=1)
    usage: _Usage = Field(default_factory=_Usage)


class OpenAICompatibleClient:
    """Minimal async client for a vLLM/OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout_seconds: float,
        max_tokens: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model_name = model_name
        self._max_tokens = max_tokens
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    async def __aenter__(self) -> "OpenAICompatibleClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(self, messages: Sequence[ChatMessage]) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [message.model_dump(mode="json") for message in messages],
            "temperature": 0.0,
            "max_tokens": self._max_tokens,
            "stream": False,
        }
        started = perf_counter()
        outcome = "error"
        try:
            try:
                response = await self._client.post("chat/completions", json=payload)
                response.raise_for_status()
            except httpx.TimeoutException as error:
                outcome = "timeout"
                raise ModelGatewayTimeoutError("Model request timed out") from error
            except httpx.HTTPStatusError as error:
                outcome = f"http_{error.response.status_code}"
                raise ModelGatewayUpstreamError(
                    f"Model server returned HTTP {error.response.status_code}"
                ) from error
            except httpx.RequestError as error:
                outcome = "transport_error"
                raise ModelGatewayUpstreamError("Model server request failed") from error

            latency_ms = max(0, round((perf_counter() - started) * 1000))
            try:
                completion = _CompletionResponse.model_validate(response.json())
            except (ValueError, ValidationError) as error:
                outcome = "invalid_response"
                raise ModelGatewayResponseError("Invalid model server response") from error
            choice = completion.choices[0]
            outcome = "success"
            MODEL_TOKENS.labels(self.model_name, "input").inc(
                completion.usage.prompt_tokens
            )
            MODEL_TOKENS.labels(self.model_name, "output").inc(
                completion.usage.completion_tokens
            )
            return ModelResponse(
                content=choice.message.content,
                model=completion.model or self.model_name,
                usage=ModelUsage(
                    input_tokens=completion.usage.prompt_tokens,
                    output_tokens=completion.usage.completion_tokens,
                ),
                latency_ms=latency_ms,
            )
        finally:
            MODEL_REQUESTS.labels(self.model_name, outcome).inc()
            MODEL_DURATION.labels(self.model_name).observe(perf_counter() - started)
