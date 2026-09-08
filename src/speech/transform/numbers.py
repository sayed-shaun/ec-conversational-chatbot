"""Numbers as a voice says them.

Bangla is not built like English here: it has a distinct word for every number
up to ninety-nine rather than composing tens plus ones, and it groups large
numbers as crore/lakh/thousand instead of thousands. Both need lookup tables.

The model is deliberately left free to write digits. Asking it to spell numbers
out itself was tried and reverted: it gets the VALUE right with digits, but
occasionally emits non-Bangla fragments when spelling tricky numbers as words.
Converting here is deterministic -- same input, same output, no model involved.
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


def numbers_for_speech(text: str, bengali: bool = True) -> str:
    """Every digit run said the way its role demands.

    Order is from most specific to least. An ordinal suffix, a helpline label
    or a six-digit run each identify what a number IS, and each wants a
    different reading; whatever is left over is a plain magnitude -- a fee, an
    age, a year.

    `bengali` says which language the reply is in. An English answer keeps its
    digits, since the Bangla magnitude words would otherwise drop "দুইশ ত্রিশ"
    into the middle of an English sentence.
    """
    out = text

    out = _DATE_ORDINAL.sub(
        lambda m: bangla_date_ordinal(int(normalize_digits(m.group(1))), m.group(2)),
        out,
    )
    out = _ORDINAL.sub(lambda m: bangla_ordinal(int(normalize_digits(m.group(1)))), out)
    out = _EN_ORDINAL.sub(lambda m: english_ordinal(int(m.group(1))), out)

    # Said digit by digit: a helpline or an ID is dictation, not a quantity.
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

    # Whatever plain digit runs remain: read as a magnitude.
    if bengali:
        out = _ANY_NUMBER.sub(
            lambda m: number_to_bangla_words(int(normalize_digits(m.group(0)))), out
        )
    return out
