"""Latin script, turned into something a Bangla voice can say.

Three kinds of Latin reach the voice. Terms in SPOKEN_TERMS have a real
Bengali rendering and get it. Initialisms absent from that table are spelt
letter by letter. Anything remaining is an English word with no useful
spoken form, and is dropped.

SPOKEN_TERMS is derived from the knowledge base rather than guessed: its
1379 answers contain 256 distinct Latin tokens. Patterns are built
longest-first, so "Apple App Store" is never consumed by "App Store" or
"Apple" and the order of the table itself does not matter. The initialisms
listed explicitly are there because spelling them would give "এন আই ডি"
where "এনআইডি" is the word in use.
"""

import re

from src.speech.transform.common import SENTENCE_SPLIT, has_bengali
from src.speech.transform.numbers import BN_TWO_DIGIT
from src.speech.transform.translit import transliterate

SPOKEN_TERMS = {
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
    "Return Envelope": "রিটার্ন এনভেলপ",
    "Postal Ballot": "পোস্টাল ব্যালট",
    "Declaration": "ডিক্লারেশন",
    "Envelope": "এনভেলপ",
    "Ballot": "ব্যালট",
    "Surname": "সারনেম",
    "Given": "গিভেন",
    "Vote": "ভোট",
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

# Everything below closes the gaps an audit of all 1379 answers turned up:
# tokens that reached the voice as nothing at all, or as spelt letters where a
# word exists. They matter more now than they did, because the reply is read
# down a phone line where there is no screen to fall back on.
#
# "No" is the address abbreviation, not the English "no" -- it is never the
# latter anywhere in the knowledge base. "Act No" is listed as a phrase so the
# legal citations read "আইন নম্বর", while a bare "ACT" stays the Australian
# territory and is spelt, which is what an address wants.
SPOKEN_TERMS.update(
    {
        # Address abbreviations. Left without their trailing dots: the
        # patterns are \b-anchored, and a \b will not follow a full stop.
        "Miami hosts foreign country consulates and a US Department of State "
        "Office of Foreign Missions": "মায়ামিতে বিদেশি কনস্যুলেট এবং "
        "যুক্তরাষ্ট্রের পররাষ্ট্র দপ্তরের অফিস অব ফরেন মিশনস",
        # English function words carry nothing into a Bengali sentence, and
        # now that the fallback spells rather than deletes, leaving them out
        # has to be said explicitly -- otherwise "The Embassy of Bangladesh"
        # opens with a spelt-out "থে".
        "the": "",
        "of": "",
        "and": "",
        "in": "",
        "at": "",
        "for": "",
        "a": "",
        "an": "",
        "Act No": "আইন নম্বর",
        "PO Box": "পোস্ট অফিস বক্স",
        "PO": "পি ও",
        "No": "নম্বর",
        "St": "স্ট্রিট",
        "Ln": "লেন",
        "Rd": "রোড",
        "Blvd": "বুলেভার্ড",
        "Apt": "অ্যাপার্টমেন্ট",
        # Countries and regions written as initials.
        "USA": "ইউএসএ",
        "NSW": "নিউ সাউথ ওয়েলস",
        "DC": "ডিসি",
        "Diplomatic": "ডিপ্লোম্যাটিক",
        "foreign": "বিদেশি",
        "NW": "নর্থ ওয়েস্ট",
        "FL": "ফ্লোরিডা",
        "CA": "ক্যালিফোর্নিয়া",
        "ON": "অন্টারিও",
        # Initialisms with an established spoken shape.
        "AFIS": "এএফআইএস",
        "NIDFN": "এনআইডিএফএন",
        "MPO": "এমপিও",
        "FAQ": "এফএকিউ",
        "OFM": "ওএফএম",
        "HQ": "এইচকিউ",
        "ecs": "ইসিএস",
        # Roman numerals, which spell as letters otherwise.
        "XIX": "ঊনিশ",
        "II": "দুই",
        # Place names from the overseas mission addresses.
        "Al-Sadu": "আল সাদু",
        "Al-Nazlah": "আল নাজলাহ",
        "Al-Sharqiyah": "আল শারকিয়াহ",
        "Al Khalil": "আল খলিল",
        "dell'Antartide": "দেল আন্তার্তিদে",
        "O'Malley": "ও ম্যালি",
        "Atria": "অ্যাট্রিয়া",
        "Miami": "মায়ামি",
        "Deira": "দেইরা",
        "Dubai": "দুবাই",
        # Ordinary words that were being dropped mid-sentence.
        "password": "পাসওয়ার্ড",
        "optional": "ঐচ্ছিক",
        "service": "সার্ভিস",
        "name": "নেম",
        "Act": "আইন",
    }
)

SPOKEN_LATIN = [
    (
        re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE | re.ASCII),
        spoken,
    )
    for term, spoken in sorted(
        SPOKEN_TERMS.items(), key=lambda kv: len(kv[0]), reverse=True
    )
]

LATIN_LETTER_BN = {
    "a": "এ", "b": "বি", "c": "সি", "d": "ডি", "e": "ই", "f": "এফ",
    "g": "জি", "h": "এইচ", "i": "আই", "j": "জে", "k": "কে", "l": "এল",
    "m": "এম", "n": "এন", "o": "ও", "p": "পি", "q": "কিউ", "r": "আর",
    "s": "এস", "t": "টি", "u": "ইউ", "v": "ভি", "w": "ডব্লিউ",
    "x": "এক্স", "y": "ওয়াই", "z": "জেড",
}


def spell_latin(token: str) -> str:
    """Say a Latin run one letter at a time, the way a Bangla speaker reads an
    unfamiliar initialism aloud."""
    return " ".join(LATIN_LETTER_BN[c] for c in token.lower() if c in LATIN_LETTER_BN)

# "Plot No. 5" ends a sentence as far as any splitter is concerned, and that
# is the damage: the address is cut in two, and the tail -- still mostly Latin
# at that point -- is then dropped whole by the rule below. The citizen is read
# half a street address and no city. So the dot is taken off the handful of
# abbreviations that carry one, before sentence splitting ever happens.
_ABBREV_DOT = re.compile(
    r"\b(No|St|Rd|Ln|Ave|Blvd|Apt|Mr|Mrs|Ms|Dr|Jr|Sr|vs|etc)\.", re.ASCII
)


# "P.O.", "U.S.A." and "D.C." are the same problem wearing dots inside as well
# as at the end. Collapsed to bare initialisms here, they reach the table below
# as "PO", "USA" and "DC" and are spoken; left alone, each interior dot was one
# more false sentence end, and "P.O. No. 8" was read as a lone ". নম্বর আট".
_DOTTED_INITIALS = re.compile(r"\b(?:[A-Za-z]\.){2,}", re.ASCII)


def strip_abbrev_dots(text: str) -> str:
    """Drop full stops that abbreviate rather than end a sentence."""
    out = _DOTTED_INITIALS.sub(lambda m: m.group(0).replace(".", ""), text)
    return _ABBREV_DOT.sub(r"\1", out)


# A postcode is neither a word nor a quantity, and reading it as either
# destroys it. "SW7 5JA" met the number stage first, which turned 7 and 5 into
# quantities and left "এস ডব্লিউসাত পাঁচজে এ" -- the letters welded onto the
# digits and the grouping gone. Canada's "K1R 7S8" came out "এক সাতআট", having
# lost three letters outright.
#
# So a run that mixes capitals and digits is spelt character by character
# before anything else can claim it: letters as letters, digits as digits,
# spaced so a listener can write them down. Requiring both a capital and a
# digit is what keeps it off plain numbers ("2606") and plain initialisms
# ("XMM"), which the stages below already handle.
_ALNUM_CODE = re.compile(r"\b(?=[A-Z\d]*[A-Z])(?=[A-Z\d]*\d)[A-Z\d]{2,8}\b", re.ASCII)


def spell_code(token: str) -> str:
    """Say a postcode-like run one character at a time."""
    return " ".join(
        BN_TWO_DIGIT[int(c)] if c.isdigit() else LATIN_LETTER_BN[c.lower()]
        for c in token
        if c.isdigit() or c.lower() in LATIN_LETTER_BN
    )


def codes_for_speech(text: str) -> str:
    """Spell out postcodes and similar letter-and-digit runs."""
    return _ALNUM_CODE.sub(lambda m: spell_code(m.group(0)), text)


def spoken_latin(text: str) -> str:
    if not has_bengali(text):
        return text
    for pattern, word in SPOKEN_LATIN:
        text = pattern.sub(word, text)
    return text

# Script other than Bengali or Latin also reaches the voice: a reply came back
# with the Arabic "مراجعه" dropped into a Bengali sentence. There is no useful
# spoken form for it, so it goes the way an English word does.
#
# The exclusions are not optional. The daṛi is U+0964, which lives in the
# Devanagari block rather than the Bengali one, so a plain "not Bengali" rule
# deletes every sentence ending in the corpus. ZWNJ and ZWJ are outside the
# block too and do real work in Bengali conjuncts.
# Dashes are excluded because they separate words rather than being words:
# deleting the em dash in "সংযুক্ত—এটি" welds two words into one. They are
# turned into a pause by the punctuation stage instead.
_FOREIGN_RUN = re.compile(
    r"[^\s\x00-\x7F\u0980-\u09FF\u0964\u0965\u200C\u200D\u2013-\u2015]+"
)

_ACRONYM = re.compile(r"\b[A-Z]{2,6}\b", re.ASCII)
_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z'\-]*(?:\.[A-Za-z]+)*", re.ASCII)


_SENTENCE_LATIN_LIMIT = 0.30


def _foreign_share(sentence: str) -> float:
    """Share of a sentence's letters that a Bangla voice cannot say."""
    letters = [c for c in sentence if c.isalpha()]
    if not letters:
        return 0.0
    foreign = sum(1 for c in letters if not ("\u0980" <= c <= "\u09FF"))
    return foreign / len(letters)


def latin_for_speech(text: str) -> str:
    """Spell initialisms and write every remaining English word in Bengali.

    The caller decides this is a Bengali reply; an English answer to an
    English question keeps its English.

    Nothing English is dropped any more. This used to spell the initialisms,
    delete every other Latin word, and throw away whole sentences that were
    still more than _SENTENCE_LATIN_LIMIT Latin afterwards -- on the grounds
    that half an overseas address reads as an answer without being one, and
    a listener who needed it had it on screen. Read down a phone line there
    is no screen, and deletion is the one outcome a caller cannot recover
    from: they never learn a word was missing. So the remainder is spelt in
    Bengali letters instead, and the sentence is kept.

    Script that is neither Latin nor Bengali is still removed. An Arabic run
    dropped into a Bengali reply has no Bengali spelling to give it, and
    transliterating it would mean inventing one.
    """
    out = []
    for sentence in SENTENCE_SPLIT.split(text):
        if not sentence:
            continue
        spelled = _ACRONYM.sub(lambda m: spell_latin(m.group(0)), sentence)
        out.append(_FOREIGN_RUN.sub("", transliterate(spelled)))
    return "".join(out)
