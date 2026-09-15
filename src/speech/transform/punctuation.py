"""Punctuation the voice can and cannot say.

A comma earns its place, as the voice pauses on it, and so does a daṛi. The
rest is either read aloud as a word or swallowed as a glitch, so it goes --
and "the rest" means everything, not only the marks that are obviously
unspeakable. A question mark, an abbreviating dot and a compound's hyphen
all reached the voice intact and none of them can be voiced; what the model
does with them is not a pause.

The two marks that stay are the two that are heard.

Two marks need judgement rather than deletion. A slash carries meaning --
"উপজেলা/থানা" means "or" -- and becomes that word. A hyphen is kept when it
joins a compound such as রি-ইস্যু and removed when a space on one side shows
it was left behind by a dropped English word.
"""

import re

from src.speech.transform.common import collapse_space

_SLASH_BETWEEN_WORDS = re.compile(r"(?<=\S)\s*/\s*(?=\S)")

_ORPHAN_HYPHEN = re.compile(r"\s+-+|-+\s+")

# En dash, em dash and horizontal bar separate clauses. Read aloud they are
# nothing, but removing them outright joins the words on either side, so they
# become the pause they already are in the text.
_DASH = re.compile(r"\s*[\u2013\u2014\u2015]+\s*")

_UNSPEAKABLE = re.compile(r"[()\[\]{}\"'“”‘’:;|<>+=*_~^\\@#$%&]")

# A full stop inside a web address is already "ডট" by the time it reaches
# here, put there by the addresses stage. What is left is the dot that
# abbreviates -- "পি.এস.সি", "দ.আফ্রিকা" -- which the voice cannot say and
# which is not a sentence ending either. The dots go and the letters keep
# their spaces, so the initials are read as initials.
_BENGALI_ABBREV_DOT = re.compile(r"(?<=[\u0980-\u09FF])\.(?=[\u0980-\u09FF])")

# What is left after that is a dot the corpus uses as a stop of some kind:
# the ellipsis in "যাচাই করা হচ্ছে...।", and the separators an address ends
# up with once its English has been spelt out -- "সেক্টর. উনিশ", "কানাডা.
# অ্যাট্রিয়াম". A dot already leaning on a daṛi is absorbed by it. One at
# the very end becomes the daṛi it was standing in for. One in the middle
# becomes a comma rather than a daṛi: it is separating the parts of an
# address, and a full stop there reads as the address having finished.
_DOTS_BEFORE_DARI = re.compile(r"\.+(?=\s*।)")
_DOTS_AT_END = re.compile(r"(?<=[\u0980-\u09FF])\.+\s*$")
_DOTS_MID = re.compile(r"(?<=[\u0980-\u09FF])\.+")

# A bisarga does two unrelated jobs. Inside a word it is a letter --
# "দুঃখিত" is spelt with one, and taking it out leaves a misspelling the
# voice reads as a different word. At the end of one it is the corpus's
# colon, introducing the list that follows: "নিজ নাম ... এর ক্ষেত্রেঃ". Only
# the second is punctuation, and a comma is the pause it was standing in
# for.
_TRAILING_BISARGA = re.compile(r"\u0983(?=\s|$)")

# A hyphen joining two Bengali pieces is inside a word -- "রি-ইস্যু",
# "পাঁচ-এ" -- and the mark itself has no sound. Closing it up leaves the word
# the compound already was; a space would break it into two.
_COMPOUND_HYPHEN = re.compile(r"(?<=[\u0980-\u09FF])-(?=[\u0980-\u09FF])")

# The voice has no intonation to give a question mark, so it is read as
# nothing or as a word. A daṛi is the pause that is actually wanted at the
# end of the sentence either way.
_QUESTION = re.compile(r"\?")


def punctuation_for_speech(text: str) -> str:
    """Leave only the two marks the voice can say: a comma and a daṛi."""
    text = _BENGALI_ABBREV_DOT.sub(" ", text)
    text = _DOTS_BEFORE_DARI.sub("", text)
    text = _DOTS_AT_END.sub("।", text)
    text = _DOTS_MID.sub(",", text)
    text = _TRAILING_BISARGA.sub(",", text)
    text = _COMPOUND_HYPHEN.sub("", text)
    text = _QUESTION.sub("।", text)
    text = _SLASH_BETWEEN_WORDS.sub(" বা ", text)
    text = _DASH.sub(" ", text)
    text = _ORPHAN_HYPHEN.sub(" ", text)
    text = _UNSPEAKABLE.sub(" ", text)
    text = re.sub(r"\s+([।,!])", r"\1", text)
    text = re.sub(r"([।,!])\1+", r"\1", text)
    # A comma that has landed against a daṛi is one mark too many: the
    # bisarga above becomes a comma without knowing what follows it.
    text = re.sub(r",\s*।", "।", text)
    return collapse_space(text)
