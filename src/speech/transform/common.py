"""Helpers the other speech stages share.

Small on purpose. Anything used by exactly one stage lives in that stage's
module instead, so each file can be read on its own.
"""

import re

_BENGALI = re.compile(r"[ঀ-৿]")

SENTENCE_SPLIT = re.compile(r"(?<=[।.!?])")

_SPACE = re.compile(r"\s+")

# Bengali writes ড়, ঢ় and য় either as a single code point or as a base
# letter followed by a nukta. The two spellings render identically, compare
# unequal, and Unicode will not reconcile them: all three are composition
# exclusions, so NFC leaves a decomposed pair decomposed and NFD takes the
# single code point apart. Neither normal form unifies them, so it is done
# here by hand.
#
# It matters because the two halves of this system disagree. Every rule in
# this package is written with the decomposed spelling, while the FAQ dataset
# uses the single code point -- so "২য়" from the dataset slipped past the
# ordinal rule and came out spoken as "দুইয়", a number with an orphan suffix
# stuck to it, instead of "দ্বিতীয়". It was the fee answers that said it.
#
# So input is folded apart before anything matches, and the finished line is
# folded back together: the single code point is the form the dataset and the
# corpus use, and one spelling per sentence is what keeps the audio cache from
# holding two entries for the same words.
_NUKTA_PAIRS = (
    ("\u09a1\u09bc", "\u09dc"),  # ড + ়  <->  ড়
    ("\u09a2\u09bc", "\u09dd"),  # ঢ + ়  <->  ঢ়
    ("\u09af\u09bc", "\u09df"),  # য + ়  <->  য়
)


def split_nukta(text: str) -> str:
    """Spell ড়, ঢ় and য় as a base letter plus a nukta, as the rules do."""
    for apart, together in _NUKTA_PAIRS:
        text = text.replace(together, apart)
    return text


def join_nukta(text: str) -> str:
    """Spell ড়, ঢ় and য় as the single code point, as the dataset does."""
    for apart, together in _NUKTA_PAIRS:
        text = text.replace(apart, together)
    return text


def has_bengali(text: str) -> bool:
    """Whether any Bengali appears in `text`.

    Presence, not majority: "Google Play Store থেকে NID Wallet অ্যাপ" has
    more Latin letters than Bengali and is still a Bengali sentence.
    """
    return bool(_BENGALI.search(text or ""))


def collapse_space(text: str) -> str:
    return _SPACE.sub(" ", text).strip()
