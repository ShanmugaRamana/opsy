import logging

import httpx

logger = logging.getLogger("byok")

TIMEOUT = 10.0


def _check_anthropic(api_key):
    return httpx.get(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        timeout=TIMEOUT,
    )


def _check_openai(api_key):
    return httpx.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=TIMEOUT,
    )


def _check_gemini(api_key):
    return httpx.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        params={"key": api_key},
        timeout=TIMEOUT,
    )


def _check_openrouter(api_key):
    return httpx.get(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=TIMEOUT,
    )


def _check_groq(api_key):
    return httpx.get(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=TIMEOUT,
    )


_CHECKS = {
    "anthropic": _check_anthropic,
    "openai": _check_openai,
    "gemini": _check_gemini,
    "openrouter": _check_openrouter,
    "groq": _check_groq,
}


def verify_key(provider, api_key):
    """Returns 'valid', 'invalid', or 'unreachable'. Never logs the key itself."""
    check = _CHECKS.get(provider)
    if check is None:
        return "invalid"

    try:
        response = check(api_key)
    except httpx.RequestError as e:
        logger.error(f"{provider} unreachable: {e}")
        return "unreachable"

    if response.status_code == 200:
        logger.info(f"{provider} key verification: valid")
        return "valid"
    elif response.status_code in (401, 403):
        logger.warning(f"{provider} key verification: rejected ({response.status_code})")
        return "invalid"
    else:
        logger.error(f"{provider} unreachable: unexpected status {response.status_code}")
        return "unreachable"
