import logging
import re

from prompts import load_prompt

from .clients import call_provider

logger = logging.getLogger("orchestrator")

CLASSIFY_SYSTEM_PROMPT = load_prompt("orchestrator_classify")

# Every specialist agent's mode. "general" is the fallback and is not an agent.
AGENT_MODES = ("disk", "process", "network")
GENERAL = "general"


def _match(text):
    """A whole-word match, checked against a lowercased reply.

    Substring matching was the original approach and could not survive a second agent: "process" is
    a substring of plenty of prose, and a reply like "this is a general question about disk usage"
    would have matched the wrong mode. A bare one-word reply is the common case; a word inside a
    short sentence is the fallback; anything else is general."""
    stripped = text.strip().strip(".\"'`").lower()
    if stripped in AGENT_MODES:
        return stripped
    if stripped == GENERAL:
        return GENERAL

    for mode in AGENT_MODES:
        if re.search(rf"\b{mode}\b", stripped):
            return mode
    return GENERAL


async def classify_intent(provider, api_key, model_id, message) -> str:
    raw = await call_provider(provider, api_key, model_id, CLASSIFY_SYSTEM_PROMPT, message)
    mode = _match(raw or "")
    if mode == GENERAL and (raw or "").strip().lower() not in ("general", ""):
        # Worth seeing in the log: a reply that matched nothing means the classifier prompt and the
        # registered agents have drifted apart, and every such turn silently takes the general path.
        logger.info(f"classifier reply did not name a known mode, using general: {raw!r:.120}")
    return mode
