"""Turning a reply into something a Bangla voice can read aloud.

Markdown removed, addresses shortened, Latin initialisms respelled and every
digit turned into Bangla words. Ported from the browser, where it used to run
before each TTS request -- which meant the /tts endpoint only behaved for one
particular client, and this logic had nowhere to be tested.

The model is deliberately left free to write digits. Asking it to spell numbers
out itself was tried and reverted: it gets the VALUE right with digits, but
occasionally emits non-Bangla fragments when spelling tricky numbers as words.
Converting here is deterministic -- same input, same output, no model involved.

A note on word boundaries, because it is the one thing that does not survive a
straight port. JavaScript's \\b is ASCII-only, so it sees a boundary between a
Bengali letter and "NID". Python's \\b is Unicode-aware and does not, since
Bengali letters are word characters to it -- so `\\bNID\\b` silently stops
matching in exactly the sentences this exists for. Every pattern that needs
JavaScript's meaning is compiled with re.ASCII.
"""

import re

BN_DIGITS = "০১২৩৪৫৬৭৮৯"
_BN_TO_EN = {ord(c): str(i) for i, c in enumerate(BN_DIGITS)}


def normalize_digits(text: str) -> str:
    return text.translate(_BN_TO_EN)


# Bangla has a distinct word for every number 0-99 (not composed from tens plus
# ones like English), so this has to be a full lookup table.
BN_TWO_DIGIT = [
    "শূন্য",
    "এক",
    "দুই",
    "তিন",
    "চার",
    "পাঁচ",
    "ছয়",
    "সাত",
    "আট",
    "নয়",
    "দশ",
    "এগারো",
    "বারো",
    "তেরো",
    "চৌদ্দ",
    "পনেরো",
    "ষোলো",
    "সতেরো",
    "আঠারো",
    "উনিশ",
    "বিশ",
    "একুশ",
    "বাইশ",
    "তেইশ",
    "চব্বিশ",
    "পঁচিশ",
    "ছাব্বিশ",
    "সাতাশ",
    "আটাশ",
    "ঊনত্রিশ",
    "ত্রিশ",
    "একত্রিশ",
    "বত্রিশ",
    "তেত্রিশ",
    "চৌত্রিশ",
    "পঁয়ত্রিশ",
    "ছত্রিশ",
    "সাঁইত্রিশ",
    "আটত্রিশ",
    "ঊনচল্লিশ",
    "চল্লিশ",
    "একচল্লিশ",
    "বিয়াল্লিশ",
    "তেতাল্লিশ",
    "চুয়াল্লিশ",
    "পঁয়তাল্লিশ",
    "ছেচল্লিশ",
    "সাতচল্লিশ",
    "আটচল্লিশ",
    "ঊনপঞ্চাশ",
    "পঞ্চাশ",
    "একান্ন",
    "বাহান্ন",
    "তিপ্পান্ন",
    "চুয়ান্ন",
    "পঞ্চান্ন",
    "ছাপ্পান্ন",
    "সাতান্ন",
    "আটান্ন",
    "ঊনষাট",
    "ষাট",
    "একষট্টি",
    "বাষট্টি",
    "তেষট্টি",
    "চৌষট্টি",
    "পঁয়ষট্টি",
    "ছেষট্টি",
    "সাতষট্টি",
    "আটষট্টি",
    "ঊনসত্তর",
    "সত্তর",
    "একাত্তর",
    "বাহাত্তর",
    "তিয়াত্তর",
    "চুয়াত্তর",
    "পঁচাত্তর",
    "ছিয়াত্তর",
    "সাতাত্তর",
    "আটাত্তর",
    "ঊনআশি",
    "আশি",
    "একাশি",
    "বিরাশি",
    "তিরাশি",
    "চুরাশি",
    "পঁচাশি",
    "ছিয়াশি",
    "সাতাশি",
    "আটাশি",
    "ঊননব্বই",
    "নব্বই",
    "একানব্বই",
    "বিরানব্বই",
    "তিরানব্বই",
    "চুরানব্বই",
    "পঁচানব্বই",
    "ছিয়ানব্বই",
    "সাতানব্বই",
    "আটানব্বই",
    "নিরানব্বই",
]


def bangla_hundreds(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    out = ""
    if hundreds:
        out += BN_TWO_DIGIT[hundreds] + "শ" + (" " if rest else "")
    if rest:
        out += BN_TWO_DIGIT[rest]
    return out.strip()


def number_to_bangla_words(n: int) -> str:
    """Bangla groups digits as crore/lakh/thousand/hundred, not thousands."""
    if n == 0:
        return "শূন্য"
    if n < 0:
        return "ঋণাত্মক " + number_to_bangla_words(-n)
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1_000)
    if crore:
        parts.append(BN_TWO_DIGIT[crore] + " কোটি")
    if lakh:
        parts.append(BN_TWO_DIGIT[lakh] + " লক্ষ")
    if thousand:
        parts.append(BN_TWO_DIGIT[thousand] + " হাজার")
    if n:
        parts.append(bangla_hundreds(n))
    return " ".join(parts).strip()


BN_ORDINAL = [
    "",
    "প্রথম",
    "দ্বিতীয়",
    "তৃতীয়",
    "চতুর্থ",
    "পঞ্চম",
    "ষষ্ঠ",
    "সপ্তম",
    "অষ্টম",
    "নবম",
    "দশম",
    "একাদশ",
    "দ্বাদশ",
    "ত্রয়োদশ",
    "চতুর্দশ",
    "পঞ্চদশ",
    "ষোড়শ",
    "সপ্তদশ",
    "অষ্টাদশ",
    "ঊনবিংশ",
    "বিংশ",
]


def bangla_ordinal(n: int) -> str:
    if 1 <= n < len(BN_ORDINAL):
        return BN_ORDINAL[n]
    return number_to_bangla_words(n) + "তম"


# Days of the month: 1st-4th are irregular idioms, 5th onward is regular
# (cardinal word plus whichever suffix the source text already used).
BN_DATE_SPECIAL = {1: "পয়লা", 2: "দোসরা", 3: "তেসরা", 4: "চৌঠা"}


def bangla_date_ordinal(n: int, suffix: str) -> str:
    if n in BN_DATE_SPECIAL:
        return BN_DATE_SPECIAL[n]
    word = number_to_bangla_words(n)
    # পঁচিশ + শে would double the শ; the real word elides it to পঁচিশে.
    if suffix == "শে" and word.endswith("শ"):
        return word + "ে"
    return word + suffix


EN_ORDINAL = [
    "",
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
    "thirteenth",
    "fourteenth",
    "fifteenth",
    "sixteenth",
    "seventeenth",
    "eighteenth",
    "nineteenth",
    "twentieth",
]


def english_ordinal(n: int) -> str:
    if 1 <= n < len(EN_ORDINAL):
        return EN_ORDINAL[n]
    return f"{n}th"


def digit_by_digit(digits: str) -> str:
    """Helpline and ID numbers: said as digits, not as a magnitude."""
    return " ".join(BN_TWO_DIGIT[int(d)] for d in normalize_digits(digits))


EN_DIGIT_WORDS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
]


def digit_by_digit_english(digits: str) -> str:
    return " ".join(EN_DIGIT_WORDS[int(d)] for d in digits)


_URL = re.compile(
    r"(?:https?://)?\b([a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z]{2,})+)(?:/[^\s,।;)]*)?",
    re.ASCII,
)
_KNOWN_DOMAIN = re.compile(r"services\.nidw\.gov\.bd", re.IGNORECASE | re.ASCII)
_DOMAIN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z]{2,})+\b", re.ASCII)
_DATE_ORDINAL = re.compile(r"([০-৯]+|\d+)(লা|রা|শে|ঠা|ই)")
_ORDINAL = re.compile(r"([০-৯]+|\d+)(ম|য়|র্থ|ষ্ঠ)")
_EN_ORDINAL = re.compile(r"\b(\d+)(st|nd|rd|th)\b", re.IGNORECASE | re.ASCII)
_LONG_RUN = re.compile(r"[০-৯]{6,}|\d{6,}")
_LABEL_THEN_NUM = re.compile(
    r"(নম্বর|নম্বরে|নম্বরটি|কল করে|কল করুন|হেল্পলাইন|হটলাইন)\s*([০-৯]+|\d+)"
)
_NUM_THEN_LABEL = re.compile(r"([০-৯]+|\d+)\s*(নম্বরে|নম্বরটি|নম্বর)")
_EN_LABEL_THEN_NUM = re.compile(
    r"\b(call|number|helpline|hotline|dial)\b\s*:?\s*([0-9]+)",
    re.IGNORECASE | re.ASCII,
)
_EN_NUM_BEFORE_LABEL = re.compile(
    r"\b([0-9]+)\s*(?=is the (?:number|helpline|hotline))",
    re.IGNORECASE | re.ASCII,
)
_ANY_NUMBER = re.compile(r"[০-৯]+|\d+")


def numbers_for_speech(text: str) -> str:
    out = text

    # A spoken address is only useful as far as the domain. Reading a path out
    # -- "slash n i d dash pub slash fees" -- tells a listener nothing they can
    # act on, and the path is where Latin letters survive everything below.
    out = _URL.sub(lambda m: m.group(1), out)

    out = _KNOWN_DOMAIN.sub("সার্ভিসেস ডট এনআইডিডাব্লিউ ডট গভ ডট বিডি", out)
    # Any other domain: break it on the dots so it is not one run-on word.
    out = _DOMAIN.sub(lambda m: " ডট ".join(m.group(0).split(".")), out)

    out = _DATE_ORDINAL.sub(
        lambda m: bangla_date_ordinal(int(normalize_digits(m.group(1))), m.group(2)),
        out,
    )
    out = _ORDINAL.sub(lambda m: bangla_ordinal(int(normalize_digits(m.group(1)))), out)
    out = _EN_ORDINAL.sub(lambda m: english_ordinal(int(m.group(1))), out)

    out = _LONG_RUN.sub(lambda m: digit_by_digit(m.group(0)), out)
    out = _LABEL_THEN_NUM.sub(
        lambda m: m.group(1) + " " + digit_by_digit(m.group(2)), out
    )
    out = _NUM_THEN_LABEL.sub(
        lambda m: digit_by_digit(m.group(1)) + " " + m.group(2), out
    )
    out = _EN_LABEL_THEN_NUM.sub(
        lambda m: m.group(1) + " " + digit_by_digit_english(m.group(2)), out
    )
    out = _EN_NUM_BEFORE_LABEL.sub(
        lambda m: digit_by_digit_english(m.group(1)) + " ", out
    )

    # Whatever plain digit runs remain: read as a magnitude (fees, ages, years).
    out = _ANY_NUMBER.sub(
        lambda m: number_to_bangla_words(int(normalize_digits(m.group(0)))), out
    )
    return out


# Latin that reaches the voice anyway. The prompt tells the model not to write
# English or initialisms, but an initialism copied out of a tool result gets
# past it, and some proper nouns are simply written in Latin in the knowledge
# base. Taken from the data rather than guessed: the Latin present across the
# 1379 answers is initialisms, the service domain, and a few names.
SPOKEN_LATIN = [
    (re.compile(r"\bNID\b", re.IGNORECASE | re.ASCII), "এনআইডি"),
    (re.compile(r"\bOTP\b", re.IGNORECASE | re.ASCII), "ওটিপি"),
    (re.compile(r"\bSMS\b", re.IGNORECASE | re.ASCII), "এসএমএস"),
    (re.compile(r"\bQR\b", re.IGNORECASE | re.ASCII), "কিউআর"),
    (re.compile(r"\bPDF\b", re.IGNORECASE | re.ASCII), "পিডিএফ"),
    (re.compile(r"\bBD\b", re.ASCII), "বিডি"),
    (re.compile(r"\bEC\b", re.ASCII), "ইসি"),
    (re.compile(r"\bID\b", re.ASCII), "আইডি"),
    (
        re.compile(r"\bGoogle\s*Play\s*Store\b", re.IGNORECASE | re.ASCII),
        "গুগল প্লে স্টোর",
    ),
    (re.compile(r"\bPlay\s*Store\b", re.IGNORECASE | re.ASCII), "প্লে স্টোর"),
    (re.compile(r"\bGoogle\b", re.IGNORECASE | re.ASCII), "গুগল"),
    (re.compile(r"\bWallet\b", re.IGNORECASE | re.ASCII), "ওয়ালেট"),
    (re.compile(r"\bBangladesh\b", re.IGNORECASE | re.ASCII), "বাংলাদেশ"),
]

_HAS_BENGALI = re.compile(r"[ঀ-৿]")


def spoken_latin(text: str) -> str:
    # Only for a Bengali reply: an English answer to an English question is
    # meant to stay English. Presence, not majority -- "Google Play Store থেকে
    # NID Wallet অ্যাপ" has more Latin letters than Bengali and is still Bengali.
    if not _HAS_BENGALI.search(text):
        return text
    for pattern, word in SPOKEN_LATIN:
        text = pattern.sub(word, text)
    return text


_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MARKS = re.compile(r"[#*_>~]")
_SPACE = re.compile(r"\s+")


def strip_markdown(text: str) -> str:
    """Remove markdown so the voice does not read asterisks and hashes."""
    plain = _CODE_FENCE.sub(" ", text)
    plain = _INLINE_CODE.sub(r"\1", plain)
    plain = _IMAGE.sub(" ", plain)
    plain = _LINK.sub(r"\1", plain)
    plain = _MARKS.sub("", plain)
    return _SPACE.sub(" ", plain).strip()


def for_speech(text: str) -> str:
    """The whole pipeline: reply text in, something speakable out."""
    return spoken_latin(numbers_for_speech(strip_markdown(text)))
