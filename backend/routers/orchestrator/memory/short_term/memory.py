"""Assembles a session's short-term memory window from the chats table.

This is the memory equivalent of a tool group's `tool.py`: the actual work, with no knowledge of HTTP.
Its router exposes it; the orchestrator and the agents reach it over that route.

Nothing here re-parses stored XML by hand - every assistant row goes through `from_storage_xml`, the
same reader `GET /linux/sessions/{id}/chats` uses to replay a session into the UI. Memory and the
transcript therefore cannot disagree about what a stored turn said.
"""
import logging

from core.db import get_connection
from routers.orchestrator.xml_output import from_storage_xml
from routers.sessions.queries import list_recent_chats

logger = logging.getLogger("orchestrator.memory")

# The window: three completed user+assistant pairs.
MAX_HISTORY_TURNS = 3

# Per message, after condensing. Three turns of two messages at this cap is roughly 12 KB (~3k
# tokens), which leaves a local model's 16k context (LOCAL_CONTEXT_LENGTH) most of its room for the
# tool schema and this turn's command output. This caps *history*, never a tool schema or an agent's
# capabilities.
MAX_HISTORY_CHARS = 2000

# The classifier needs the subject of the prior turns, not their detail, and has to stay reliable
# enough to answer with a single word - so its copy of the window is cut much harder.
MAX_CLASSIFIER_CHARS = 400

# Rows fetched to fill the window. Over-fetched deliberately: a turn that errored leaves a user row
# with no reply, and those are skipped rather than fed in half-formed. Four rows per wanted turn
# absorbs up to six failed turns before the window comes up short.
FETCH_ROWS = MAX_HISTORY_TURNS * 4

# How each agent mode's report is flattened into prose. `items` is (report key, formatter) for the
# mode's headline list - the rows a follow-up question actually depends on.
_REPORT_SHAPES = {
    "disk": {
        "label": "disk check",
        "headline": lambda report: _disk_capacity(report.get("capacity")),
        "items_key": "top_consumers",
        "item": lambda row: _join_detail(
            row.get("label"), _gb(row.get("size_gb"))
        ),
    },
    "process": {
        "label": "process check",
        "headline": lambda report: _process_load(report.get("load")),
        "items_key": "apps",
        "item": lambda row: _join_detail(
            row.get("name"),
            _csv(_percent(row.get("cpu_percent"), "CPU"), _mb(row.get("memory_mb"))),
        ),
    },
    "network": {
        "label": "network check",
        "headline": lambda report: _network_connectivity(report.get("connectivity")),
        "items_key": "interfaces",
        "item": lambda row: _join_detail(
            row.get("name"), _csv(row.get("state"), row.get("ipv4"))
        ),
    },
}


# ---- Number/detail formatting ----
#
# Every one of these returns None rather than an empty string when it has nothing to say, so the
# joins below can drop absent values instead of emitting "None" or a dangling separator into text a
# model will read as fact.

def _gb(value):
    return f"{value:g} GB" if isinstance(value, (int, float)) else None


def _mb(value):
    return f"{value:g} MB" if isinstance(value, (int, float)) else None


def _percent(value, label=None):
    if not isinstance(value, (int, float)):
        return None
    return f"{value:g}% {label}" if label else f"{value:g}%"


def _csv(*parts):
    joined = ", ".join(part for part in parts if part)
    return joined or None


def _join_detail(name, detail):
    name = (name or "").strip()
    if not name:
        return None
    return f"{name} - {detail}" if detail else name


def _disk_capacity(capacity):
    if not isinstance(capacity, dict):
        return None
    used = _percent(capacity.get("percent_used"))
    free = _gb(capacity.get("free_gb"))
    total = _gb(capacity.get("total_gb"))
    space = f"{free} free of {total}" if free and total else free
    return _csv(f"{used} used" if used else None, space)


def _process_load(load):
    if not isinstance(load, dict):
        return None
    return _csv(
        _percent(load.get("cpu_percent"), "CPU"),
        _percent(load.get("memory_percent"), "memory"),
    )


def _network_connectivity(connectivity):
    if not isinstance(connectivity, dict):
        return None
    severity = connectivity.get("severity")
    failed_at = connectivity.get("failed_at")
    return _csv(severity, f"failed at {failed_at}" if failed_at else None)


def truncate(text, limit=MAX_HISTORY_CHARS):
    """Cuts on a word boundary and marks the cut, so the model can tell it is reading an excerpt
    rather than a complete - and therefore trustworthy - earlier answer.

    Returns (text, was_truncated)."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text, False

    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip() + " ...", True


# ---- Condensing one stored assistant row ----

def _condense_report(mode, report):
    shape = _REPORT_SHAPES[mode]
    lines = []

    summary = (report.get("summary") or "").strip()
    headline = shape["headline"](report)
    opener = f"[{shape['label']}] {summary}" if summary else f"[{shape['label']}]"
    lines.append(f"{opener} ({headline})" if headline else opener)

    explanation = (report.get("explanation") or "").strip()
    if explanation:
        lines.append(explanation)

    items = [shape["item"](row) for row in (report.get(shape["items_key"]) or []) if isinstance(row, dict)]
    items = [item for item in items if item]
    if items:
        lines.append("Findings: " + "; ".join(items))

    facts = [
        f"{(fact.get('label') or '').strip()}: {(fact.get('value') or '').strip()}"
        for fact in (report.get("facts") or [])
        if isinstance(fact, dict) and fact.get("label") and fact.get("value")
    ]
    if facts:
        lines.append("Also: " + "; ".join(facts))

    suggestion = (report.get("suggestion") or "").strip()
    if suggestion:
        lines.append(f"Suggested: {suggestion}")

    return "\n".join(lines)


def condense_assistant(chat_xml):
    """One stored assistant row -> the single plain-text message that stands for it in history.

    A general turn contributes its <content>, deliberately not its raw XML: replaying the markup
    would fill the window with tags and teach the model to imitate the noise along with the format.

    An agent turn has no prose answer at all - it answered through tool calls and a structured
    report - so one is written here from the report's own numbers. The numbers are the point: "which
    of those can I delete?" is unanswerable from a summary sentence alone. `commands_run` is left
    out; it is trace data for the UI, and replaying command output would exhaust the window to tell
    the agent something it can simply check again.

    Returns None when the row yields nothing usable, which drops the pair rather than feeding the
    model a broken turn.
    """
    try:
        parsed = from_storage_xml(chat_xml)
    except Exception:
        logger.warning("short-term memory: unparseable stored assistant row, dropping that turn", exc_info=True)
        return None

    mode = parsed.get("mode", "general")
    if mode not in _REPORT_SHAPES:
        return (parsed.get("content") or "").strip() or None

    report = parsed.get(f"{mode}_report")
    if not isinstance(report, dict) or not report:
        return None
    return _condense_report(mode, report) or None


# ---- The window ----

def _pair_rows(rows):
    """Newest-first rows -> completed (user_row, assistant_row) pairs, oldest first.

    A user row with no assistant row after it is a turn that errored before it could be answered.
    Those are skipped: "the user asked X" with no answer teaches the model nothing and invites it to
    apologise for a failure it did not have.

    That rule also makes this safe to call mid-turn. The newest row during a live turn is the message
    being answered right now, which by definition has no reply yet - so it drops out on its own, and
    the window is identical whether it is read before or after the new user row is inserted.
    """
    pairs = []
    index = 0
    while index < len(rows) and len(pairs) < MAX_HISTORY_TURNS:
        row = rows[index]
        previous = rows[index + 1] if index + 1 < len(rows) else None
        if row["role"] == "assistant" and previous is not None and previous["role"] == "user":
            pairs.append((previous, row))
            index += 2
            continue
        index += 1

    pairs.reverse()
    return pairs


def _load_rows_sync(session_id):
    conn = get_connection()
    try:
        return list_recent_chats(conn, session_id, FETCH_ROWS)
    finally:
        conn.close()


def build_window(session_id, rows):
    """Rows (newest first) -> the neutral window. Split out from the DB read so it is directly
    testable, and so the route can hand it whatever it fetched."""
    turns = []
    truncated = False
    for user_row, assistant_row in _pair_rows(rows):
        answer = condense_assistant(assistant_row["chat"])
        if not answer:
            continue

        question, question_cut = truncate(user_row["chat"])
        if not question:
            continue
        answer, answer_cut = truncate(answer)
        truncated = truncated or question_cut or answer_cut

        turns.append({"role": "user", "content": question})
        turns.append({"role": "assistant", "content": answer})

    return {
        "session_id": session_id,
        "turns": turns,
        "turn_count": len(turns) // 2,
        "truncated": truncated,
    }


def load_rows(session_id):
    """The bounded newest-first read this window is built from. Synchronous - callers run it in a
    worker thread, as every other DB read in the orchestrator does."""
    return _load_rows_sync(session_id)
