import anthropic
import httpx

TIMEOUT = 60.0


class ProviderCallError(Exception):
    """Raised when a provider's completion call fails (auth, network, or unexpected shape)."""


def _call_anthropic(api_key, model_id, system_prompt, message):
    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=model_id,
            max_tokens=16000,
            system=system_prompt,
            messages=[{"role": "user", "content": message}],
        )
    except anthropic.APIError as e:
        raise ProviderCallError(str(e)) from e

    for block in response.content:
        if block.type == "text":
            return block.text
    raise ProviderCallError("anthropic response had no text block")


def _call_openai_compatible(base_url, api_key, model_id, system_prompt, message):
    try:
        response = httpx.post(
            base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ],
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError) as e:
        raise ProviderCallError(str(e)) from e


def _call_openai(api_key, model_id, system_prompt, message):
    return _call_openai_compatible(
        "https://api.openai.com/v1/chat/completions", api_key, model_id, system_prompt, message
    )


def _call_groq(api_key, model_id, system_prompt, message):
    return _call_openai_compatible(
        "https://api.groq.com/openai/v1/chat/completions", api_key, model_id, system_prompt, message
    )


def _call_gemini(api_key, model_id, system_prompt, message):
    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent",
            params={"key": api_key},
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": message}]}],
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (httpx.HTTPError, KeyError, IndexError) as e:
        raise ProviderCallError(str(e)) from e


_CLIENTS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "gemini": _call_gemini,
    "groq": _call_groq,
}


def call_provider(provider, api_key, model_id, system_prompt, message):
    client = _CLIENTS.get(provider)
    if client is None:
        raise ProviderCallError(f"unknown provider: {provider}")
    return client(api_key, model_id, system_prompt, message)
