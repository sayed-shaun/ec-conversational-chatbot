"""Web addresses, said rather than dictated.

A spoken address is only useful as far as the host: reading a path aloud
gives a listener nothing they can act on, and the path is where Latin
letters survive every other rule.

SERVICE_SITE_BN names the one address in the knowledge base instead of
spelling it out, which would be thirteen syllables of dictation. Only
speech is affected; the on-screen reply keeps the real URL, as this
module runs on the way to TTS and nowhere else.
"""

import re

from src.speech.transform.latin import spell_latin

SERVICE_SITE_BN = "এনআইডি সেবার ওয়েবসাইট"

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

_URL = re.compile(
    r"(?:https?://)?\b([a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z]{2,})+)(?:/[^\s,।;)]*)?",
    re.ASCII,
)
_KNOWN_DOMAIN = re.compile(r"(?:services\.)?nidw\.gov\.bd", re.IGNORECASE | re.ASCII)
_DOMAIN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z]{2,})+\b", re.ASCII)


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
_TLDS = "bd|com|org|net|gov|edu|info|io|co"
_SPACED_DOMAIN = re.compile(
    r"\b[a-z][a-z0-9-]*(?:\s*\.\s*[a-z][a-z0-9-]*)+\s*\.\s*(?:" + _TLDS + r")\b",
    re.ASCII,
)


def _repair_spaced_domains(text: str) -> str:
    """Rejoin a host whose dots were written with spaces around them."""
    return _SPACED_DOMAIN.sub(
        lambda m: re.sub(r"\s*\.\s*", ".", m.group(0)), text
    )


def _spoken_domain(match: re.Match) -> str:
    labels = match.group(0).split(".")
    return " ডট ".join(
        DOMAIN_LABEL_BN.get(part.lower(), spell_latin(part)) for part in labels
    )


def addresses_for_speech(text: str) -> str:
    """Strip paths, name the known site, break other hosts on their dots.

    Unknown hosts have each label translated via DOMAIN_LABEL_BN or spelled
    out, so a bare nidw.gov.bd is not left half in Latin for the voice to
    trip over.

    A host written with spaces around its dots is rejoined first, since every
    pattern here expects the labels joined.
    """
    out = _repair_spaced_domains(text)
    out = _URL.sub(lambda m: m.group(1), out)
    out = _KNOWN_DOMAIN.sub(SERVICE_SITE_BN, out)
    return _DOMAIN.sub(_spoken_domain, out)


_SITE_ECHO = re.compile(
    re.escape(SERVICE_SITE_BN) + r"\s+(?:ওয়েবসাইট|পোর্টাল|সাইট)((?:টিতে|টি|ে|য়ে)?)"
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
    return _SITE_ECHO.sub(lambda m: SERVICE_SITE_BN + m.group(1), text)
