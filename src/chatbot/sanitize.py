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


# The model also imitates the tool-calling protocol in its own prose, emitting
# a reply that begins "query: ..." followed by a tool_output block and a JSON
# object it invented. None of that carries the tool's name, so the sentence
# rule above does not see it, and a citizen is shown machine plumbing plus a
# fabricated result.
#
# Matched by line, because that is the shape the model produces: an ASCII
# label with a colon, or a line of JSON carrying one of the result keys. Both
# tests are deliberately narrow -- a Bengali reply contains neither.
_PROTOCOL_LABEL = re.compile(
    r"^\s*(?:query|tool|tool_call|tool_input|tool_output|tool_result|tool_response"
    r"|function|function_call|arguments|args|observation|thought|action|input"
    r"|output|response|result)\s*:",
    re.IGNORECASE | re.ASCII,
)

_RESULT_KEYS = re.compile(
    r'"(?:best_answer|alternatives|confident|input_question|best_tag|top_k'
    r'|CONFIDENCE_THRESHOLD|runner_up_score|min_score_ratio)"'
)

_JSON_NOISE = re.compile(r"^\s*[\[\]{},]*\s*$")


# The model is only ever supposed to answer in Bengali or English, but a
# quantised model occasionally drops a stray token from an unrelated script
# into an otherwise clean sentence -- e.g. a lone Korean word mid-answer.
# That is never legitimate content, so any whitespace-delimited run
# containing a character from one of these blocks is dropped outright.
_STRAY_SCRIPT_CHAR = (
    "ᄀ-ᇿ"  # Hangul Jamo
    "぀-ヿ"  # Hiragana / Katakana
    "㄰-㆏"  # Hangul Compatibility Jamo
    "㐀-䶿"  # CJK Unified Ideographs Extension A
    "一-鿿"  # CJK Unified Ideographs
    "가-힣"  # Hangul Syllables
    "豈-﫿"  # CJK Compatibility Ideographs
    "฀-๿"  # Thai
)
_STRAY_SCRIPT_WORD = re.compile(rf"\s*\S*[{_STRAY_SCRIPT_CHAR}]\S*")


def strip_foreign_script(text: str) -> str:
    """Drop words containing a character from a script that is neither
    Bengali nor Latin -- glitch tokens the prompt's language rule can't
    prevent at the source."""
    if not text:
        return text or ""
    cleaned = _STRAY_SCRIPT_WORD.sub(" ", text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


# Another glitch the same quantised model produces: spelling "NID" half in
# one script and half in the other -- এনID, Nআইডি, or a bare Latin NID
# dropped into a Bengali sentence. All are normalised to the Bengali word.
_BENGALI_CHAR = re.compile(r"[ঀ-৿]")
_NID_VARIANTS = re.compile(
    r"এন\s*ID"  # এনID, এন ID
    r"|N\s*আইডি"  # Nআইডি, N আইডি
    r"|(?<![^\W\d_])NID(?![^\W\d_])",  # a bare NID between non-letters
    re.IGNORECASE,
)


def normalize_nid(text: str) -> str:
    """Spell NID consistently as এনআইডি in a Bengali reply.

    Left alone when the reply carries no Bengali at all: an English answer
    is supposed to say "NID", and rewriting it would put a Bengali word in
    the middle of an English sentence -- the very mixing this fixes.
    """
    if not text or not _BENGALI_CHAR.search(text):
        return text or ""
    return _NID_VARIANTS.sub("এনআইডি", text)


def _is_protocol(line: str) -> bool:
    """Whether a line is machine protocol rather than an answer."""
    if _PROTOCOL_LABEL.match(line):
        return True
    if _RESULT_KEYS.search(line):
        return True
    stripped = line.strip()
    if stripped.startswith(("{", "}", "[", "]")) and not any(
        "\u0980" <= c <= "\u09ff" for c in stripped
    ):
        return True
    return False


def strip_protocol(text: str) -> str:
    """Drop lines where the model imitated the tool-calling protocol."""
    lines = (text or "").splitlines()
    if not any(_is_protocol(line) for line in lines):
        return text or ""
    kept = [line for line in lines if not _is_protocol(line)]
    kept = [line for line in kept if not _JSON_NOISE.match(line)]
    return "\n".join(kept).strip()


def mentions_tool(text: str) -> bool:
    """True if `text` names one of the tools."""
    return bool(_TOOL_MENTION.search(text or ""))


def scrub(text: str) -> str:
    """Drop every sentence that names a tool, leaving the rest untouched.

    Returns "" if that removes everything -- the caller decides what to say
    instead, since an empty reply is never the right thing to show.
    """
    text = normalize_nid(strip_foreign_script(strip_protocol(text)))
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
