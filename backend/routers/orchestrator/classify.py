from prompts import load_prompt

from .clients import call_provider

CLASSIFY_SYSTEM_PROMPT = load_prompt("orchestrator_classify")


async def classify_intent(provider, api_key, model_id, message) -> str:
    raw = await call_provider(provider, api_key, model_id, CLASSIFY_SYSTEM_PROMPT, message)
    text = raw.strip().lower()
    return "disk" if "disk" in text else "general"
