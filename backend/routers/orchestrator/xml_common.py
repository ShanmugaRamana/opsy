"""Parsing helpers shared by the orchestrator's XML replies.

The base orchestrator and the disk agent both ask the model for a fixed XML shape, and both meet the
same non-compliance: prose wrapped around the block, a reply truncated mid-tag, bare ampersands from
command output quoted back, and markdown fences. These helpers live here so the two parsers cannot
drift - the disk path was hardened first, and the general path was still dumping raw markup at the
user months later because the fix had not been shared.
"""
import re
from functools import lru_cache

CODE_FENCE_RE = re.compile(r"^```(?:xml)?\s*|\s*```$", re.MULTILINE)
# A bare "&" is not valid XML and is common in command output quoted back by the model.
BARE_AMP_RE = re.compile(r"&(?!#?\w+;)")
# Only markup shaped like a real tag. A plain "<[^>]*>" cannot tell a tag from a comparison, and
# these answers are full of comparisons: "<1 GB free ... grew >90%" would lose the figure that was
# actually asked for.
TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9_.:-]*(?:\s[^<>]*)?/?>")

# How much of a non-compliant reply to log: enough to see what the model sent, capped so a runaway
# reply does not flood the log.
LOG_EXCERPT_CHARS = 600


@lru_cache(maxsize=32)
def _closed_re(tag):
    return re.compile(rf"<{tag}\b.*?</{tag}>", re.DOTALL | re.IGNORECASE)


@lru_cache(maxsize=32)
def _open_re(tag):
    return re.compile(rf"<{tag}\b.*", re.DOTALL | re.IGNORECASE)


def clean(raw_text):
    """Strips markdown fences and surrounding whitespace."""
    return CODE_FENCE_RE.sub("", raw_text or "").strip()


def extract_block(text, tag):
    """Pulls a <tag>...</tag> block out of a reply, tolerating surrounding prose and a missing
    closing tag (which happens when the model is cut off mid-answer)."""
    match = _closed_re(tag).search(text)
    if match:
        return match.group(0)

    match = _open_re(tag).search(text)
    if match:
        return f"{match.group(0).rstrip()}</{tag}>"

    return None


def drop_block(text, tag):
    """Removes a block and everything after its opening tag - used to keep the model's internal
    reasoning out of a salvaged answer."""
    without_closed = _closed_re(tag).sub("", text)
    return _open_re(tag).sub("", without_closed)


def strip_markup(text):
    """Removes tag-shaped markup, leaving prose (and comparisons like "<1 GB") intact."""
    return TAG_RE.sub("", text or "").strip()


def excerpt(text):
    """A truncated repr for logging a non-compliant reply."""
    return repr(text or "")[:LOG_EXCERPT_CHARS]
