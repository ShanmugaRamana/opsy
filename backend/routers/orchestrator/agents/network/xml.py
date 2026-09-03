import logging
import xml.etree.ElementTree as ET

from routers.orchestrator import xml_common
from routers.orchestrator.schemas import (
    ConnectionEntry,
    ConnectivityLadder,
    Fact,
    ListeningPort,
    NetworkInterface,
    NetworkReport,
)

logger = logging.getLogger("orchestrator.network")

_VALID_SEVERITIES = {"online", "degraded", "offline"}
_VALID_CONFIDENCE = {"full", "degraded"}
_VALID_RUNG_STATES = {"ok", "fail", "unknown"}
_VALID_EXPOSURES = {"local", "all-interfaces", "unknown"}
_VALID_KINDS = {"wifi", "ethernet", "loopback", "tunnel", "bridge", "bond", "virtual", "unknown"}
_VALID_LINK_STATES = {"up", "down", "no-carrier"}

_LADDER_RUNGS = ("link", "address", "gateway", "dns", "internet")

# Listing every interface, connection or port would bury the answer the same way a raw dump does.
MAX_INTERFACES = 12
MAX_CONNECTIONS = 12
MAX_PORTS = 15

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

    Tries the individual prose fields before falling back to loose narration, because a reply
    truncated mid-report usually still carries a complete <summary>, and throwing that away would be
    discarding the actual answer.

    Always flagged as salvaged, because the caller renders a degraded answer differently: whatever is
    recovered here is missing its structured half, so it belongs alongside the trace rather than in
    place of it."""
    logger.warning(f"{reason}; raw reply: {xml_common.excerpt(raw_text)}")

    summary = _recover_field(raw_text, "summary")
    explanation = _recover_field(raw_text, "explanation")
    if summary or explanation:
        return NetworkReport(
            summary=summary or explanation,
            explanation=explanation if summary else None,
            salvaged=True,
        )

    prose = xml_common.strip_markup(xml_common.drop_block(raw_text, "network_report"))
    return NetworkReport(summary=prose or NO_ANSWER_SUMMARY, salvaged=True)


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


def _enum(raw, valid):
    value = (raw or "").strip().lower() or None
    return value if value in valid else None


def _parse_confidence(root):
    return _enum(_text(root.find("confidence")), _VALID_CONFIDENCE)


def _parse_connectivity(root):
    node = root.find("connectivity")
    if node is None:
        return None

    rungs = {rung: _enum(_text(node.find(rung)), _VALID_RUNG_STATES) for rung in _LADDER_RUNGS}
    failed_at = _enum(_text(node.find("failed_at")), set(_LADDER_RUNGS))
    severity = _enum(_text(node.find("severity")), _VALID_SEVERITIES)

    # A layer reported as failed but not named in failed_at still means something failed. Deriving it
    # here keeps the renderer from highlighting nothing on a report that clearly broke somewhere.
    if failed_at is None:
        failed = [rung for rung in _LADDER_RUNGS if rungs[rung] == "fail"]
        failed_at = failed[0] if failed else None

    # The one place this parser overrides the model rather than just validating it, mirroring the
    # degraded-state override in the process agent. A verdict cannot be stronger than the evidence it
    # was built from, and "online" alongside a failed layer is the claim a model most often rounds up
    # to. The user has no way to tell the difference, so it is corrected here.
    if failed_at is not None and severity == "online":
        logger.warning(f"network agent claimed severity 'online' while '{failed_at}' failed")
        severity = "degraded" if failed_at == "dns" else "offline"

    ladder = ConnectivityLadder(**rungs, failed_at=failed_at, severity=severity)

    # An empty <connectivity/> block carries nothing worth rendering.
    if ladder.model_dump(exclude_none=True):
        return ladder
    return None


def _parse_interfaces(root):
    node = root.find("interfaces")
    if node is None:
        return []

    interfaces = []
    for item in node.findall("interface"):
        name = (item.get("name") or "").strip()
        if not name:
            continue
        interfaces.append(
            NetworkInterface(
                name=name,
                kind=_enum(item.get("kind"), _VALID_KINDS),
                state=_enum(item.get("state"), _VALID_LINK_STATES),
                ipv4=(item.get("ipv4") or "").strip() or None,
                ipv6=(item.get("ipv6") or "").strip() or None,
                signal_dbm=_parse_float(item.get("signal_dbm")),
                detail=(item.get("detail") or "").strip() or None,
            )
        )
    return interfaces[:MAX_INTERFACES]


def _parse_connections(root):
    node = root.find("connections")
    if node is None:
        return []

    connections = []
    for item in node.findall("connection"):
        name = (item.get("name") or "").strip()
        if not name:
            continue
        connections.append(
            ConnectionEntry(
                name=name,
                connections=_parse_int(item.get("connections")),
                listening=_parse_int(item.get("listening")),
                detail=(item.get("detail") or "").strip() or None,
            )
        )
    return connections[:MAX_CONNECTIONS]


def _parse_listening(root):
    node = root.find("listening")
    if node is None:
        return []

    ports = []
    for item in node.findall("port"):
        port = _parse_int(item.get("port"))
        process = (item.get("process") or "").strip() or None
        if port is None and process is None:
            continue

        address = (item.get("address") or "").strip() or None
        exposure = _enum(item.get("exposure"), _VALID_EXPOSURES)
        # Exposure is the security-relevant half of the row, so a missing or invalid value is derived
        # from the bind address rather than left blank - "unknown" reads as a caveat the data does
        # not actually have when the address plainly says which it is.
        if exposure is None and address:
            if address in ("0.0.0.0", "::", "[::]", "*"):
                exposure = "all-interfaces"
            elif address.startswith("127.") or address in ("::1", "[::1]"):
                exposure = "local"

        ports.append(
            ListeningPort(
                port=port,
                protocol=_enum(item.get("protocol"), {"tcp", "udp"}),
                address=address,
                process=process,
                exposure=exposure,
            )
        )
    return ports[:MAX_PORTS]


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


def parse_network_report(raw_text: str) -> NetworkReport:
    """Parses the network agent's <network_report> reply. Falls back to a bare summary if the model
    didn't comply with the schema, rather than raising."""
    cleaned = xml_common.clean(raw_text)

    block = xml_common.extract_block(cleaned, "network_report")
    if block is None:
        return _fallback(cleaned, "network agent reply contained no <network_report> block")

    try:
        root = ET.fromstring(xml_common.BARE_AMP_RE.sub("&amp;", block))
    except ET.ParseError as e:
        return _fallback(cleaned, f"network agent <network_report> block was malformed ({e})")

    # An answer with no summary but real content elsewhere is still worth showing.
    summary = _text(root.find("summary")) or _text(root.find("explanation"))
    if summary is None:
        return _fallback(cleaned, "network agent reply had no <summary>")

    return NetworkReport(
        summary=summary,
        explanation=_text(root.find("explanation")),
        confidence=_parse_confidence(root),
        connectivity=_parse_connectivity(root),
        interfaces=_parse_interfaces(root),
        connections=_parse_connections(root),
        listening=_parse_listening(root),
        facts=_parse_facts(root),
        standout=_text(root.find("standout")),
        suggestion=_text(root.find("suggestion")),
    )
