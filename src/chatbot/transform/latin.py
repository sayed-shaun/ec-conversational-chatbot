"""Latin script, turned into something a Bangla voice can say.

Three kinds of Latin reach the voice. Terms in SPOKEN_TERMS have a real Bengali
rendering and get it. Initialisms not in that table are spelt letter by letter,
the way a Bangla speaker reads an unfamiliar one aloud. Anything left is an
English word with no useful spoken form, and it is dropped.
"""

import re

from src.chatbot.transform.common import SENTENCE_SPLIT, has_bengali

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

def spoken_latin(text: str) -> str:
    # Only for a Bengali reply: an English answer to an English question is
    # meant to stay English. Presence, not majority -- "Google Play Store থেকে
    # NID Wallet অ্যাপ" has more Latin letters than Bengali and is still Bengali.
    if not has_bengali(text):
        return text
    for pattern, word in SPOKEN_LATIN:
        text = pattern.sub(word, text)
    return text

_ACRONYM = re.compile(r"\b[A-Z]{2,6}\b", re.ASCII)
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
    for sentence in SENTENCE_SPLIT.split(text):
        if not sentence:
            continue
        spelled = _ACRONYM.sub(lambda m: spell_latin(m.group(0)), sentence)
        if _latin_share(spelled) >= _SENTENCE_LATIN_LIMIT:
            continue
        kept.append(_LATIN_RUN.sub("", spelled))
    return "".join(kept)
