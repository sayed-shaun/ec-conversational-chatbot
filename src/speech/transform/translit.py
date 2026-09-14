"""English spelt out in Bengali letters, for words nothing else knows.

The stages before this one cover the English that was known in advance:
SPOKEN_TERMS has a rendering for every Latin token in the knowledge base,
and initialisms are spelt letter by letter. What reaches here is the
remainder -- a word the model wrote that the corpus never contained.

The remainder used to be deleted. That was defensible while the reply was
read on a screen, with the English still sitting in the text above; down a
phone line it means a sentence quietly loses a word and the caller never
learns one was missing. A rough Bengali spelling of an English word is
imperfect, but a caller hears something and can ask again -- which silence
never lets them do.

The mapping is orthographic, not phonetic: English spelling does not
determine English pronunciation, so "receipt" comes out with its p. The aim
is a listener recognising the word, not a lexicon.

Bengali writes a consonant with an inherent 'অ' already in it, so the work
is deciding what follows each consonant: a vowel sign when a vowel comes
next, a hasanta when another consonant does. Getting that wrong is what
turns a cluster into gibberish, which is why this is assembled unit by unit
rather than substituted letter by letter.
"""

import re

# Vowels carry two forms: standing alone at the start of a word, and as a
# sign hung on the preceding consonant. Digraphs come first so "ee" is never
# read as two "e"s.
VOWELS = {
    "eau": ("ও", "ো"),
    "ough": ("ও", "ো"),
    "ee": ("ঈ", "ী"),
    "ea": ("ই", "ি"),
    "oo": ("উ", "ূ"),
    "ou": ("আউ", "াউ"),
    "ow": ("আও", "াও"),
    "oi": ("অই", "ৈ"),
    "oy": ("অই", "ৈ"),
    "ai": ("এ", "ে"),
    "ay": ("এ", "ে"),
    "ei": ("এ", "ে"),
    "ey": ("এ", "ে"),
    "ie": ("ই", "ি"),
    "oa": ("ও", "ো"),
    "au": ("অ", "া"),
    "aw": ("অ", "া"),
    "ue": ("উ", "ু"),
    "ui": ("উ", "ু"),
    "a": ("অ", "া"),
    "e": ("এ", "ে"),
    "i": ("ই", "ি"),
    "o": ("ও", "ো"),
    "u": ("আ", "া"),
}

# Consonant digraphs, again longest-first: "sch" before "sh" before "s".
CONSONANTS = {
    "tch": "চ",
    "sch": "স্ক",
    "sh": "শ",
    "ch": "চ",
    "ph": "ফ",
    "th": "থ",
    "gh": "গ",
    "ck": "ক",
    "kh": "খ",
    "wh": "ও",
    "qu": "কু",
    "ng": "ং",
    "nk": "ঙ্ক",
    "b": "ব",
    "c": "ক",
    "d": "ড",
    "f": "ফ",
    "g": "গ",
    "h": "হ",
    "j": "জ",
    "k": "ক",
    "l": "ল",
    "m": "ম",
    "n": "ন",
    "p": "প",
    "q": "ক",
    "r": "র",
    "s": "স",
    "t": "ট",
    "v": "ভ",
    "w": "ওয়",
    "x": "ক্স",
    "y": "য়",
    "z": "জ",
}

_HASANTA = "্"

_VOWEL_KEYS = sorted(VOWELS, key=len, reverse=True)
_CONSONANT_KEYS = sorted(CONSONANTS, key=len, reverse=True)

_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*", re.ASCII)


def _units(word):
    """Split a word into ('V'|'C', text) units, longest match first."""
    out = []
    i = 0
    while i < len(word):
        if word[i] == "\x00":
            out.append(("V", "\x00"))
            i += 1
            continue
        for key in _VOWEL_KEYS:
            if word.startswith(key, i):
                out.append(("V", key))
                i += len(key)
                break
        else:
            for key in _CONSONANT_KEYS:
                if word.startswith(key, i):
                    out.append(("C", key))
                    i += len(key)
                    break
            else:
                i += 1
    return out


# English writes a doubled consonant where it says a single one. Left alone,
# each half took a hasanta and "wallet" came out "ওাল্লেট" -- a cluster no
# reader would say. Collapsed before anything else looks at the word.
_DOUBLED = re.compile(r"([bcdfglmnprstz])\1", re.ASCII)

# "c" is "s" before e, i or y and "k" everywhere else, which is why an
# untreated "service" came out "সের্ভিক্".
_SOFT_C = re.compile(r"c(?=[eiy])", re.ASCII)

# A silent final "e" does not sound; it lengthens the vowel before it.
# "state" is স্টেট and "mobile" is মোবাইল, so the vowel is rewritten rather
# than the "e" simply dropped.
_MAGIC_E = {
    "a": ("এ", "ে"),
    "i": ("আই", "াই"),
    "y": ("আই", "াই"),
    "o": ("ও", "ো"),
    "u": ("ইউ", "িউ"),
}
_MAGIC = re.compile(r"([aiouy])([bcdfgklmnprstvz])e$", re.ASCII)

# "-er" and a final "y" are frequent enough to be worth naming: প্রিন্টার,
# not প্রিন্টের, and ভেরিফি, not ভেরিফ্য়্.
_FINAL_ER = re.compile(r"er$", re.ASCII)

# "or" before a consonant is the vowel in "word", not in "or": পাসওয়ার্ড and
# নেটওয়ার্ক, never পাসওয়োর্ড.
_OR = re.compile(r"or(?=[bcdfgklmnpqrstvz])", re.ASCII)

# English keeps a handful of endings whose spelling says nothing about how
# they sound, and they are common enough in this domain -- option, service,
# picture, available -- to be worth naming outright. Rewritten to spellings
# the rules below already read correctly, before the silent-e rule can take
# "service" for a magic-e word and make it "সের্ভাইস".
# Given in Bengali rather than as a respelling: routing them back through
# English spelling only fed the wrong vowels in again, and "option" came out
# "ওপ্শোন" where the ending is simply শন.
_ENDINGS = [
    ("tion", "শন"),
    ("sion", "শন"),
    ("ture", "চার"),
    ("ance", "েন্স"),
    ("ence", "েন্স"),
    ("ice", "িস"),
    ("age", "েজ"),
    ("ble", "বল"),
    ("ous", "াস"),
    ("ing", "িং"),
]

# "ow" closing a word is the vowel in "low"; before a consonant it is the one
# in "download". Only the second is rewritten.
_OW = re.compile(r"ow(?=[bcdfgklmnpqrstvz])", re.ASCII)
_FINAL_Y = re.compile(r"(?<=[^aeiou])y$", re.ASCII)


def transliterate_word(word: str) -> str:
    """Spell one English word with Bengali letters."""
    lowered = word.lower().replace("'", "").replace("\u2019", "")
    for ending, bengali in _ENDINGS:
        if len(lowered) > len(ending) + 1 and lowered.endswith(ending):
            return transliterate_word(lowered[: -len(ending)]) + bengali

    lowered = _DOUBLED.sub(r"\1", lowered)
    lowered = _SOFT_C.sub("s", lowered)
    lowered = _OR.sub("ar", lowered)
    lowered = _OW.sub("ou", lowered)

    magic = _MAGIC.search(lowered)
    if magic and len(lowered) > 3:
        lowered = lowered[: magic.start()] + "\x00" + magic.group(2)
        magic_vowel = _MAGIC_E[_MAGIC.search(word.lower().replace("'", "")).group(1)]
    else:
        magic_vowel = None
        if len(lowered) > 3 and lowered.endswith("e") and lowered[-2] not in VOWELS:
            lowered = lowered[:-1]

    if magic_vowel is None:
        lowered = _FINAL_Y.sub("i", lowered)
        lowered = _FINAL_ER.sub("ar", lowered)

    units = _units(lowered)
    out = []
    for index, (kind, text) in enumerate(units):
        if text == "\x00":
            standalone, sign = magic_vowel
            out.append(sign if index and units[index - 1][0] == "C" else standalone)
            continue
        if kind == "V":
            standalone, sign = VOWELS[text]
            # A vowel sign needs a consonant to hang on; at the start of a
            # word, or straight after another vowel, there is none.
            out.append(sign if index and units[index - 1][0] == "C" else standalone)
            continue

        letter = CONSONANTS[text]
        out.append(letter)
        # The inherent vowel has to be suppressed when the next unit is
        # another consonant, and at the end of the word -- otherwise every
        # English word acquires a trailing "অ" and "start" becomes "স্টারটো".
        nxt = units[index + 1] if index + 1 < len(units) else None
        opens_syllable = nxt is not None and CONSONANTS.get(nxt[1]) in ("ওয়", "য়")
        if letter != "ং" and nxt is not None and nxt[0] == "C" and not opens_syllable:
            out.append(_HASANTA)
    return "".join(out)


def transliterate(text: str) -> str:
    """Spell every remaining Latin word in a string with Bengali letters."""
    return _LATIN_WORD.sub(lambda m: transliterate_word(m.group(0)), text)
