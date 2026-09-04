"""Writing the one paragraph that sits above several agents' findings.

Two stacked report cards are not an answer to "why is my machine struggling" - the user still has to
join them up. This is the join: one extra provider call that reads the finished reports and says how
they relate.

It composes from reports that have already been produced, so it can only ever be a nice-to-have. The
call is best-effort in the strongest sense: every failure returns None and the turn renders and
stores exactly the reports it already had. That is the same bargain `_generate_title` strikes in
core.py - a side call must never cost the user the turn it was decorating.

No knowledge of HTTP here; the router exposes it, and the orchestrator reaches it over that route.
"""
import json
import logging

from prompts import load_prompt
from routers.orchestrator import xml_common
from routers.orchestrator.clients import call_provider

logger = logging.getLogger("orchestrator.supervisor")

COMPOSE_SYSTEM_PROMPT = load_prompt("orchestrator_compose")

# Per agent block. A full report serialized whole would be most of a local model's context for a
# paragraph that names three figures, so each block carries the prose plus the report's headline rows
# and is then cut.
MAX_REPORT_CHARS = 1500

# The paragraph itself. Anything past this is not the two-to-four sentences that were asked for.
MAX_SUMMARY_CHARS = 1200

# The rows of each report that a combined answer actually turns on. Deliberately not the whole
# report: the per-agent detail is rendered underneath this paragraph, so what is needed here is the
# handful of figures that let one agent's finding be related to another's.
_HEADLINE_KEYS = {
    "disk": ("capacity", "top_consumers", "facts"),
    "process": ("load", "apps", "facts", "standout"),
    "network": ("connectivity", "interfaces", "facts", "standout"),
}


def _report_block(mode, report):
    """One agent's report as the text the composer reads."""
    lines = []
    for key in ("summary", "explanation"):
        text = (report.get(key) or "").strip()
        if text:
            lines.append(text)

    confidence = (report.get("confidence") or "").strip()
    if confidence and confidence != "full":
        # Carried explicitly rather than left in the JSON below, because it changes how every figure
        # in this block may be stated - the prompt asks for the limitation to reach the wording.
        lines.append(f"This check's data was {confidence}, so its findings are not complete.")

    details = {
        key: report[key] for key in _HEADLINE_KEYS.get(mode, ()) if report.get(key)
    }
    if details:
        lines.append(json.dumps(details, default=str))

    suggestion = (report.get("suggestion") or "").strip()
    if suggestion:
        lines.append(f"Suggested: {suggestion}")

    return "\n".join(lines)[:MAX_REPORT_CHARS]


def _slot_block(slot):
    """One agent result -> its block, whatever shape the result took."""
    mode = slot.get("mode") or "general"

    error = (slot.get("error") or "").strip()
    if error:
        return f"[{mode} check] could not complete: {error}"

    if mode == "general":
        body = (slot.get("content") or "").strip()
    else:
        report = slot.get(f"{mode}_report")
        body = _report_block(mode, report) if isinstance(report, dict) else ""

    return f"[{mode} check]\n{body}" if body else f"[{mode} check] reported nothing usable."


def build_compose_message(message, results):
    """The user message for the compose call: the original question, then one block per agent."""
    blocks = [_slot_block(slot) for slot in results or []]
    return (
        f"The user asked: {message}\n\n"
        + "\n\n".join(blocks)
        + "\n\nWrite the paragraph now."
    )


async def compose_summary(provider, api_key, model_id, message, results, base_url=None):
    """The combined paragraph, or None.

    Never raises. A rate limit, an unreachable provider or an empty reply all return None, which the
    turn renders as "no summary paragraph" rather than as a failure - the reports are the answer, and
    they are already in hand by the time this runs."""
    if not results:
        return None

    try:
        raw = await call_provider(
            provider, api_key, model_id, COMPOSE_SYSTEM_PROMPT,
            build_compose_message(message, results), base_url=base_url,
        )
    except Exception as e:
        logger.warning(f"summary composition failed: {e}")
        return None

    # A model asked for plain prose still sometimes wraps it in a fence or a tag it invented, and
    # that markup would be rendered to the user verbatim as the headline answer.
    summary = xml_common.strip_markup(xml_common.clean(raw))
    return summary[:MAX_SUMMARY_CHARS] or None
