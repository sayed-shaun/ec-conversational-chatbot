"""Turning a reply into something a Bangla voice can read aloud.

Ported from the browser, where it used to run before each TTS request -- which
meant the /tts endpoint only behaved for one particular client, and this logic
had nowhere to be tested.

One stage per module, in the order the pipeline applies them:

    layout       line breaks and item numbers become pauses
    markup       markdown out, so asterisks are not read aloud
    addresses    URLs said as names, paths dropped
    codes        postcodes spelt out, before digits look like quantities
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
from src.speech.transform.common import (
    collapse_space,
    has_bengali,
    join_nukta,
    split_nukta,
)
from src.speech.transform.latin import (
    LATIN_LETTER_BN,
    SPOKEN_LATIN,
    SPOKEN_TERMS,
    codes_for_speech,
    latin_for_speech,
    spell_code,
    spell_latin,
    spoken_latin,
    strip_abbrev_dots,
)
from src.speech.transform.layout import layout_for_speech
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
    "codes_for_speech",
    "layout_for_speech",
    "strip_abbrev_dots",
    "latin_for_speech",
    "numbers_for_speech",
    "punctuation_for_speech",
    "spoken_latin",
    "spell_latin",
    "spell_code",
    "strip_markdown",
    "collapse_space",
    "has_bengali",
    "split_nukta",
    "join_nukta",
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

    Order matters. Layout goes first, because it is the only stage that can
    still see the line breaks -- strip_markdown collapses them, and by then
    the structure they carried is gone. Markdown next, so later stages see
    plain prose.
    Addresses next, while their Latin is still structured enough to recognise
    as a host rather than as words. Codes after them and before numbers, since
    a postcode's digits are not a quantity and the number stage cannot tell.
    Numbers before the Latin rules, because a helpline label is Bengali and
    the number beside it is not. Then the Latin
    stages, most accurate first: the known-term table, then letter-by-letter
    spelling, then removal. Punctuation last, because every stage above emits
    commas and daṛis of its own.

    The language is decided before anything is rewritten. numbers_for_speech
    emits Bangla number words, so testing for Bengali afterwards reports yes
    for an English reply containing a fee, and the Latin stages would then
    delete the English answer.

    Around all of it, ড়/ঢ়/য় are folded to one spelling on the way in and the
    other on the way out -- see split_nukta in common.py for why Unicode will
    not do it and what it cost when nothing did.
    """
    is_bengali = has_bengali(text)

    out = split_nukta(text)
    out = layout_for_speech(out)
    out = strip_markdown(out)
    out = strip_abbrev_dots(out)
    out = addresses_for_speech(out)
    out = codes_for_speech(out)
    out = numbers_for_speech(out, bengali=is_bengali)
    if is_bengali:
        out = spoken_latin(out)
        out = latin_for_speech(out)
        out = dedupe_site_noun(out)
    return join_nukta(punctuation_for_speech(out))
