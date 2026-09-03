import logging
import re
import xml.etree.ElementTree as ET

from routers.orchestrator.schemas import Capacity, DiskReport, Fact, TopConsumer

logger = logging.getLogger("orchestrator.disk")

_CODE_FENCE_RE = re.compile(r"^```(?:xml)?\s*|\s*```$", re.MULTILINE)
_VALID_SEVERITIES = {"plenty", "moderate", "tight", "critical"}


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
    cleaned = _CODE_FENCE_RE.sub("", raw_text).strip()

    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError:
        logger.warning("disk agent reply was not well-formed XML, falling back to raw text")
        return DiskReport(summary=raw_text.strip())

    summary = _text(root.find("summary"))
    if summary is None:
        logger.warning("disk agent reply had no <summary>, falling back to raw text")
        return DiskReport(summary=raw_text.strip())

    return DiskReport(
        summary=summary,
        explanation=_text(root.find("explanation")),
        capacity=_parse_capacity(root),
        facts=_parse_facts(root),
        top_consumers=_parse_top_consumers(root),
        suggestion=_text(root.find("suggestion")),
    )
