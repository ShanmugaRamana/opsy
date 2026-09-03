import logging
import xml.etree.ElementTree as ET

from routers.orchestrator import xml_common
from routers.orchestrator.schemas import AppEntry, Fact, LoadSummary, ProcessEntry, ProcessReport

logger = logging.getLogger("orchestrator.process")

_VALID_SEVERITIES = {"idle", "normal", "busy", "overloaded"}
_VALID_CONFIDENCE = {"full", "degraded"}
_VALID_STATES = {"foreground", "background", "unknown"}

# Listing every process would bury the answer the same way a raw ps dump does.
MAX_PROCESSES = 12

NO_ANSWER_SUMMARY = "The model finished without returning a readable answer. Expanding the trace shows what was checked."


def _recover_field(text, tag):
    """One field pulled straight out of an unparseable reply. extract_block tolerates a missing
    closing tag, so this still works on a reply that was cut off mid-report."""
    block = xml_common.extract_block(text, tag)
    if block is None:
        return None
    return xml_common.strip_markup(block) or None


def _fallback(raw_text, reason):
    """No parseable report: recover what the model did produce rather than showing the user an empty
    answer or a wall of half-XML.

    Tries the individual prose fields before falling back to loose narration. A reply truncated
    mid-report usually still carries a complete <summary>, and throwing that away to show "the model
    finished without returning a readable answer" would be discarding the actual answer.

    Always flagged as salvaged, because the caller renders a degraded answer differently: whatever is
    recovered here is missing its structured half, so it belongs alongside the trace rather than in
    place of it."""
    logger.warning(f"{reason}; raw reply: {xml_common.excerpt(raw_text)}")

    summary = _recover_field(raw_text, "summary")
    explanation = _recover_field(raw_text, "explanation")
    if summary or explanation:
        return ProcessReport(
            summary=summary or explanation,
            explanation=explanation if summary else None,
            salvaged=True,
        )

    prose = xml_common.strip_markup(xml_common.drop_block(raw_text, "process_report"))
    return ProcessReport(summary=prose or NO_ANSWER_SUMMARY, salvaged=True)


def _text(element):
    if element is None or element.text is None:
        return None
    stripped = element.text.strip()
    return stripped or None


def _parse_float(raw):
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        return None


def _parse_int(raw):
    value = _parse_float(raw)
    return int(value) if value is not None else None


def _parse_confidence(root):
    value = (_text(root.find("confidence")) or "").lower() or None
    return value if value in _VALID_CONFIDENCE else None


def _parse_apps(root, confidence):
    node = root.find("apps")
    if node is None:
        return []

    apps = []
    for item in node.findall("app"):
        name = (item.get("name") or "").strip()
        if not name:
            continue

        state = (item.get("state") or "").strip().lower()
        if state not in _VALID_STATES:
            state = None
        # The one place this parser overrides the model rather than just validating it. Window data
        # did not exist for this session, so "foreground" or "background" cannot have been observed -
        # a model that emits one anyway is corrected here rather than passed through to the user, who
        # would have no way to tell the difference.
        if confidence == "degraded" and state in ("foreground", "background"):
            logger.warning(f"process agent claimed state '{state}' for '{name}' on a degraded session")
            state = "unknown"

        apps.append(
            AppEntry(
                name=name,
                cpu_percent=_parse_float(item.get("cpu_percent")),
                memory_mb=_parse_float(item.get("memory_mb")),
                processes=_parse_int(item.get("processes")),
                uptime=(item.get("uptime") or "").strip() or None,
                state=state,
                detail=(item.get("detail") or "").strip() or None,
            )
        )
    return apps


def _parse_processes(root):
    node = root.find("processes")
    if node is None:
        return []

    processes = []
    for item in node.findall("process"):
        name = (item.get("name") or "").strip()
        if not name:
            continue
        processes.append(
            ProcessEntry(
                pid=_parse_int(item.get("pid")),
                name=name,
                cpu_percent=_parse_float(item.get("cpu_percent")),
                memory_mb=_parse_float(item.get("memory_mb")),
                state=(item.get("state") or "").strip() or None,
            )
        )
    return processes[:MAX_PROCESSES]


def _parse_load(root):
    node = root.find("load")
    if node is None:
        return None

    severity = (_text(node.find("severity")) or "").lower() or None
    if severity not in _VALID_SEVERITIES:
        severity = None

    load = LoadSummary(
        cpu_percent=_parse_float(node.findtext("cpu_percent")),
        memory_percent=_parse_float(node.findtext("memory_percent")),
        load_1m=_parse_float(node.findtext("load_1m")),
        cores=_parse_int(node.findtext("cores")),
        severity=severity,
    )

    # An empty <load/> block carries nothing worth rendering.
    if load.model_dump(exclude_none=True):
        return load
    return None


def _parse_facts(root):
    node = root.find("facts")
    if node is None:
        return []

    facts = []
    for item in node.findall("fact"):
        label = (item.get("label") or "").strip()
        value = (item.get("value") or "").strip()
        if label and value:
            facts.append(Fact(label=label, value=value))
    return facts


def parse_process_report(raw_text: str) -> ProcessReport:
    """Parses the process agent's <process_report> reply. Falls back to a bare summary if the model
    didn't comply with the schema, rather than raising."""
    cleaned = xml_common.clean(raw_text)

    block = xml_common.extract_block(cleaned, "process_report")
    if block is None:
        return _fallback(cleaned, "process agent reply contained no <process_report> block")

    try:
        root = ET.fromstring(xml_common.BARE_AMP_RE.sub("&amp;", block))
    except ET.ParseError as e:
        return _fallback(cleaned, f"process agent <process_report> block was malformed ({e})")

    # An answer with no summary but real content elsewhere is still worth showing.
    summary = _text(root.find("summary")) or _text(root.find("explanation"))
    if summary is None:
        return _fallback(cleaned, "process agent reply had no <summary>")

    confidence = _parse_confidence(root)

    return ProcessReport(
        summary=summary,
        explanation=_text(root.find("explanation")),
        confidence=confidence,
        apps=_parse_apps(root, confidence),
        processes=_parse_processes(root),
        load=_parse_load(root),
        facts=_parse_facts(root),
        standout=_text(root.find("standout")),
        suggestion=_text(root.find("suggestion")),
    )
