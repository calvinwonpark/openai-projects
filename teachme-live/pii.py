import re
from typing import Dict

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(
    r"(?:(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4})|"
    r"(?:(?:\+?82[-.\s]?)?0?1[0-9][-\.\s]?\d{3,4}[-.\s]?\d{4})"
)
ADDRESS_RE = re.compile(
    r"\b\d{1,5}\s+[A-Za-z0-9.\- ]+\s(?:st|street|rd|road|ave|avenue|blvd|lane|ln|dr|drive)\b",
    re.IGNORECASE,
)


def detect_and_redact(text: str) -> Dict[str, object]:
    if not text:
        return {"redacted_text": "", "detected": False, "redacted": False}

    redacted_text = text
    detected = False
    redacted = False

    if EMAIL_RE.search(redacted_text):
        detected = True
        redacted_text = EMAIL_RE.sub("[REDACTED_EMAIL]", redacted_text)
        redacted = True

    if PHONE_RE.search(redacted_text):
        detected = True
        redacted_text = PHONE_RE.sub("[REDACTED_PHONE]", redacted_text)
        redacted = True

    if ADDRESS_RE.search(redacted_text):
        detected = True
        redacted_text = ADDRESS_RE.sub("[REDACTED_ADDRESS]", redacted_text)
        redacted = True

    return {"redacted_text": redacted_text, "detected": detected, "redacted": redacted}
