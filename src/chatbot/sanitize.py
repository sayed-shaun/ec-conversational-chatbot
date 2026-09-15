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


# The dataset closes a great many answers with a stock offer of further help.
# Read once it is courteous; read after every single answer it is the reason a
# conversation cannot end, and it is what makes a canned reply sound canned --
# the citizen answers the question they were just asked, gets the same question
# back, and the exchange loops. The information is in the sentence before it;
# this one carries none.
#
# Anchored to the end of the answer, which is the only place it appears, but
# not to a preceding daṛi: the entry the citizen actually saw ran the closer
# straight on from a URL -- "...ঠিকানা হলো services.nidw.gov.bd/ আপনাকে আর
# কোন..." -- with no sentence terminator anywhere before it. Requiring one
# matched nothing in exactly the case that prompted this.
#
# The wording varies across entries -- কি/কী, "আর কোন" against "আর কিছু" --
# so the parts that move are optional rather than spelt out as separate
# patterns.
_CANNED_CLOSER = re.compile(
    r"(?:^|(?<=\s)|(?<=[।.!?]))\s*"
    r"আপনাকে\s+আর\s+(?:কি\s+|কী\s+)?(?:কোন|কোনো|কিছু)\s+"
    r"(?:তথ্য|বিষয়ে)\s+(?:দিয়ে\s+)?সহযোগিতা\s+করতে\s+পারি\s*[?।]?\s*$"
)


def strip_canned_closer(text: str) -> str:
    """Drop the stock "can I help you with anything else" tail.

    Returns the text unchanged when the phrase is the whole of it: an answer
    that is only the closer still has to say something.
    """
    if not text:
        return text or ""
    stripped = _CANNED_CLOSER.sub("", text).strip()
    return stripped or text.strip()


# The knowledge base sends a caller who cannot be helped to the 105 helpline.
# That was the right advice while the reply was read in a browser. Reached
# over the phone it is absurd: the citizen is already on a call, and being
# told to place another one is a dead end -- so the same instruction becomes
# "press 0", which transfers them to a person without hanging up.
#
# Bengali inflects the verb, so the ending is carried across rather than
# replaced wholesale: "কল করে" is a participle and becomes "চেপে", while
# "কল করুন" is an imperative and becomes "চাপুন". Substituting one form
# everywhere would leave half the corpus ungrammatical.
_PRESS = {
    "ুন": "চাপুন",
    "ে": "চেপে",
    "েও": "চেপেও",
    "ার": "চাপার",
    "তে": "চাপতে",
}

# The digit is left as "০" rather than written "শূন্য": on screen it is the
# key to press, and the number stage reads it aloud as শূন্য anyway.
_ZERO = "০"

# Ordered, most specific first. The first pattern carries the helpline's name
# with it -- "নির্বাচন কমিশনের হেল্পলাইন ১০৫ নম্বরে কল করুন" -- because
# replacing only the number leaves "হেল্পলাইন ০ চাপুন", which names a
# helpline and then tells the caller to press a key on it.
# The corpus spells the particle after the number every way it can -- "১০৫-এ",
# "১০৫ নম্বরে", "১০৫ নাম্বারে", "১০৫ এর", and once "১০৫ নম্বরে এ" -- so it is
# written once here rather than three times below.
#
# Whatever follows must be an instruction to call: কল, ফোন or যোগাযোগ. That
# requirement is what leaves "আপনার মোবাইলে ১০৫ থেকে এসএমএস পাবেন" alone,
# where 105 is the sender of a message and not a number to ring.
_PARTICLE = r"(?:-\s*)?(?:এর|এ|তে|নম্বরে|নাম্বারে|নম্বর|নাম্বার)?\s*(?:এ\s*)?"

_HELPLINE_105 = [
    re.compile(
        r"(?:বাংলাদেশ\s*)?(?:নির্বাচন\s*)?(?:কমিশনে?র?\s*)?(?:আমাদের\s*)?(?:ফ্রি\s*)?"
        r"(?:হেল্পলাইন|কল\s*সেন্টার|কলসেন্টার)\s*-?\s*১০৫\s*" + _PARTICLE
        + r"(?:কল|ফোন|যোগাযোগ)\s*কর(ুন|েও|ে|ার|তে)"
    ),
    re.compile(r"(?:কল|ফোন)\s*কর(ুন|েও|ে|ার|তে)\s*১০৫\s*(?:নম্বরে|নাম্বারে|এ|তে)?"),
    re.compile(r"১০৫\s*" + _PARTICLE + r"(?:কল|ফোন|যোগাযোগ)\s*কর(ুন|েও|ে|ার|তে)"),
]

_AGENT_PHRASE = "সরাসরি আমাদের প্রতিনিধির সাথে কথা বলতে "


def press_zero_for_agent(text: str) -> str:
    """Turn "call 105" into "press 0", which is what a caller can act on."""
    if not text or "১০৫" not in text:
        return text or ""

    out = text
    for index, pattern in enumerate(_HELPLINE_105):
        def swap(m: "re.Match") -> str:
            press = _PRESS.get(m.group(1), "চাপুন")
            # Only the named-helpline form needs the clause rebuilt; the
            # others already sit in a sentence that says who is being reached.
            lead = _AGENT_PHRASE if index == 0 else ""
            return f"{lead}{_ZERO} {press}"

        out = pattern.sub(swap, out)
    return out


# The corpus writes a list inline, with a bracketed number and no line break
# anywhere in it:
#
#     নিজ নাম (বাংলা ও ইংরেজী) এর ক্ষেত্রেঃ (১) অনলাইন জন্ম সনদ (বাংলা ও
#     ইংরেজী) (২) শিক্ষাগত যোগ্যতা ... (৩) ড্রাইভিং লাইসেন্স (যদি থাকে)
#
# Five separate documents arrive as one unbroken paragraph. On screen the
# citizen has to pick them out by eye; down a phone line it is worse, because
# the brackets do not survive the trip to the voice and the caller hears
# "...সনদ বাংলা ও ইংরেজী দুই শিক্ষাগত যোগ্যতা...", the item number sounding
# like part of the document before it.
#
# Both are the same missing line break, so it is put in here rather than in
# either consumer -- there is nowhere else that serves both. The browser reads
# the two trailing spaces as markdown's hard break; the speech pipeline's
# layout stage turns the newline into a daṛi and then finds the marker at the
# start of a line, where its existing rule gives it a comma to pause on. An
# Asterisk dialplan does neither, and does not have to: what reaches the TTS
# already carries the pauses.
#
# One or two digits and nothing else inside the brackets, which is what leaves
# a year -- "(১৯৭২)" -- and the parentheticals the corpus is full of --
# "(বাংলা ও ইংরেজী)", "(ভ্যাটসহ)", "(যদি থাকে)" -- untouched. Something has to
# follow, or a trailing "(২)" would be given a line of its own to sit on.
_BRACKET_ITEM = re.compile(r"[ \t]+(?=\((?:[০-৯]{1,2}|[0-9]{1,2})\)[ \t]*\S)")


# The corpus writes its own line breaks, and markdown eats them: a single
# newline is whitespace there, so an answer the dataset laid out as
#
#     নিজ নাম (বাংলা ও ইংরেজী) এর ক্ষেত্রেঃ
#     (১) অনলাইন জন্ম সনদ (বাংলা ও ইংরেজী)
#     (২) শিক্ষাগত যোগ্যতা ...
#
# reaches the reader as one unbroken paragraph with the markers buried in
# it. The layout was there all along; only the rendering lost it.
#
# Two trailing spaces is markdown's hard break, which is what makes the
# newline survive. A blank line is left alone -- that is a paragraph break
# and already renders as one. The speech path is unaffected either way: its
# layout stage strips a line's trailing whitespace before it looks at what
# the line ends with.
_SOFT_BREAK = re.compile(r"(?<!\n)[ \t]*\n(?!\s*\n)")


def hard_break_lines(text: str) -> str:
    """Make the answer's own line breaks survive markdown."""
    if not text:
        return text or ""
    return _SOFT_BREAK.sub("  \n", text)


def break_bracket_items(text: str) -> str:
    """Put each inline "(১)" item on its own line."""
    if not text:
        return text or ""
    return _BRACKET_ITEM.sub("  \n", text)


def mentions_tool(text: str) -> bool:
    """True if `text` names one of the tools."""
    return bool(_TOOL_MENTION.search(text or ""))


def scrub(text: str) -> str:
    """Drop every sentence that names a tool, leaving the rest untouched.

    "Call 105" becomes "press 0" here as well as on the dataset path: the
    prompt tells the model to offer the helpline, and a model does not follow
    a prompt reliably enough for that to be the only place it is handled.

    Returns "" if that removes everything -- the caller decides what to say
    instead, since an empty reply is never the right thing to show.
    """
    text = hard_break_lines(
        break_bracket_items(
            press_zero_for_agent(
                normalize_nid(strip_foreign_script(strip_protocol(text)))
            )
        )
    )
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
