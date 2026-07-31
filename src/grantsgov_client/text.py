"""Normalization for untrusted upstream text.

Everything either API returns is data, never instructions and never markup to
render: it is stripped of tags, HTML-unescaped, whitespace-collapsed and
length-capped before it reaches a caller. Nothing fetched is executed, and no
link in a payload is followed.
"""

import re
from html import unescape

_TAG_RE = re.compile(r"<[^>]+>")

DEFAULT_CAP = 20_000


def plain_text(value, cap=DEFAULT_CAP):
    """Untrusted HTML-ish upstream text -> bounded plain text (or None).

    Returns None for an empty input and for input that collapses to nothing,
    so "absent" and "blank" are the same value downstream.
    """
    if not value:
        return None
    text = unescape(_TAG_RE.sub(" ", str(value)))
    return " ".join(text.split())[:cap] or None
