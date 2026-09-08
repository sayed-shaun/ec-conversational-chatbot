"""Web addresses, said rather than dictated.

A spoken address is only useful as far as the host. Reading a path out --
"slash n i d dash pub slash fees" -- tells a listener nothing they can act on,
and the path is where Latin letters survive every other rule.
"""

import re

from src.chatbot.transform.latin import spell_latin

# The one address in the knowledge base, said as a name rather than spelled
# out. "সার্ভিসেস ডট এনআইডিডাব্লিউ ডট গভ ডট বিডি" is thirteen syllables of
# dictation that nobody can act on by ear, and a listener who wants to type it
# is reading the on-screen reply anyway -- this transform only feeds TTS, so
# the visible text keeps the real URL.
SERVICE_SITE_BN = "এনআইডি সেবার ওয়েবসাইট"

# Domain labels, so a bare nidw.gov.bd is not left half-translated. The known
# full address is handled above; this catches every other host, where splitting
# on the dots alone would leave the labels in Latin for the voice to trip over.
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


def _spoken_domain(match: re.Match) -> str:
    labels = match.group(0).split(".")
    return " ডট ".join(
        DOMAIN_LABEL_BN.get(part.lower(), spell_latin(part)) for part in labels
    )


def addresses_for_speech(text: str) -> str:
    """Strip paths, name the known site, break other hosts on their dots."""
    out = _URL.sub(lambda m: m.group(1), text)
    out = _KNOWN_DOMAIN.sub(SERVICE_SITE_BN, out)
    return _DOMAIN.sub(_spoken_domain, out)


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
