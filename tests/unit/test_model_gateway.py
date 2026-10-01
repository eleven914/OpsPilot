import httpx
import pytest

from opspilot.model_gateway.client import (
    ModelGatewayResponseError,
    ModelGatewayTimeoutError,
    ModelGatewayUpstreamError,
    OpenAICompatibleClient,
)
from opspilot.model_gateway.schemas import ChatMessage


@pytest.mark.asyncio
async def test_openai_compatible_client_sends_deterministic_chat_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = await request.aread()
        assert request.url == "http://model.test/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer secret"
        assert b'"temperature":0.0' in payload
        assert b'"max_tokens":256' in payload
        return httpx.Response(
            200,
            json={
                "model": "served-adapter",
                "choices": [{"message": {"content": '{"type":"final_answer"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            },
        )

    client = OpenAICompatibleClient(
        base_url="http://model.test/v1",
        api_key="secret",
        model_name="requested-model",
        timeout_seconds=2,
        max_tokens=256,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        response = await client.complete(
            [ChatMessage(role="user", content="diagnose incident")]
        )

    assert response.model == "served-adapter"
    assert response.content == '{"type":"final_answer"}'
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 7


@pytest.mark.asyncio
async def test_openai_compatible_client_maps_timeout_without_leaking_details() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret upstream detail", request=request)

    client = OpenAICompatibleClient(
        base_url="http://model.test/v1",
        api_key="",
        model_name="model",
        timeout_seconds=1,
        max_tokens=128,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        with pytest.raises(ModelGatewayTimeoutError, match="Model request timed out"):
            await client.complete([ChatMessage(role="user", content="hello")])


@pytest.mark.asyncio
async def test_openai_compatible_client_rejects_http_and_shape_errors() -> None:
    responses = iter(
        [
            httpx.Response(503, json={"error": "internal secret"}),
            httpx.Response(200, json={"choices": []}),
        ]
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return next(responses)

    client = OpenAICompatibleClient(
        base_url="http://model.test/v1",
        api_key="",
        model_name="model",
        timeout_seconds=1,
        max_tokens=128,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        with pytest.raises(ModelGatewayUpstreamError, match="HTTP 503"):
            await client.complete([ChatMessage(role="user", content="first")])
        with pytest.raises(ModelGatewayResponseError, match="Invalid model"):
            await client.complete([ChatMessage(role="user", content="second")])
