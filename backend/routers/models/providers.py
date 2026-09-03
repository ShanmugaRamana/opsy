# Provider identity shared across BYOK, the model catalog, and the orchestrator. Cloud providers are
# authenticated with a stored BYOK key; local providers run on this machine and need no key at all -
# `is_local` is the one place that distinction is decided, so callers don't each re-derive it.

CLOUD_PROVIDERS = ("anthropic", "openai", "gemini", "groq")
LOCAL_PROVIDERS = ("ollama",)
ALL_PROVIDERS = CLOUD_PROVIDERS + LOCAL_PROVIDERS


def is_local(provider):
    return provider in LOCAL_PROVIDERS
