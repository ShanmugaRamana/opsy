"""The base agent's reply parsing.

Deliberately thin: the <response><thinking/><content/></response> shape is the one the orchestrator
has always stored for a general turn, and `xml_output.parse_response` is the reader that both this
agent and the session replay path use. Duplicating it here would let a live answer and its replay
disagree about the same text. What this module adds is the part only the live agent has - the
narration it streamed on the way to the answer - which is worth more than a placeholder when the
model never produced a parseable block.
"""
import logging

from routers.orchestrator import xml_output

logger = logging.getLogger("orchestrator.base")


def parse_base_answer(raw_text, narration=""):
    """Returns (thinking, content) for the base agent's final event.

    `narration` is everything already streamed to the user as thinking this turn. It is used twice:
    as the thinking of a reply that gave an answer but no <thinking>, and as the answer itself when
    the reply had no readable <content> at all - the same salvage the disk agent performs, for the
    same reason. A user who watched the model reason for ten seconds should not be handed "the model
    finished without returning a readable answer" while that reasoning sits one panel away.
    """
    narration = (narration or "").strip()
    thinking, content = xml_output.parse_response(raw_text or "")

    if content == xml_output.NO_ANSWER_CONTENT and narration:
        logger.warning("base agent returned no readable answer; falling back to streamed narration")
        return None, narration

    if thinking is None and narration:
        thinking = narration

    return thinking, content
