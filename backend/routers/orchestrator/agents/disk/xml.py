import logging
import re
import xml.etree.ElementTree as ET

from routers.orchestrator.schemas import DiskReport, TopConsumer

logger = logging.getLogger("orchestrator.disk")

_CODE_FENCE_RE = re.compile(r"^```(?:xml)?\s*|\s*```$", re.MULTILINE)
_VALID_SEVERITIES = {"plenty", "moderate", "tight", "critical"}


def _parse_float(text):
    if text is None:
        return None
    try:
        return float(text.strip())
    except ValueError:
        return None


def parse_disk_report(raw_text: str) -> DiskReport:
    """Parses the disk agent's <disk_report> reply. Falls back to a bare summary (everything else
    None/empty) if the model didn't comply with the schema, rather than raising."""
    cleaned = _CODE_FENCE_RE.sub("", raw_text).strip()

    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError:
        logger.warning("disk agent reply was not well-formed XML, falling back to raw text")
        return DiskReport(summary=raw_text.strip())

    summary_el = root.find("summary")
    if summary_el is None or not summary_el.text:
        logger.warning("disk agent reply had no <summary>, falling back to raw text")
        return DiskReport(summary=raw_text.strip())

    severity_el = root.find("severity")
    severity = severity_el.text.strip().lower() if severity_el is not None and severity_el.text else None
    if severity not in _VALID_SEVERITIES:
        severity = None

    top_consumers = []
    top_consumers_el = root.find("top_consumers")
    if top_consumers_el is not None:
        for item in top_consumers_el.findall("item"):
            label = item.get("label")
            if not label:
                continue
            top_consumers.append(TopConsumer(label=label, size_gb=_parse_float(item.get("size_gb"))))

    suggestion_el = root.find("suggestion")
    suggestion = suggestion_el.text.strip() if suggestion_el is not None and suggestion_el.text else None

    return DiskReport(
        summary=summary_el.text.strip(),
        free_gb=_parse_float(root.findtext("free_gb")),
        total_gb=_parse_float(root.findtext("total_gb")),
        percent_used=_parse_float(root.findtext("percent_used")),
        severity=severity,
        top_consumers=top_consumers,
        suggestion=suggestion,
    )
