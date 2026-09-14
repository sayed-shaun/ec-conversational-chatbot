"""Layout turned into pauses, so a list is heard as a list.

A written answer carries its structure in the whitespace: each fee on its
own line, each clause behind a "(১)". On screen that does the work of
punctuation. Collapsed into one line for the voice it does nothing, and the
reply becomes a single unbroken sentence the TTS reads without drawing
breath -- which is how "...চারশ ষাট টাকা (২) কার্ডে অপ্রদর্শিত..." reaches a
caller as one run of words, the item number sounding like part of the amount
before it.

So the layout is converted into the punctuation it stood for, before
anything downstream collapses the whitespace: a line break becomes a full
stop, a leading item marker becomes a number and a comma. No words are added
or removed -- only the marks that tell a voice where to stop.
"""

import re

# An item marker opening a line: "(১)", "১.", "১)", "ক)" or a bare "১" with
# the number still attached to the text after it. Anchored to the start of a
# line, which is what keeps it off "ক. নাগরিক সনদপত্র, খ. ইউটিলিটি বিল"
# written inline -- there the marks are already doing their job.
_ITEM_MARKER = re.compile(
    r"^([ \t]*)[(\[]?[ \t]*([০-৯]+|[0-9]+|[ক-ঙ])[ \t]*[)\].]?[ \t]+",
    re.MULTILINE,
)

# A line ending in any of these already tells the voice to pause, so adding a
# daṛi only stacks one mark on another: the corpus introduces its lists with a
# bisarga ("করতে হলেঃ") or a dash ("সেবা গুলো হলো-"), and both were coming out
# as "হলেঃ।" and "হলো-।".
_TERMINATORS = "।.!?,;:ঃ-–—…"


def _mark_items(text: str) -> str:
    """Give each item's number a comma to pause on."""
    return _ITEM_MARKER.sub(lambda m: f"{m.group(1)}{m.group(2)}, ", text)


def _break_lines(text: str) -> str:
    """End a line that runs straight into the next one.

    A line already ending in punctuation is left alone; a daṛi added after a
    daṛi would only double it, and the punctuation stage would then collapse
    the pair anyway.
    """
    out = []
    lines = text.split("\n")
    for index, line in enumerate(lines):
        stripped = line.rstrip()
        last = index == len(lines) - 1
        if stripped and not last and stripped[-1] not in _TERMINATORS:
            stripped += "।"
        out.append(stripped)
    return "\n".join(out)


def layout_for_speech(text: str) -> str:
    """Turn an answer's layout into the pauses it stood for."""
    if not text:
        return text or ""
    return _break_lines(_mark_items(text))
