"""OpenAI-compatible chat completions over httpx. One POST — no vendor SDK."""

import logging

import httpx

from app.config import settings
from app.envelope import AppError

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(
    base_url=settings.llm_base_url,
    timeout=httpx.Timeout(settings.llm_timeout_s, connect=10.0),
)


async def aclose() -> None:
    await _client.aclose()


async def complete(
    model: str, messages: list[dict[str, str]], **options: object
) -> dict:
    if not settings.llm_api_key:
        raise AppError(
            "llm_provider_unconfigured", "LLM provider is not configured.", 503
        )

    try:
        response = await _client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={"model": model, "messages": messages, **options},
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "llm provider returned %s: %s", exc.response.status_code, exc.response.text
        )
        raise AppError(
            "llm_provider_error", "The model provider rejected the request.", 502
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("llm provider unreachable: %s", exc)
        raise AppError(
            "llm_provider_unavailable", "The model provider is unreachable.", 502
        ) from exc
