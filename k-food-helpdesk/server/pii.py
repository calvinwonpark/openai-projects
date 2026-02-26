import re
from typing import Tuple

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(
    r"(?:(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4})|"
    r"(?:(?:\+?82[-.\s]?)?0?1[0-9][-.\s]?\d{3,4}[-.\s]?\d{4})"
)


def detect_and_redact(text: str) -> Tuple[str, bool, bool]:
    if not text:
        return "", False, False

    detected = False
    redacted = False
    out = text

    if EMAIL_RE.search(out):
        detected = True
        out = EMAIL_RE.sub("[REDACTED_EMAIL]", out)
        redacted = True

    if PHONE_RE.search(out):
        detected = True
        out = PHONE_RE.sub("[REDACTED_PHONE]", out)
        redacted = True

    return out, detected, redacted
