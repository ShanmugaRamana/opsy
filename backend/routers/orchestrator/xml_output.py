import logging
import xml.etree.ElementTree as ET

from . import xml_common

logger = logging.getLogger("orchestrator")

NO_ANSWER_CONTENT = "The model finished without returning a readable answer. Try asking again."


def _element_text(element):
    """All text under an element, not just the run before its first child - a model that emits
    markup inside <content> would otherwise lose everything after it."""
    if element is None:
        return None
    text = "".join(element.itertext()).strip()
    return text or None


def _salvage(cleaned, reason):
    """No parseable <response>: recover the answer rather than showing the user raw markup.

    Prefers whatever is inside <content>, since a truncated reply usually still has the opening tag,
    and drops <thinking> entirely - the user asked a question, not for the model's notes."""
    logger.warning(f"{reason}; raw reply: {xml_common.excerpt(cleaned)}")

    block = xml_common.extract_block(cleaned, "content")
    if block is not None:
        recovered = xml_common.strip_markup(block)
        if recovered:
            return recovered

    recovered = xml_common.strip_markup(xml_common.drop_block(cleaned, "thinking"))
    return recovered or NO_ANSWER_CONTENT


def parse_response(raw_text: str) -> tuple[str | None, str]:
    """Parses the model's <response><thinking/><content/></response> reply.

    Returns (thinking, content). A model that doesn't comply shouldn't 500 the request, and it
    shouldn't leak tags into the chat either, so a non-compliant reply is salvaged into prose.
    """
    cleaned = xml_common.clean(raw_text)

    block = xml_common.extract_block(cleaned, "response")
    if block is None:
        return None, _salvage(cleaned, "orchestrator reply contained no <response> block")

    try:
        root = ET.fromstring(xml_common.BARE_AMP_RE.sub("&amp;", block))
    except ET.ParseError as e:
        return None, _salvage(cleaned, f"orchestrator <response> block was malformed ({e})")

    content = _element_text(root.find("content"))
    if content is None:
        return None, _salvage(cleaned, "orchestrator reply had no <content>")

    return _element_text(root.find("thinking")), content
