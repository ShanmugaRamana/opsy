import logging
import re
import xml.etree.ElementTree as ET

from routers.orchestrator.schemas import Capacity, DiskReport, Fact, TopConsumer

logger = logging.getLogger("orchestrator.disk")

_CODE_FENCE_RE = re.compile(r"^```(?:xml)?\s*|\s*```$", re.MULTILINE)
_VALID_SEVERITIES = {"plenty", "moderate", "tight", "critical"}

# Smaller models often wrap the report in prose ("Here is what I found: <disk_report>...") despite
# being told not to, so the block is extracted from wherever it appears rather than requiring the
# whole reply to be XML.
_REPORT_RE = re.compile(r"<disk_report\b.*?</disk_report>", re.DOTALL | re.IGNORECASE)
_REPORT_OPEN_RE = re.compile(r"<disk_report\b.*", re.DOTALL | re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<[^>]*>")
# A bare "&" is not valid XML and is common in command output quoted back by the model.
_BARE_AMP_RE = re.compile(r"&(?!#?\w+;)")

NO_ANSWER_SUMMARY = "The model finished without returning a readable answer. Expanding the trace shows what was checked."


def _extract_report(text):
    """Pulls the <disk_report> block out of a reply, tolerating surrounding prose and a missing
    closing tag (which happens when the model is cut off mid-answer)."""
    match = _REPORT_RE.search(text)
    if match:
        return match.group(0)

    match = _REPORT_OPEN_RE.search(text)
    if match:
        return f"{match.group(0).rstrip()}</disk_report>"

    return None


def _fallback(raw_text):
    """No parseable report: salvage whatever prose the model did produce rather than showing the
    user an empty answer or a wall of half-XML."""
    prose = _REPORT_OPEN_RE.sub("", raw_text)
    prose = _ANY_TAG_RE.sub("", prose).strip()
    return DiskReport(summary=prose or NO_ANSWER_SUMMARY)


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


def _parse_capacity(root):
    node = root.find("capacity")
    if node is None:
        return None

    severity = (_text(node.find("severity")) or "").lower() or None
    if severity not in _VALID_SEVERITIES:
        severity = None

    capacity = Capacity(
        free_gb=_parse_float(node.findtext("free_gb")),
        total_gb=_parse_float(node.findtext("total_gb")),
        percent_used=_parse_float(node.findtext("percent_used")),
        severity=severity,
    )

    # An empty <capacity/> block carries nothing worth rendering.
    if capacity.model_dump(exclude_none=True):
        return capacity
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


def _parse_top_consumers(root):
    node = root.find("top_consumers")
    if node is None:
        return []

    consumers = []
    for item in node.findall("item"):
        label = (item.get("label") or "").strip()
        if label:
            consumers.append(TopConsumer(label=label, size_gb=_parse_float(item.get("size_gb"))))
    return consumers


def parse_disk_report(raw_text: str) -> DiskReport:
    """Parses the disk agent's <disk_report> reply. Falls back to a bare summary if the model didn't
    comply with the schema, rather than raising."""
    cleaned = _CODE_FENCE_RE.sub("", raw_text or "").strip()

    block = _extract_report(cleaned)
    if block is None:
        logger.warning("disk agent reply contained no <disk_report> block, salvaging prose")
        return _fallback(cleaned)

    try:
        root = ET.fromstring(_BARE_AMP_RE.sub("&amp;", block))
    except ET.ParseError as e:
        logger.warning(f"disk agent <disk_report> block was malformed ({e}), salvaging prose")
        return _fallback(cleaned)

    # An answer with no summary but real content elsewhere is still worth showing.
    summary = _text(root.find("summary")) or _text(root.find("explanation"))
    if summary is None:
        logger.warning("disk agent reply had no <summary>, salvaging prose")
        return _fallback(cleaned)

    return DiskReport(
        summary=summary,
        explanation=_text(root.find("explanation")),
        capacity=_parse_capacity(root),
        facts=_parse_facts(root),
        top_consumers=_parse_top_consumers(root),
        suggestion=_text(root.find("suggestion")),
    )
