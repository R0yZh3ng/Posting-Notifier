"""Extract eligibility requirements (citizenship, clearance, sponsorship, degree level) from job text.

Returns {tag: matching sentence} so the UI can show *why* a job was flagged and you can spot false positives.
Tags: us_citizen, clearance, no_sponsor, masters_req, phd_req. "_src" says whether we read the full
description ("desc") or only the title ("title").
"""
from __future__ import annotations

import html as _html
import re

I = re.I

# --- tag patterns (matched per sentence) -----------------------------------------------------
_US_CITIZEN = re.compile(
    r"\bu\.?\s?s\.?\s*(citizen|citizenship|person)s?\b|\bunited states\s+(citizen|citizenship|person)"
    r"|\bcitizens? of the (u\.?s\.?|united states)|\bmust be (a )?(u\.?s\.? )?citizen|\bitar\b"
    r"|citizenship (is )?(required|needed)|\bu\.?s\.? national\b", I)
_EXPORT = re.compile(r"export[- ]control", I)
_PERSON = re.compile(r"\b(u\.?s\.? )?(person|citizen|national)s?\b", I)
_CLEARANCE = re.compile(
    r"\b(security|secret|top[- ]secret|ts/sci|ts-sci|dod|government)\s+clearance|\bpolygraph\b"
    r"|\bactive (secret|top secret|ts)\b|\bclearance\b.{0,40}\b(required|must|eligib|obtain|active)", I)
_NO_SPONSOR = re.compile(
    r"\b(not|unable to|cannot|can't|won't|will not|do not|does not|don't|doesn't)\b[^.]{0,40}\bsponsor"
    r"|without (the need for )?(visa |employer |immigration )?sponsorship|\bno (visa )?sponsorship"
    r"|sponsorship (is )?(not|unavailable)", I)
_DEG_MASTERS = re.compile(r"\bmaster'?s?\b|(?-i:\bM\.?S\.?c?\b(?=[ ,/).]))|graduate (degree|student|program|school)", I)
_DEG_PHD = re.compile(r"\bph\.?\s?d\b|\bdoctora(l|te)\b", I)
_DEG_CONTEXT = re.compile(r"pursuing|enrolled|currently|working toward|candidate|studying|completing|"
                          r"degree|student|must|required|requirement", I)

# --- guards ----------------------------------------------------------------------------------
_NEGATE = re.compile(r"regardless of|irrespective|not (contingent|dependent|limited|restricted)|not (be )?(a )?(required|requirement|necessary)|does not require|"
                     r"without regard|discriminat|equal opportunity|all qualified applicants|no .{0,20}citizenship", I)
_SOFT = re.compile(r"\b(preferred|a plus|nice to have|desired|ideal|bonus|helpful|advantage)\b", I)
_BACHELOR = re.compile(r"bachelor|undergrad|\bb\.?s\.?c?\b|\bba\b|or equivalent|associate", I)

_SENT = re.compile(r"(?<=[.!?])\s+|[\n\r•·▪●;]+")
_TAG = re.compile(r"<[^>]+>")


def clean(text: str | None) -> str:
    """HTML (possibly entity-escaped, as Greenhouse sends it) -> plain text."""
    if not text:
        return ""
    t = _html.unescape(text)
    if "<" in t:
        t = _html.unescape(_TAG.sub(" ", re.sub(r"</(p|li|div|br|h\d)>|<br\s*/?>", "\n", t, flags=I)))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    # Dots in abbreviations would otherwise be read as sentence ends.
    t = re.sub(r"\bU\.\s?S\.(?:A\.)?", "US", t)
    t = re.sub(r"\bPh\.\s?D\.?", "PhD", t, flags=I)
    return re.sub(r"\b([BM])\.\s?S\.?(c?)(?![A-Za-z])", r"\1S\2", t)


def _snip(s: str) -> str:
    s = " ".join(s.split())
    return s if len(s) <= 160 else s[:157] + "…"


def analyze(title: str, description: str | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    text = clean(description)
    out["_src"] = "desc" if text else "title"

    # Title cues are strong: "PhD Research Intern", "Master's Software Intern".
    if _DEG_PHD.search(title):
        out["phd_req"] = _snip(title)
    elif re.search(r"\bmaster'?s?\b|\bmsc\b|graduate student", title, I):
        out["masters_req"] = _snip(title)

    for sent in _SENT.split(text):
        s = sent.strip()
        if len(s) < 12:
            continue
        negated = bool(_NEGATE.search(s))
        soft = bool(_SOFT.search(s))
        if not negated:
            if "us_citizen" not in out and (_US_CITIZEN.search(s) or (_EXPORT.search(s) and _PERSON.search(s))):
                out["us_citizen"] = _snip(s)
            if "clearance" not in out and _CLEARANCE.search(s) and not soft:
                out["clearance"] = _snip(s)
        if "no_sponsor" not in out and _NO_SPONSOR.search(s):
            out["no_sponsor"] = _snip(s)
        if _DEG_CONTEXT.search(s) and not soft and not _BACHELOR.search(s):
            if _DEG_MASTERS.search(s):  # "Master's or PhD" -> the lower bar is a Master's
                out.pop("phd_req", None)
                out.setdefault("masters_req", _snip(s))
            elif "phd_req" not in out and "masters_req" not in out and _DEG_PHD.search(s):
                out["phd_req"] = _snip(s)
    return out
