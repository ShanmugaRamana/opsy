import logging
import re
import xml.etree.ElementTree as ET

logger = logging.getLogger("orchestrator")

_CODE_FENCE_RE = re.compile(r"^```(?:xml)?\s*|\s*```$", re.MULTILINE)


def parse_response(raw_text: str) -> tuple[str | None, str]:
    """Parses the model's <response><thinking/><content/></response> reply.

    Returns (thinking, content). If the model didn't comply with the XML shape, falls back to
    (None, raw_text) rather than raising — a base-model compliance miss shouldn't 500 the request.
    """
    cleaned = _CODE_FENCE_RE.sub("", raw_text).strip()

    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError:
        logger.warning("orchestrator reply was not well-formed XML, falling back to raw text")
        return None, raw_text.strip()

    thinking_el = root.find("thinking")
    content_el = root.find("content")

    if content_el is None or content_el.text is None:
        logger.warning("orchestrator reply had no <content>, falling back to raw text")
        return None, raw_text.strip()

    thinking = thinking_el.text.strip() if thinking_el is not None and thinking_el.text else None
    return thinking, content_el.text.strip()
