"""Turning a reply into something a Bangla voice can read aloud.

Ported from the browser, where it used to run before each TTS request -- which
meant the /tts endpoint only behaved for one particular client, and this logic
had nowhere to be tested.

One stage per module, in the order the pipeline applies them:

    markup       markdown out, so asterisks are not read aloud
    addresses    URLs said as names, paths dropped
    numbers      digits read as quantities, dictation or ordinals
    latin        English rendered, spelt, or removed
    punctuation  what is left of the marks a voice can say

`for_speech` is the only name the rest of the app uses; the stages are
re-exported so they stay individually testable.

A note on word boundaries, because it is the one thing that did not survive
the port from JavaScript. JS's \\b is ASCII-only, so it sees a boundary between
a Bengali letter and "NID". Python's \\b is Unicode-aware and does not, since
Bengali letters are word characters to it -- so `\\bNID\\b` silently stops
matching in exactly the sentences it exists for. Every pattern that needs the
JavaScript meaning is compiled with re.ASCII.
"""

from src.speech.transform.addresses import (
    DOMAIN_LABEL_BN,
    SERVICE_SITE_BN,
    addresses_for_speech,
    dedupe_site_noun,
)
from src.speech.transform.common import collapse_space, has_bengali
from src.speech.transform.latin import (
    LATIN_LETTER_BN,
    SPOKEN_LATIN,
    SPOKEN_TERMS,
    latin_for_speech,
    spell_latin,
    spoken_latin,
)
from src.speech.transform.markup import strip_markdown
from src.speech.transform.numbers import (
    BN_DIGITS,
    bangla_date_ordinal,
    bangla_hundreds,
    bangla_ordinal,
    digit_by_digit,
    digit_by_digit_english,
    english_ordinal,
    normalize_digits,
    number_to_bangla_words,
    numbers_for_speech,
)
from src.speech.transform.punctuation import punctuation_for_speech

__all__ = [
    "for_speech",
    "addresses_for_speech",
    "dedupe_site_noun",
    "latin_for_speech",
    "numbers_for_speech",
    "punctuation_for_speech",
    "spoken_latin",
    "spell_latin",
    "strip_markdown",
    "collapse_space",
    "has_bengali",
    "normalize_digits",
    "number_to_bangla_words",
    "bangla_hundreds",
    "bangla_ordinal",
    "bangla_date_ordinal",
    "english_ordinal",
    "digit_by_digit",
    "digit_by_digit_english",
    "BN_DIGITS",
    "LATIN_LETTER_BN",
    "SPOKEN_TERMS",
    "SPOKEN_LATIN",
    "SERVICE_SITE_BN",
    "DOMAIN_LABEL_BN",
]


def for_speech(text: str) -> str:
    """The whole pipeline: reply text in, something speakable out.

    Order matters. Markdown goes first so later stages see plain prose.
    Addresses next, while their Latin is still structured enough to recognise
    as a host rather than as words. Numbers before the Latin rules, because a
    helpline label is Bengali and the number beside it is not. Then the Latin
    stages, most accurate first: the known-term table, then letter-by-letter
    spelling, then removal. Punctuation last, because every stage above emits
    commas and daṛis of its own.
    """
    # Decided up front, on the original: numbers_for_speech writes Bangla
    # number words, so asking "is this Bengali?" afterwards says yes for an
    # English reply containing a fee -- and the Latin rules would then delete
    # the answer.
    is_bengali = has_bengali(text)

    out = strip_markdown(text)
    out = addresses_for_speech(out)
    out = numbers_for_speech(out, bengali=is_bengali)
    if is_bengali:
        out = spoken_latin(out)
        out = latin_for_speech(out)
        out = dedupe_site_noun(out)
    return punctuation_for_speech(out)
