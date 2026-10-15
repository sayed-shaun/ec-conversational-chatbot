"""Web addresses, said as their parts.

A spoken address is only useful as far as the host: reading a path aloud
gives a listener nothing they can act on, and the path is where Latin
letters survive every other rule. The host is read label by label with
"ডট" between, so services.nidw.gov.bd is said "সার্ভিসেস ডট এনআইডব্লিউ ডট
গভ ডট বিডি". Only speech is affected; the on-screen reply keeps the real URL,
as this module runs on the way to TTS and nowhere else.

SERVICE_SITE_BN, KNOWN_DOMAIN and dedupe_site_noun are the older way: naming
that one address "এনআইডি সেবার ওয়েবসাইট" instead. Nothing applies them now.
"""

import re

from src.speech.transform.latin import spell_latin

SERVICE_SITE_BN = "এনআইডি সেবার ওয়েবসাইট"

DOMAIN_LABEL_BN = {
    "www": "ডাব্লিউ ডাব্লিউ ডাব্লিউ",
    "nidw": "এনআইডব্লিউ",
    "gov": "গভ",
    "bd": "বিডি",
    "com": "কম",
    "org": "অর্গ",
    "net": "নেট",
    "info": "ইনফো",
    "services": "সার্ভিসেস",
}

URL = re.compile(
    r"(?:https?://)?\b([a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z]{2,})+)(?:/[^\s,।;)]*)?",
    re.ASCII,
)
KNOWN_DOMAIN = re.compile(r"(?:services\.)?nidw\.gov\.bd", re.IGNORECASE | re.ASCII)
DOMAIN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z]{2,})+\b", re.ASCII)


# A model does not always write a host contiguously: "services. nidw. gov. bd"
# has been observed in replies where the knowledge base holds
# services.nidw.gov.bd. Every pattern below needs the labels joined, so a
# spaced host matched nothing, and the Latin stage then dropped the labels one
# by one and left the voice saying only the last of them.
#
# The repair is deliberately narrow, because a dot followed by a space is also
# what the end of a sentence looks like. All labels must be lowercase ASCII,
# there must be at least two separators, and the last label must be a TLD from
# this list -- anchoring on a real TLD is what keeps "e.g. this and that" and
# "the fee. then. wait" from being welded into a hostname. A host ending in
# some other TLD is simply left as it was, which is the behaviour before this
# repair existed.
TLDS = "bd|com|org|net|gov|edu|info|io|co"
SPACED_DOMAIN = re.compile(
    r"\b[a-z][a-z0-9-]*(?:\s*\.\s*[a-z][a-z0-9-]*)+\s*\.\s*(?:" + TLDS + r")\b",
    re.ASCII,
)


def repair_spaced_domains(text: str) -> str:
    """Rejoin a host whose dots were written with spaces around them."""
    return SPACED_DOMAIN.sub(
        lambda m: re.sub(r"\s*\.\s*", ".", m.group(0)), text
    )


def spoken_domain(match: re.Match) -> str:
    labels = match.group(0).split(".")
    return " ডট ".join(
        DOMAIN_LABEL_BN.get(part.lower(), spell_latin(part)) for part in labels
    )


def addresses_for_speech(text: str) -> str:
    """Strip paths and say each host label by label, joined with "ডট".

    Each label is translated via DOMAIN_LABEL_BN or spelled out, so a host is
    never left half in Latin for the voice to trip over.

    A host written with spaces around its dots is rejoined first, since every
    pattern here expects the labels joined.
    """
    out = repair_spaced_domains(text)
    out = URL.sub(lambda m: m.group(1), out)
    return DOMAIN.sub(spoken_domain, out)


# "য়" is one character (U+09DF) in some text and two (য + nukta) in other, and the
# two look the same, so a pattern written one way silently misses the other.
YA = "(?:\u09df|\u09af\u09bc)"
SITE_ECHO = re.compile(
    re.escape(SERVICE_SITE_BN)
    + r"\s+(?:ও"
    + YA
    + r"েবসাইট|পোর্টাল|সাইট)((?:টিতে|টি|ে|"
    + YA
    + r"ে)?)"
)


def dedupe_site_noun(text: str) -> str:
    """Collapse the doubled noun left by naming the site.

    Substituting a name for the address can state the noun twice, as in
    "এনআইডি সেবার ওয়েবসাইট ওয়েবসাইটে দেখুন", because the sentence already
    had one. The case ending is preserved rather than dropped, since the
    sentence needs "ওয়েবসাইটে দেখুন".

    The pattern deliberately omits \\b. A Bengali vowel sign is a word
    character to Python, so a boundary assertion after one does not mean
    what it appears to.
    """
    return SITE_ECHO.sub(lambda m: SERVICE_SITE_BN + m.group(1), text)
