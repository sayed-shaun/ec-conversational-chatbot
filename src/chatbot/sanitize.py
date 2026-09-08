"""
Last-resort scrub of the assistant's own plumbing out of a reply.

The prompt already tells the model not to mention the tool, but a 2-bit
quantised model does not reliably obey that -- it has been observed replying
"আমি `search_ec_services` টুল ব্যবহার করতে পারি" instead of answering. A rule
in the prompt is a request; this module is the guarantee, so the tool name can
never reach a citizen reading the chat.

Removal is per sentence, not per word: dropping just the identifier out of
"আমি X টুল ব্যবহার করতে পারি" leaves a sentence that still narrates the
lookup, which is the actual problem. Bengali sentences end in a daṛi (।), so
that counts as a terminator alongside the ASCII ones.
"""

import re
from typing import Iterable, List

from src.chatbot.tools import TOOLS

_TERMINATORS = "।.!?\n"
_SENTENCE_SPLIT = re.compile(rf"(?<=[{_TERMINATORS}])")


def _tool_names() -> List[str]:
    """Every name the model could be told about, newest schema first.

    Retired names stay on the list because a transcript checkpointed
    before a tool was renamed can still mention the old one.
    """
    names = [
        t["function"]["name"]
        for t in TOOLS
        if t.get("type") == "function" and t.get("function", {}).get("name")
    ]
    names += ["search_faq", "health"]
    return names


def _name_pattern(names: Iterable[str]) -> re.Pattern:
    """Match a tool name however the model chose to dress it up: bare, in a
    code span, bolded, or with the underscores written as spaces."""
    alts = []
    for name in sorted(set(names), key=len, reverse=True):
        loose = re.escape(name).replace("_", r"[\s_\-]?")
        alts.append(loose)
    return re.compile(rf"[`*_]*(?:{'|'.join(alts)})[`*_]*", re.IGNORECASE)


_TOOL_MENTION = _name_pattern(_tool_names())


def mentions_tool(text: str) -> bool:
    """True if `text` names one of the tools."""
    return bool(_TOOL_MENTION.search(text or ""))


def scrub(text: str) -> str:
    """Drop every sentence that names a tool, leaving the rest untouched.

    Returns "" if that removes everything -- the caller decides what to say
    instead, since an empty reply is never the right thing to show.
    """
    if not text or not mentions_tool(text):
        return text or ""

    kept = [s for s in _SENTENCE_SPLIT.split(text) if not mentions_tool(s)]
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", "".join(kept))).strip()


class StreamScrubber:
    """Sentence-buffered `scrub` for the streaming path.

    Tokens cannot be filtered as they arrive: by the time the tool name is
    recognisable it would already be on screen, and a leak that flickers in
    the UI has still been shown. So text is held back until a sentence is
    terminated, then that whole sentence is either emitted or dropped. The
    cost is that the reply appears a sentence at a time rather than a word at
    a time, which is the price of the guarantee.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self.emitted = ""

    def feed(self, chunk: str) -> str:
        """Take a raw delta, return whatever is now safe to show (may be "")."""
        self._buffer += chunk or ""
        last = max((self._buffer.rfind(t) for t in _TERMINATORS), default=-1)
        if last < 0:
            return ""
        complete, self._buffer = self._buffer[: last + 1], self._buffer[last + 1 :]
        return self._take(complete)

    def flush(self) -> str:
        """Emit what is left once the model has stopped, sentence or not."""
        complete, self._buffer = self._buffer, ""
        return self._take(complete)

    def _take(self, text: str) -> str:
        out = scrub(text).lstrip()
        if not out:
            return ""
        if self.emitted and not self.emitted[-1].isspace():
            out = " " + out
        self.emitted += out
        return out
