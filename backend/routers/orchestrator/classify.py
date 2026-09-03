import logging
import re

from prompts import load_prompt

from .clients import call_provider
from .memory.short_term.render import as_classifier_context

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


async def classify_intent(provider, api_key, model_id, message, base_url=None, history=None) -> str:
    """`history` is folded into the single user message rather than sent as prior turns.

    A follow-up like "and what about /var?" names nothing classifiable on its own and would fall
    through to "general", which is the most visible symptom of a classifier with no memory. But the
    fix cannot be a real multi-turn array: this call's entire contract is a one-word reply, and prior
    turns presented as actual assistant messages invite a weaker model to answer the conversation
    instead of classifying it. Inline context reads as part of the one instruction it was given.

    With no history the message is sent exactly as it was before this existed."""
    if history:
        message = as_classifier_context(history) + message

    raw = await call_provider(provider, api_key, model_id, CLASSIFY_SYSTEM_PROMPT, message, base_url=base_url)
    mode = _match(raw or "")
    if mode == GENERAL and (raw or "").strip().lower() not in ("general", ""):
        # Worth seeing in the log: a reply that matched nothing means the classifier prompt and the
        # registered agents have drifted apart, and every such turn silently takes the general path.
        logger.info(f"classifier reply did not name a known mode, using general: {raw!r:.120}")
    return mode
