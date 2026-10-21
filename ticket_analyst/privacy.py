"""Remove personal information and pull hardware barcodes out of ticket text.

Order matters: barcodes are pulled out first, then text is masked, then the
person fields are dropped. Nothing personal leaves this module.
"""

from __future__ import annotations

import re
from typing import Any

from .config import Settings
from .servicenow import PERSON_FIELDS

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Phone numbers written with a +, brackets, or separators, e.g. +1 555 123 4567, (02) 9876-5432.
# Plain unbroken digit strings are left alone because they may be barcodes.
PHONE_RE = re.compile(
    r"\(\d{1,4}\)[\s.-]?\d{2,6}(?:[\s.-]\d{2,6}){0,3}"  # (02) 9876-5432
    r"|\b\d{2,4}(?:[\s.-]\d{2,4}){2,4}\b"  # 555-123-4567, 0412 345 678
)
PLUS_PHONE_RE = re.compile(r"\+\d{1,3}(?:[\s.-]?\(?\d{1,6}\)?){1,5}")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
GREETING_RE = re.compile(r"\b(Hi|Hello|Dear|Regards|Thanks|Thank you|Cheers),?\s+[A-Z][a-z]+\b(?![ \t]+[A-Z])")

TEXT_FIELDS = ("short_description", "description")


def is_hardware(ticket: dict[str, Any], settings: Settings) -> bool:
    cats = settings.hardware_categories
    return (ticket.get("category", "").lower() in cats) or (
        ticket.get("subcategory", "").lower() in cats
    )


def extract_barcodes(ticket: dict[str, Any], settings: Settings) -> list[str]:
    lengths = sorted(set(settings.barcode_lengths), reverse=True)
    alts = "|".join(r"\d{%d}" % n for n in lengths)
    digits_re = re.compile(r"(?<![\w.])(?:%s)(?![\w.])" % alts)
    found: list[str] = []
    for f in settings.barcode_fields:
        v = str(ticket.get(f, "")).strip()
        if v.isdigit() and len(v) in lengths:
            found.append(v)
    for f in TEXT_FIELDS:
        found.extend(digits_re.findall(ticket.get(f, "") or ""))
    # keep order, drop duplicates
    return list(dict.fromkeys(found))


def _name_patterns(ticket: dict[str, Any]) -> list[re.Pattern[str]]:
    pats = []
    for f in PERSON_FIELDS:
        full = (ticket.get(f) or "").strip()
        if not full:
            continue
        parts = [full] + [p for p in re.split(r"[\s,]+", full) if len(p) >= 3]
        for p in sorted(set(parts), key=len, reverse=True):
            pats.append(re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE))
    return pats


DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}[.-]\d{2}[.-]\d{4}")


def _phone_or_date(m: re.Match[str]) -> str:
    return m.group(0) if DATE_RE.fullmatch(m.group(0).strip()) else "[PHONE]"


def mask_text(text: str, name_patterns: list[re.Pattern[str]] | None = None) -> str:
    if not text:
        return ""
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = PLUS_PHONE_RE.sub("[PHONE]", text)
    text = IPV4_RE.sub("[IP]", text)
    text = PHONE_RE.sub(_phone_or_date, text)
    for pat in name_patterns or []:
        text = pat.sub("[NAME]", text)
    text = GREETING_RE.sub(r"\1 [NAME]", text)
    return text


def sanitize(ticket: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Return a copy that is safe for the report and the AI."""
    t = dict(ticket)
    t["is_hardware"] = is_hardware(t, settings)
    t["barcodes"] = extract_barcodes(t, settings) if t["is_hardware"] else []
    names = _name_patterns(t)
    for f in TEXT_FIELDS:
        t[f] = mask_text(t.get(f, ""), names)
    for f in PERSON_FIELDS:
        t.pop(f, None)
    return t
