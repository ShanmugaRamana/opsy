import json
import logging
import re
import xml.etree.ElementTree as ET

from . import xml_common

logger = logging.getLogger("orchestrator")

NO_ANSWER_CONTENT = "The model finished without returning a readable answer. Try asking again."

# Marks a stored chat row as a turn this module synthesized rather than one the model wrote: the
# three report modes always, "multi" always (a turn several agents answered), and "general" only when
# the base agent ran commands worth keeping (see to_storage_xml). A plain general answer is still
# stored as the model's own unmarked <response>, which is what parse_response already handles - and
# every row written before this attribute existed reads back through that same path unchanged.
#
# This alternation has to list every mode that can be written with one. A mode missing from it does
# not raise: the stored turn silently falls through to parse_response, replays as "general", and its
# report is dropped from the transcript, so the live turn looks perfect and only a reload shows the
# damage.
_AGENT_MODE_RE = re.compile(r'<response\b[^>]*\bmode="(disk|process|network|general|multi)"')


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


def _load_json(element, default):
    """JSON carried inside an element, or `default`. A row whose JSON no longer parses replays
    without that piece rather than taking the whole transcript down with it."""
    if element is None or not element.text:
        return default
    try:
        return json.loads(element.text)
    except ValueError:
        logger.warning(f"stored chat XML had unreadable JSON in <{element.tag}>")
        return default


def _write_agent(root, slot):
    """One agent's slice of a multi-agent turn, written as an <agent mode="..."> child.

    Each slot is that agent's own final event, so this writes the same three shapes the single-agent
    branches below do - a report, the base agent's prose, or the fact that it failed."""
    mode = slot.get("mode") or "general"
    element = ET.SubElement(root, "agent")
    element.set("mode", mode)

    error = slot.get("error")
    if error:
        # A failed agent is stored, not dropped. The turn's answer covered the parts that worked, and
        # a replay that quietly showed two findings where the live turn showed two findings and a
        # failure would be a different, more confident answer than the user was actually given.
        ET.SubElement(element, "error").text = str(error)
        return

    thinking = slot.get("thinking")
    if thinking:
        ET.SubElement(element, "thinking").text = thinking

    if mode == "general":
        ET.SubElement(element, "content").text = slot.get("content") or ""
    else:
        ET.SubElement(element, "report").text = json.dumps(slot.get(f"{mode}_report") or {})

    ET.SubElement(element, "commands_run").text = json.dumps(slot.get("commands_run") or [])


def _read_agent(element) -> dict:
    """The inverse of _write_agent: one <agent> element back into the slot shape the live
    `agent_final` event and the composite final's `agents` list both carry."""
    mode = element.get("mode") or "general"

    error = _element_text(element.find("error"))
    if error:
        return {"mode": mode, "error": error}

    slot = {
        "mode": mode,
        "thinking": _element_text(element.find("thinking")),
        "commands_run": _load_json(element.find("commands_run"), []),
    }
    if mode == "general":
        slot["content"] = _element_text(element.find("content")) or ""
    else:
        slot[f"{mode}_report"] = _load_json(element.find("report"), {})
    return slot


def to_storage_xml(final_event: dict) -> str:
    """Serializes a terminal `final` event into the XML stored in the chats table, so a session can
    be replayed later without losing thinking, the structured report, or which commands ran.

    A general-mode turn that ran no commands already is real model-authored XML (`raw_xml`) - stored
    as-is, so the row is the model's own words rather than a round trip through this process. Agent-
    mode turns (disk/process/network) never produce XML on their own, since they answer via tool
    calls rather than a text reply, so one is synthesized here from the same fields the live UI
    already renders, with the structured report and command list carried as JSON text inside their
    own elements. A general turn where the base agent did run commands takes the synthesized path
    too: storing its raw reply would keep the answer and silently lose the record of what was run.

    A "multi" turn - two or three agents on one message - is a container of those same shapes: the
    composed summary, then one <agent> per agent carrying whatever that agent produced. Storing the
    agents individually rather than flattening them into one report is what lets a replay draw the
    same cards, in the same order, that the live turn drew.
    """
    mode = final_event.get("mode", "general")
    if mode == "multi":
        root = ET.Element("response")
        root.set("mode", "multi")
        summary = final_event.get("summary")
        if summary:
            ET.SubElement(root, "summary").text = summary
        for slot in final_event.get("agents") or []:
            _write_agent(root, slot)
        return ET.tostring(root, encoding="unicode")

    if mode == "general":
        commands_run = final_event.get("commands_run") or []
        if not commands_run:
            raw_xml = final_event.get("raw_xml")
            if raw_xml:
                return raw_xml

        root = ET.Element("response")
        if commands_run:
            root.set("mode", "general")
        thinking = final_event.get("thinking")
        if thinking:
            ET.SubElement(root, "thinking").text = thinking
        ET.SubElement(root, "content").text = final_event.get("content") or ""
        if commands_run:
            ET.SubElement(root, "commands_run").text = json.dumps(commands_run)
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
        if mode == "multi":
            logger.warning(f"stored multi chat XML was malformed ({e}); replaying with no agents")
            return {"mode": "multi", "thinking": None, "summary": None, "agents": [], "commands_run": []}
        if mode == "general":
            # Falling back to the tolerant reader rather than an empty report: a general turn's value
            # is its prose, and parse_response salvages that out of markup this parser rejected.
            logger.warning(f"stored general chat XML was malformed ({e}); salvaging its text")
            thinking, content = parse_response(chat_text)
            return {"mode": "general", "thinking": thinking, "content": content, "commands_run": []}
        logger.warning(f"stored {mode} chat XML was malformed ({e}); replaying with an empty report")
        return {"mode": mode, "thinking": None, f"{mode}_report": {}, "commands_run": []}

    thinking = _element_text(root.find("thinking"))

    if mode == "multi":
        agents = [_read_agent(element) for element in root.findall("agent")]
        return {
            "mode": "multi",
            "thinking": thinking,
            "summary": _element_text(root.find("summary")),
            "agents": agents,
            # Flattened the same way the live event flattens it, so a replayed turn and a live one
            # answer "what did this turn run" identically.
            "commands_run": [
                command for slot in agents for command in (slot.get("commands_run") or [])
            ],
        }

    if mode == "general":
        commands_el = root.find("commands_run")
        return {
            "mode": "general",
            "thinking": thinking,
            "content": _element_text(root.find("content")) or "",
            "commands_run": json.loads(commands_el.text) if commands_el is not None and commands_el.text else [],
        }

    report_el = root.find("report")
    report = json.loads(report_el.text) if report_el is not None and report_el.text else {}

    commands_el = root.find("commands_run")
    commands_run = json.loads(commands_el.text) if commands_el is not None and commands_el.text else []

    return {"mode": mode, "thinking": thinking, f"{mode}_report": report, "commands_run": commands_run}
