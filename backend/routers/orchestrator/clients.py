import anthropic
import httpx

from routers.models.local.environment import LOCAL_CONTEXT_LENGTH, LOCAL_TIMEOUT
from routers.models.providers import is_local

from .memory.short_term.render import as_anthropic, as_gemini, as_openai
from .ratelimit import (
    MAX_RATE_LIMIT_RETRIES,
    can_retry_rate_limit,
    is_rate_limited,
    mark_call_end,
    retry_delay,
    space_calls,
    wait_before_retry,
)

TIMEOUT = 60.0


class ProviderCallError(Exception):
    """Raised when a provider's completion call fails (auth, network, or unexpected shape)."""

    def __init__(self, message, rate_limited=False):
        super().__init__(message)
        self.rate_limited = rate_limited


async def _call_anthropic(api_key, model_id, system_prompt, message, history=None):
    client = anthropic.AsyncAnthropic(api_key=api_key)
    messages = as_anthropic(history) + [{"role": "user", "content": message}]

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        await space_calls()
        try:
            response = await client.messages.create(
                model=model_id,
                max_tokens=16000,
                system=system_prompt,
                messages=messages,
            )
        except anthropic.RateLimitError as e:
            headers = getattr(getattr(e, "response", None), "headers", None)
            if not can_retry_rate_limit(attempt, headers, str(e)):
                raise ProviderCallError(str(e), rate_limited=True) from e
            await wait_before_retry(retry_delay(headers, str(e), attempt), attempt)
            continue
        except anthropic.APIError as e:
            raise ProviderCallError(str(e)) from e

        mark_call_end()
        for block in response.content:
            if block.type == "text":
                return block.text
        raise ProviderCallError("anthropic response had no text block")


async def _call_openai_compatible(base_url, api_key, model_id, system_prompt, message, history=None):
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            *as_openai(history),
            {"role": "user", "content": message},
        ],
    }

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        await space_calls()
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(
                    base_url, headers={"Authorization": f"Bearer {api_key}"}, json=payload
                )
            mark_call_end()

            if is_rate_limited(response.status_code) and can_retry_rate_limit(
                attempt, response.headers, response.text
            ):
                await wait_before_retry(
                    retry_delay(response.headers, response.text, attempt), attempt
                )
                continue

            if is_rate_limited(response.status_code):
                raise ProviderCallError(f"429: {response.text[:300]}", rate_limited=True)

            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise ProviderCallError(str(e)) from e


async def _call_openai(api_key, model_id, system_prompt, message, history=None):
    return await _call_openai_compatible(
        "https://api.openai.com/v1/chat/completions", api_key, model_id, system_prompt, message,
        history=history,
    )


async def _call_groq(api_key, model_id, system_prompt, message, history=None):
    return await _call_openai_compatible(
        "https://api.groq.com/openai/v1/chat/completions", api_key, model_id, system_prompt, message,
        history=history,
    )


async def _call_gemini(api_key, model_id, system_prompt, message, history=None):
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [*as_gemini(history), {"role": "user", "parts": [{"text": message}]}],
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        await space_calls()
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(url, params={"key": api_key}, json=payload)
            mark_call_end()

            if is_rate_limited(response.status_code) and can_retry_rate_limit(
                attempt, response.headers, response.text
            ):
                await wait_before_retry(
                    retry_delay(response.headers, response.text, attempt), attempt
                )
                continue

            if is_rate_limited(response.status_code):
                raise ProviderCallError(f"429: {response.text[:300]}", rate_limited=True)

            response.raise_for_status()
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise ProviderCallError(str(e)) from e


async def _call_ollama(base_url, model_id, system_prompt, message, history=None):
    """Ollama's native /api/chat, not its OpenAI-compatible /v1/chat/completions - that compat layer
    silently drops tool calls when streaming, so the agents rely on this same native endpoint for
    their tool loops (see agents/shared.py:ollama_round). This non-streaming call is only for
    classification and session-title generation, neither of which uses tools, but it stays on the
    same endpoint as a matter of consistency."""
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            *as_openai(history),
            {"role": "user", "content": message},
        ],
        "stream": False,
        "keep_alive": "10m",
        "options": {"num_ctx": LOCAL_CONTEXT_LENGTH},
    }
    try:
        async with httpx.AsyncClient(timeout=LOCAL_TIMEOUT) as client:
            response = await client.post(f"{base_url}/api/chat", json=payload)
        response.raise_for_status()
        return response.json()["message"]["content"]
    except (httpx.HTTPError, KeyError) as e:
        raise ProviderCallError(str(e)) from e


_CLIENTS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "gemini": _call_gemini,
    "groq": _call_groq,
}


async def call_provider(provider, api_key, model_id, system_prompt, message, base_url=None, history=None):
    """`history` is the session's memory window in its neutral form; each client renders it into its
    own dialect. Left out (or empty) the payload is byte-for-byte what it was before memory existed,
    which is what keeps the session-title call - a call with nothing to remember - unchanged."""
    # Local providers have no quota to respect and no key to send - they skip the cloud dispatch table
    # entirely rather than being shoehorned into the (api_key, model_id, ...) signature it expects.
    if is_local(provider):
        if provider == "ollama":
            return await _call_ollama(base_url, model_id, system_prompt, message, history=history)
        raise ProviderCallError(f"unknown local provider: {provider}")

    client = _CLIENTS.get(provider)
    if client is None:
        raise ProviderCallError(f"unknown provider: {provider}")
    return await client(api_key, model_id, system_prompt, message, history=history)
