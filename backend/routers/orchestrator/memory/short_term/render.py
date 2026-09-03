"""Renders a neutral memory window into each provider's own conversation format.

Pure formatting of data that already crossed the wire, so importing these at a call site crosses no
boundary - the same way xml_output.parse_response is imported to shape a provider's reply. The
window itself is always fetched over the memory route (client.py), never by importing memory.py.

Every function takes the neutral turns and returns something that can be spliced straight into the
payload a provider call was going to send anyway, so the four call sites stay one line each.
"""
from .memory import MAX_CLASSIFIER_CHARS, truncate

# Only the classifier's preamble needs these; the message-array renderings carry the role in the
# payload itself.
_SPEAKERS = {"user": "User", "assistant": "Opsy"}


def _messages(turns):
    """(role, content) for each turn, accepting both the dicts that come back over the wire and the
    HistoryTurn models an agent's request model parses them into."""
    for turn in turns or []:
        if isinstance(turn, dict):
            role, content = turn.get("role"), turn.get("content")
        else:
            role, content = getattr(turn, "role", None), getattr(turn, "content", None)
        if role in ("user", "assistant") and (content or "").strip():
            yield role, content.strip()


def as_anthropic(turns):
    """Anthropic's messages array. The system prompt is passed separately there, so this is spliced
    in ahead of the current user turn with nothing before it."""
    return [{"role": role, "content": content} for role, content in _messages(turns)]


def as_openai(turns):
    """OpenAI-compatible (openai, groq) and Ollama both take this shape - spliced between the system
    message and the current user turn.

    Ollama needs no renderer of its own: its native /api/chat accepts the same {"role", "content"}
    messages, and only its *response* framing differs, which is what shared.ollama_round exists to
    parse."""
    return [{"role": role, "content": content} for role, content in _messages(turns)]


def as_gemini(turns):
    """Gemini's contents array, which calls the assistant role "model" and wraps text in parts. This
    rename lives here rather than in the stored window so nothing upstream has to know which provider
    a window is destined for."""
    return [
        {"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]}
        for role, content in _messages(turns)
    ]


def as_classifier_context(turns):
    """The window folded into a preamble on the classifier's single user message.

    The classifier is deliberately not given a real multi-turn array. Its whole contract is to answer
    with one word, and prior turns presented as actual assistant messages are a standing invitation
    for a weaker model to continue the conversation instead of classifying it. Inline context reads as
    part of one instruction, so the reply stays a single word - while still letting "and what about
    /var?" be recognised as a disk question.

    Returns "" when there is nothing to add, so the caller sends today's exact message unchanged.
    """
    lines = [
        f"{_SPEAKERS[role]}: {truncate(content, MAX_CLASSIFIER_CHARS)[0]}"
        for role, content in _messages(turns)
    ]
    if not lines:
        return ""

    transcript = "\n".join(lines)
    return f"Earlier in this conversation:\n{transcript}\n\nClassify this new message:\n"
