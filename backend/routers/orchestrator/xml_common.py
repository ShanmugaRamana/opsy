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


# ---- Streaming ----

# A tag opens with '<' followed by a name, or '</' followed by one. Anything else after '<' is prose:
# "less than <1 GB free" is an answer, not markup.
_TAG_OPEN_RE = re.compile(r"^</?[A-Za-z]")
_TAG_NAME_RE = re.compile(r"^</?\s*([A-Za-z][A-Za-z0-9_.:-]*)")
# A '<' with no '>' behind it eventually stops being a tag that got split across chunks and starts
# being prose the stream is holding hostage. Past this many characters it is released as text.
MAX_PARTIAL_TAG = 120


class ThinkingStream:
    """Decides, chunk by chunk, which of a model's reply may be streamed to the user as thinking.

    The agents that answer with a report write their reasoning as prose *before* the XML, so
    `narration_prefix_len` in agents/shared.py can split on the first tag and stop. The base agent
    reasons *inside* <thinking>, and its answer lives inside <content> in the same block, so the
    split cannot be a prefix rule - it needs to track where in the markup the stream currently is.

    What comes back from `feed` is everything that is neither markup nor inside a suppressed block:
    prose written before any tag (a model thinking out loud on its way to the XML) and the contents
    of <thinking>. <content> is withheld, because the answer is delivered once, in the final event -
    streaming it into the trace panel as well would show the user the same text twice.

    A chunk boundary can split a tag ('<think' + 'ing>'), so a trailing fragment that could still
    become one is held back until the next chunk decides. `finish` flushes what is left when the
    round ends; an unterminated tag fragment at that point is markup and is dropped rather than
    leaked into the panel.
    """

    def __init__(self, suppress=("content",)):
        self._suppress = {tag.lower() for tag in suppress}
        self._pending = ""
        self._depth = 0

    def feed(self, chunk):
        self._pending += chunk or ""
        return self._scan(final=False)

    def finish(self):
        return self._scan(final=True)

    def _take(self, count):
        """Consumes `count` characters of prose, returning them only if they are not inside a
        suppressed block."""
        text = self._pending[:count]
        self._pending = self._pending[count:]
        return "" if self._depth else text

    def _apply(self, tag):
        match = _TAG_NAME_RE.match(tag)
        if match is None or match.group(1).lower() not in self._suppress:
            return
        if tag.startswith("</"):
            self._depth = max(0, self._depth - 1)
        elif not tag.endswith("/>"):
            self._depth += 1

    def _scan(self, final):
        out = []
        while self._pending:
            index = self._pending.find("<")
            if index == -1:
                out.append(self._take(len(self._pending)))
                break
            if index > 0:
                out.append(self._take(index))
                continue

            # The buffer now starts at a '<'. Until enough characters have arrived to tell a tag from
            # a comparison, there is nothing to decide yet.
            if len(self._pending) < 2 and not final:
                break
            if not _TAG_OPEN_RE.match(self._pending):
                # "</" is a closing tag whose name has not arrived yet - never prose.
                if self._pending.startswith("</") and len(self._pending) == 2:
                    if final:
                        self._pending = ""
                    break
                out.append(self._take(1))
                continue

            end = self._pending.find(">")
            if end == -1:
                if not final and len(self._pending) <= MAX_PARTIAL_TAG:
                    break
                if final:
                    # A reply cut off mid-tag: the fragment is markup, so it is dropped.
                    self._pending = ""
                    break
                # Too long to still be a tag - it was prose all along.
                out.append(self._take(len(self._pending)))
                continue

            tag = self._pending[:end + 1]
            self._pending = self._pending[end + 1:]
            self._apply(tag)

        return "".join(out)
