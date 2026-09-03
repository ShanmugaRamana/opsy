import json
import logging
import re
import xml.etree.ElementTree as ET

from . import xml_common

logger = logging.getLogger("orchestrator")

NO_ANSWER_CONTENT = "The model finished without returning a readable answer. Try asking again."

# Marks a stored chat row as an agent-mode turn (disk/process) - the general path's stored XML is
# the model's own <response> reply, unmarked, same as what parse_response already handles.
_AGENT_MODE_RE = re.compile(r'<response\b[^>]*\bmode="(disk|process)"')


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


def to_storage_xml(final_event: dict) -> str:
    """Serializes a terminal `final` event into the XML stored in the chats table, so a session can
    be replayed later without losing thinking, the structured report, or which commands ran.

    General-mode turns already are real model-authored XML (`raw_xml`) - stored as-is. Agent-mode
    turns (disk/process) never produce XML on their own, since they answer via tool calls rather
    than a text reply, so one is synthesized here from the same fields the live UI already renders,
    with the structured report and command list carried as JSON text inside their own elements.
    """
    mode = final_event.get("mode", "general")
    if mode == "general":
        raw_xml = final_event.get("raw_xml")
        if raw_xml:
            return raw_xml
        root = ET.Element("response")
        thinking = final_event.get("thinking")
        if thinking:
            ET.SubElement(root, "thinking").text = thinking
        ET.SubElement(root, "content").text = final_event.get("content") or ""
        return ET.tostring(root, encoding="unicode")

    root = ET.Element("response")
    root.set("mode", mode)
    thinking = final_event.get("thinking")
    if thinking:
        ET.SubElement(root, "thinking").text = thinking
    ET.SubElement(root, "report").text = json.dumps(final_event.get(f"{mode}_report") or {})
    ET.SubElement(root, "commands_run").text = json.dumps(final_event.get("commands_run") or [])
    return ET.tostring(root, encoding="unicode")


def from_storage_xml(chat_text: str) -> dict:
    """The inverse of to_storage_xml: reconstructs the same shape the live `final` WS event has, so
    a stored turn replays through the exact renderers the frontend already uses for a live one."""
    cleaned = xml_common.clean(chat_text)
    match = _AGENT_MODE_RE.search(cleaned)
    if match is None:
        thinking, content = parse_response(chat_text)
        return {"mode": "general", "thinking": thinking, "content": content}

    mode = match.group(1)
    block = xml_common.extract_block(cleaned, "response") or cleaned
    try:
        root = ET.fromstring(block)
    except ET.ParseError as e:
        logger.warning(f"stored {mode} chat XML was malformed ({e}); replaying with an empty report")
        return {"mode": mode, "thinking": None, f"{mode}_report": {}, "commands_run": []}

    thinking = _element_text(root.find("thinking"))

    report_el = root.find("report")
    report = json.loads(report_el.text) if report_el is not None and report_el.text else {}

    commands_el = root.find("commands_run")
    commands_run = json.loads(commands_el.text) if commands_el is not None and commands_el.text else []

    return {"mode": mode, "thinking": thinking, f"{mode}_report": report, "commands_run": commands_run}
