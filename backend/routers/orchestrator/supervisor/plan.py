"""Deciding which agents answer a message, and what each of them is asked.

This is the planning work with no knowledge of HTTP - its router exposes it, and the orchestrator
reaches it over that route. It replaces the old single-word classifier: a plan of one step is exactly
what that returned, so nothing about a single-subject question changed when this arrived.

The parser is deliberately forgiving. The planner call is the one provider call in a turn that a weak
local model is most likely to answer sloppily - a numbered list, a stray sentence, the same agent
twice - and every one of those failures has an obvious reading. What it will not do is invent an
agent that was not named, or let a sloppy reply grow the turn beyond three agents.
"""
import logging
import re

from prompts import load_prompt
from routers.orchestrator.clients import call_provider
from routers.orchestrator.memory.short_term.render import as_classifier_context

logger = logging.getLogger("orchestrator.supervisor")

PLAN_SYSTEM_PROMPT = load_prompt("orchestrator_plan")

# The specialist agents' modes. "general" is the base agent - a fourth agent with its own route, not
# a non-agent path - but it stays separate here for two reasons it alone has: it is the no-match
# fallback, and it is dropped whenever a specialist is also named.
AGENT_MODES = ("disk", "process", "network")
GENERAL = "general"

# Three agents is up to three full tool loops on one message. A fourth turns a question into minutes
# of wall clock and a near-certain rate limit on a free tier, so the cap is enforced here regardless
# of what the planner asks for.
MAX_STEPS = 3

# A sub-question is a sentence, not an essay. A planner that starts writing the answer itself gets
# cut off rather than handing an agent a wall of invented context.
MAX_QUESTION_CHARS = 300


def _match_mode(text):
    """A whole-word match against a lowercased fragment, or None.

    Substring matching cannot survive more than one agent: "process" is a substring of plenty of
    prose, and a line like "this is a general question about disk usage" would match whichever mode
    was checked first. Specialists are checked before "general" so that a line naming both resolves
    to the specialist, which is the same precedence the exclusivity rule applies below."""
    stripped = text.strip().strip(" .\"'`*-#").lower()
    if stripped in AGENT_MODES or stripped == GENERAL:
        return stripped

    for mode in (*AGENT_MODES, GENERAL):
        if re.search(rf"\b{mode}\b", stripped):
            return mode
    return None


def _split_line(line):
    """One reply line -> (mode, question). `disk: how full is the drive` gives both; a bare `disk`
    gives the mode and no question.

    A line whose left side names nothing known is searched whole before being given up on, so a
    planner that wrote a sentence instead of a list ("I'd check the disk first") still contributes
    the agent it named - without its prose being passed on as a sub-question."""
    head, separator, tail = line.partition(":")

    mode = _match_mode(head)
    if mode is not None:
        return mode, (tail if separator else "")

    mode = _match_mode(line)
    return mode, ""


def _clean_question(question, mode):
    """The sub-question an agent is actually given, or None to send it the user's own message.

    None is the safe default, and every doubtful case lands on it: an empty tail, or a tail that just
    repeats the agent's name, would otherwise replace a real question with nothing."""
    question = (question or "").strip().strip("\"'").strip()
    if not question or question.strip(" .").lower() == mode:
        return None
    return question[:MAX_QUESTION_CHARS]


def parse_plan(raw):
    """The planner's reply -> a list of 1-3 {"mode", "question"} steps, in the order they run.

    Order is the investigation order and is preserved as given. Duplicates are dropped on first
    sight, "general" is dropped whenever a specialist survived, and a reply naming nothing known
    falls back to a single "general" step - the same no-match behaviour the classifier had."""
    steps = []
    seen = set()

    for line in (raw or "").splitlines():
        if not line.strip():
            continue
        mode, question = _split_line(line)
        if mode is None or mode in seen:
            continue
        seen.add(mode)
        steps.append({"mode": mode, "question": _clean_question(question, mode)})

    # "general" is the fallback, so a weaker model tacks it onto everything. A message that genuinely
    # needs a specialist does not also need the fallback, and each extra agent is a full tool loop.
    specialists = [step for step in steps if step["mode"] != GENERAL]
    if specialists:
        steps = specialists

    if not steps:
        # Worth seeing in the log: a reply that matched nothing means the planner prompt and the
        # registered agents have drifted apart, and every such turn silently takes the general path.
        logger.info(f"planner reply named no known agent, using general: {raw!r:.120}")
        return [{"mode": GENERAL, "question": None}]

    if len(steps) > MAX_STEPS:
        logger.info(f"planner named {len(steps)} agents, keeping the first {MAX_STEPS}")

    return steps[:MAX_STEPS]


async def plan_turn(provider, api_key, model_id, message, base_url=None, history=None):
    """`history` is folded into the single user message rather than sent as prior turns.

    A follow-up like "and what about /var?" names nothing plannable on its own and would fall through
    to "general", which is the most visible symptom of a planner with no memory. But the fix cannot
    be a real multi-turn array: this call's entire contract is a short list of agent names, and prior
    turns presented as actual assistant messages invite a weaker model to answer the conversation
    instead of planning it. Inline context reads as part of the one instruction it was given.

    With no history the message is sent exactly as it was."""
    if history:
        message = as_classifier_context(history) + message

    raw = await call_provider(
        provider, api_key, model_id, PLAN_SYSTEM_PROMPT, message, base_url=base_url
    )
    return parse_plan(raw)
