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


# The one address in the knowledge base, said as a name rather than spelled
# out. "সার্ভিসেস ডট এনআইডিডাব্লিউ ডট গভ ডট বিডি" is thirteen syllables of
# dictation that nobody can act on by ear, and a listener who wants to type
# it is reading the on-screen reply anyway -- this transform only feeds TTS,
# so the visible text keeps the real URL.
SERVICE_SITE_BN = "এনআইডি সেবার ওয়েবসাইট"

_URL = re.compile(
    r"(?:https?://)?\b([a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z]{2,})+)(?:/[^\s,।;)]*)?",
    re.ASCII,
)
_KNOWN_DOMAIN = re.compile(
    r"(?:services\.)?nidw\.gov\.bd", re.IGNORECASE | re.ASCII
)
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


def numbers_for_speech(text: str, bengali: bool = True) -> str:
    """Addresses and numbers, said rather than shown.

    `bengali` says which language the reply is in. An English answer keeps its
    digits: the Bangla magnitude words below would otherwise put "দুইশ ত্রিশ"
    in the middle of an English sentence.
    """
    out = text

    # A spoken address is only useful as far as the domain. Reading a path out
    # -- "slash n i d dash pub slash fees" -- tells a listener nothing they can
    # act on, and the path is where Latin letters survive everything below.
    out = _URL.sub(lambda m: m.group(1), out)

    out = _KNOWN_DOMAIN.sub(SERVICE_SITE_BN, out)
    # Any other domain: break it on the dots so it is not one run-on word.
    out = _DOMAIN.sub(_spoken_domain, out)

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
    if bengali:
        out = _ANY_NUMBER.sub(
            lambda m: number_to_bangla_words(int(normalize_digits(m.group(0)))), out
        )
    return out


# Latin that reaches the voice anyway. The prompt tells the model not to write
# English or initialisms, but an initialism copied out of a tool result gets
# past it, and plenty of proper nouns are simply written in Latin in the
# knowledge base.
#
# Taken from the data, not guessed: the 1379 answers contain 256 distinct Latin
# tokens, and they sort into five kinds. Initialisms (AFIS, NOC, VPN) are spelt
# out letter by letter further down. Product and status names, address nouns and
# place names are listed here. URL fragments are handled by the address rules
# above. English function words ("of", "in", "the") are left to be dropped,
# since there is nothing useful to say in their place.
#
# Keys are matched longest-first, built below, so "Apple App Store" wins over
# "App Store" and that over "Apple" without the order here mattering.
SPOKEN_TERMS = {
    # products, apps, technology
    "Smart Election Management BD": "স্মার্ট ইলেকশন ম্যানেজমেন্ট বিডি",
    "Google Play Store": "গুগল প্লে স্টোর",
    "Google Playstore": "গুগল প্লে স্টোর",
    "Apple App Store": "অ্যাপল অ্যাপ স্টোর",
    "App Store": "অ্যাপ স্টোর",
    "Play Store": "প্লে স্টোর",
    "Playstore": "প্লে স্টোর",
    "NID Wallet": "এনআইডি ওয়ালেট",
    "QR Code": "কিউআর কোড",
    "Wi-Fi": "ওয়াই ফাই",
    "Android Phone": "অ্যান্ড্রয়েড ফোন",
    "Android": "অ্যান্ড্রয়েড",
    "iPhone": "আইফোন",
    "Apple": "অ্যাপল",
    "Google": "গুগল",
    "Wallet": "ওয়ালেট",
    "Edge": "এজ",
    "Phone": "ফোন",
    "Store": "স্টোর",
    # application status strings
    "Adjudication Pending": "অ্যাডজুডিকেশন পেন্ডিং",
    "Fingerprint Update": "ফিঙ্গারপ্রিন্ট আপডেট",
    "Fingrprint Update": "ফিঙ্গারপ্রিন্ট আপডেট",
    "Match Found": "ম্যাচ ফাউন্ড",
    "Fingerprint": "ফিঙ্গারপ্রিন্ট",
    "Fingrprint": "ফিঙ্গারপ্রিন্ট",
    "Adjudication": "অ্যাডজুডিকেশন",
    "Pending": "পেন্ডিং",
    "Match": "ম্যাচ",
    "Found": "ফাউন্ড",
    "Update": "আপডেট",
    "Done": "সম্পন্ন",
    # postal ballot vocabulary
    "Return Envelope": "রিটার্ন এনভেলপ",
    "Postal Ballot": "পোস্টাল ব্যালট",
    "Declaration": "ডিক্লারেশন",
    "Envelope": "এনভেলপ",
    "Ballot": "ব্যালট",
    "Surname": "সারনেম",
    "Given": "গিভেন",
    "Vote": "ভোট",
    # institutions
    "Bangladesh Election Commission": "বাংলাদেশ নির্বাচন কমিশন",
    "Bangladesh High Commission": "বাংলাদেশ হাই কমিশন",
    "Consulate General of Bangladesh": "বাংলাদেশ কনস্যুলেট জেনারেল",
    "Embassy of Bangladesh": "বাংলাদেশ দূতাবাস",
    "People's Republic of Bangladesh": "গণপ্রজাতন্ত্রী বাংলাদেশ",
    "Election Commission": "নির্বাচন কমিশন",
    "Consulate General": "কনস্যুলেট জেনারেল",
    "High Commission": "হাই কমিশন",
    "Diplomatic Missions": "কূটনৈতিক মিশন",
    "Foreign Missions": "বিদেশি মিশন",
    "Consulate": "কনস্যুলেট",
    "consulates": "কনস্যুলেট",
    "Commission": "কমিশন",
    "Embassy": "দূতাবাস",
    "Missions": "মিশন",
    "Election": "নির্বাচন",
    "Tribunals": "ট্রাইব্যুনাল",
    "Police": "পুলিশ",
    "Department": "ডিপার্টমেন্ট",
    "Training": "ট্রেনিং",
    "Assistant": "সহকারী",
    "Bangladesh": "বাংলাদেশ",
    # address nouns
    "Diplomatic Quarter": "ডিপ্লোম্যাটিক কোয়ার্টার",
    "Boulevard": "বুলেভার্ড",
    "Avenue": "অ্যাভিনিউ",
    "Building": "বিল্ডিং",
    "Quarter": "কোয়ার্টার",
    "Sunnyside": "সানিসাইড",
    "Southside": "সাউথসাইড",
    "Territory": "টেরিটরি",
    "Regional": "রিজিওনাল",
    "Circuit": "সার্কিট",
    "Street": "স্ট্রিট",
    "Centre": "সেন্টার",
    "Sector": "সেক্টর",
    "Suite": "স্যুট",
    "Villa": "ভিলা",
    "Floor": "ফ্লোর",
    "Drive": "ড্রাইভ",
    "Level": "লেভেল",
    "Block": "ব্লক",
    "Plot": "প্লট",
    "Zone": "জোন",
    "Area": "এরিয়া",
    "City": "সিটি",
    "Gate": "গেট",
    "Lot": "লট",
    "Way": "ওয়ে",
    "Ave": "অ্যাভিনিউ",
    "Box": "বক্স",
    "Office": "অফিস",
    "House": "হাউস",
    "Island": "আইল্যান্ড",
    "State": "স্টেট",
    "Federal": "ফেডারেল",
    "International": "ইন্টারন্যাশনাল",
    "Special": "স্পেশাল",
    "Postal": "পোস্টাল",
    "Form": "ফর্ম",
    "Code": "কোড",
    "Crimes": "ক্রাইমস",
    "Secret": "সিক্রেট",
    "Collaborators": "কোলাবরেটরস",
    # countries, cities
    "United Kingdom": "যুক্তরাজ্য",
    "United States": "যুক্তরাষ্ট্র",
    "South Africa": "দক্ষিণ আফ্রিকা",
    "Saudi Arabia": "সৌদি আরব",
    "Kuala Lumpur": "কুয়ালালামপুর",
    "Los Angeles": "লস অ্যাঞ্জেলেস",
    "Abu Dhabi": "আবুধাবি",
    "New York": "নিউ ইয়র্ক",
    "Washington": "ওয়াশিংটন",
    "Birmingham": "বার্মিংহাম",
    "Manchester": "ম্যানচেস্টার",
    "Hulhumale": "হুলহুমালে",
    "Australia": "অস্ট্রেলিয়া",
    "Malaysian": "মালয়েশিয়ান",
    "Malaysia": "মালয়েশিয়া",
    "Maldives": "মালদ্বীপ",
    "Sultanate": "সালতানাত",
    "Canberra": "ক্যানবেরা",
    "Pretoria": "প্রিটোরিয়া",
    "Fairfax": "ফেয়ারফ্যাক্স",
    "Droylsden": "ড্রয়েলসডেন",
    "Emirates": "আমিরাত",
    "Republic": "রিপাবলিক",
    "Toronto": "টরন্টো",
    "Ottawa": "অটোয়া",
    "Riyadh": "রিয়াদ",
    "Jeddah": "জেদ্দা",
    "Kuwait": "কুয়েত",
    "Muscat": "মাসকাট",
    "Sydney": "সিডনি",
    "Canada": "কানাডা",
    "Africa": "আফ্রিকা",
    "Arabia": "সৌদি আরব",
    "Queens": "কুইন্স",
    "Tokyo": "টোকিও",
    "Miami": "মায়ামি",
    "Milan": "মিলান",
    "Italy": "ইতালি",
    "Japan": "জাপান",
    "Qatar": "কাতার",
    "Dubai": "দুবাই",
    "Dhabi": "আবুধাবি",
    "Doha": "দোহা",
    "Oman": "ওমান",
    "Saudi": "সৌদি",
    "Kent": "কেন্ট",
    "Rome": "রোম",
    "Roma": "রোম",
    "York": "ইয়র্ক",
    "London": "লন্ডন",
    "Deira": "দেইরা",
    "Petra": "পেট্রা",
    "Qurum": "কুরুম",
    "Jalan": "জালান",
    "Sultan": "সুলতান",
    "Khalil": "খলিল",
    "Yahya": "ইয়াহিয়া",
    "Arab": "আরব",
    "Long": "লং",
    "New": "নিউ",
    "Los": "লস",
    "Abu": "আবু",
    "South": "দক্ষিণ",
    "North": "উত্তর",
    "United": "ইউনাইটেড",
    "English": "ইংরেজি",
    "General": "জেনারেল",
    "High": "হাই",
    "Via": "ভায়া",
    "Kuala": "কুয়ালা",
    "Lumpur": "লামপুর",
    "Angeles": "অ্যাঞ্জেলেস",
    "Sparks": "স্পার্কস",
    "Hurst": "হার্স্ট",
    "Sheppard": "শেপার্ড",
    "Farenden": "ফারেন্ডেন",
    "Giambellino": "জিয়ামবেলিনো",
    "Biscayne": "বিসকেইন",
    "Culgoa": "কুলগোয়া",
    "Chiyoda-ku": "চিয়োদা কু",
    "Kioicho": "কিওইচো",
    "Atria": "অ্যাট্রিয়া",
    "Messila": "মেসিলা",
    "Saadah": "সাআদাহ",
    "Dareen": "দারিন",
    "Jawwalah": "জাওয়ালাহ",
    "Nirolhu": "নিরোলহু",
    "Magu": "মাগু",
    "Shati": "শাতি",
    "Bab": "বাব",
    "Al": "আল",
}

# The initialisms that were already listed; kept explicit because spelling them
# letter by letter would say "এন আই ডি" where "এনআইডি" is the word people use.
SPOKEN_TERMS.update(
    {
        "NID": "এনআইডি",
        "OTP": "ওটিপি",
        "SMS": "এসএমএস",
        "QR": "কিউআর",
        "PDF": "পিডিএফ",
        "BD": "বিডি",
        "EC": "ইসি",
        "ID": "আইডি",
        "UAE": "সংযুক্ত আরব আমিরাত",
        "UK": "যুক্তরাজ্য",
        "VPN": "ভিপিএন",
        "GPS": "জিপিএস",
        "NOC": "এনওসি",
        "PC": "পিসি",
    }
)

# Longest first, so a phrase is never eaten by one of its own words.
SPOKEN_LATIN = [
    (
        re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE | re.ASCII),
        spoken,
    )
    for term, spoken in sorted(
        SPOKEN_TERMS.items(), key=lambda kv: len(kv[0]), reverse=True
    )
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
    """The whole pipeline: reply text in, something speakable out.

    Order matters. Markdown goes first so later rules see plain prose. Numbers
    and addresses next, while their Latin is still structured enough to
    recognise. Then the known-initialism table, which is more accurate than
    spelling letter by letter. Only then the catch-all for whatever Latin is
    left, and finally punctuation -- last, because the rules above emit commas
    and daṛis of their own.
    """
    # Decided up front, on the original: numbers_for_speech writes Bangla
    # number words, so asking "is this Bengali?" afterwards says yes for an
    # English reply containing a fee -- and the Latin rules would then delete
    # the answer.
    is_bengali = bool(_HAS_BENGALI.search(text or ""))

    out = strip_markdown(text)
    out = numbers_for_speech(out, bengali=is_bengali)
    if is_bengali:
        out = spoken_latin(out)
        out = latin_for_speech(out)
        out = dedupe_site_noun(out)
    return punctuation_for_speech(out)


# --- Latin that no lookup table will ever cover -------------------------------
#
# SPOKEN_LATIN above handles the initialisms that recur. The long tail does not
# look like that: it is English prose sitting inside the knowledge base --
# overseas embassy addresses ("High Commission of Bangladesh, Suite 12, ...")
# and internal status strings ("AFIS Match Found", "Pending Adjudication").
# Across the 1379 answers, 67 still contained Latin after the table ran, in 246
# distinct tokens. Adding them one by one is not a fix; the next dataset pull
# brings new ones.

LATIN_LETTER_BN = {
    "a": "এ", "b": "বি", "c": "সি", "d": "ডি", "e": "ই", "f": "এফ",
    "g": "জি", "h": "এইচ", "i": "আই", "j": "জে", "k": "কে", "l": "এল",
    "m": "এম", "n": "এন", "o": "ও", "p": "পি", "q": "কিউ", "r": "আর",
    "s": "এস", "t": "টি", "u": "ইউ", "v": "ভি", "w": "ডাব্লিউ",
    "x": "এক্স", "y": "ওয়াই", "z": "জেড",
}


def spell_latin(token: str) -> str:
    """Say a Latin run one letter at a time, the way a Bangla speaker reads an
    unfamiliar initialism aloud."""
    return " ".join(LATIN_LETTER_BN[c] for c in token.lower() if c in LATIN_LETTER_BN)


# Domain labels, so a bare nidw.gov.bd is not left half-translated. The known
# full address is handled earlier; this catches every other host, where the
# generic rule used to insert " ডট " between labels and leave the labels in
# Latin for the voice to trip over.
DOMAIN_LABEL_BN = {
    "www": "ডাব্লিউ ডাব্লিউ ডাব্লিউ",
    "nidw": "এনআইডিডাব্লিউ",
    "gov": "গভ",
    "bd": "বিডি",
    "com": "কম",
    "org": "অর্গ",
    "net": "নেট",
    "info": "ইনফো",
    "services": "সার্ভিসেস",
}


def _spoken_domain(match: re.Match) -> str:
    labels = match.group(0).split(".")
    return " ডট ".join(
        DOMAIN_LABEL_BN.get(part.lower(), spell_latin(part)) for part in labels
    )


# An all-caps run is an initialism, so spell it. Anything else -- mixed case or
# lower case -- is an English word, and a Bangla voice cannot say it. Dropping
# it is the lesser harm: a listener gets a shorter sentence instead of a burst
# of noise where a word should be.
_ACRONYM = re.compile(r"\b[A-Z]{2,6}\b", re.ASCII)
_SENTENCE_SPLIT_SPEECH = re.compile(r"(?<=[।.!?])")
_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z'\-]*(?:\.[A-Za-z]+)*", re.ASCII)


# A sentence built mostly out of English -- an overseas address is the case in
# the data -- cannot be rescued by deleting the English. Removing the Latin from
# "High Commission of Bangladesh, Suite 12, Kuala Lumpur" leaves "বাংলাদেশ,
# বারো," which sounds like an answer and is not one. Past this share of the
# letters, the whole sentence goes instead: a listener who needs the address is
# reading it on screen, where this transform never runs.
_SENTENCE_LATIN_LIMIT = 0.30


def _latin_share(sentence: str) -> float:
    letters = [c for c in sentence if c.isalpha()]
    if not letters:
        return 0.0
    latin = sum(1 for c in letters if c.isascii())
    return latin / len(letters)


def latin_for_speech(text: str) -> str:
    """Spell initialisms and remove the English a Bangla voice cannot say.

    Caller decides this is a Bengali reply; an English answer to an English
    question keeps its English.
    """
    kept = []
    for sentence in _SENTENCE_SPLIT_SPEECH.split(text):
        if not sentence:
            continue
        spelled = _ACRONYM.sub(lambda m: spell_latin(m.group(0)), sentence)
        if _latin_share(spelled) >= _SENTENCE_LATIN_LIMIT:
            continue
        kept.append(_LATIN_RUN.sub("", spelled))
    return "".join(kept)


# --- punctuation --------------------------------------------------------------
#
# A comma earns its place: the voice pauses on it. The rest is either read out
# as a word or swallowed as a glitch, so it goes. The slash is the one that
# changes meaning -- "উপজেলা/থানা" means "or", and that is how it should sound.
_SLASH_BETWEEN_WORDS = re.compile(r"(?<=\S)\s*/\s*(?=\S)")
_UNSPEAKABLE = re.compile(r"[()\[\]{}\"'“”‘’:;|<>+=*_~^\\@#$%&]")


# Substituting a name for the address can leave the noun stated twice, as in
# "এনআইডি সেবার ওয়েবসাইট ওয়েবসাইটে দেখুন", because the sentence already had one.
# The case ending is kept, not dropped: the sentence needs "ওয়েবসাইটে দেখুন",
# not "ওয়েবসাইট দেখুন". No \b here -- a Bengali vowel sign is a word character
# to Python, so a boundary assertion after it does not mean what it looks like.
_SITE_ECHO = re.compile(
    re.escape(SERVICE_SITE_BN) + r"\s+(?:ওয়েবসাইট|পোর্টাল|সাইট)((?:টিতে|টি|ে|য়ে)?)"
)


def dedupe_site_noun(text: str) -> str:
    """Collapse the doubled noun left by naming the site instead of spelling it."""
    return _SITE_ECHO.sub(lambda m: SERVICE_SITE_BN + m.group(1), text)


# A hyphen with a space on one side is left over from a dropped English word
# ("Al-Sadu Street" losing "Sadu"). A hyphen with no space around it is part of
# a Bengali compound -- রি-ইস্যু -- and must survive.
_ORPHAN_HYPHEN = re.compile(r"\s+-+|-+\s+")


def punctuation_for_speech(text: str) -> str:
    text = _SLASH_BETWEEN_WORDS.sub(" বা ", text)
    text = _ORPHAN_HYPHEN.sub(" ", text)
    text = _UNSPEAKABLE.sub(" ", text)
    # A sentence that lost its only content leaves a dangling daṛi behind.
    text = re.sub(r"\s+([।,?!])", r"\1", text)
    text = re.sub(r"([।,?!])\1+", r"\1", text)
    return _SPACE.sub(" ", text).strip()
