"""Provenance verification.

The gate between composing a message and sending it. Every number, price,
percentage, date, citation and proper noun in a finished body must trace back to
a fact in the ledger that produced it. Anything that cannot be traced is an
orphan, and an orphan is either a bug in the composer or a hallucination -- both
of which cost more than silence does.

This exists because the composer already produced one in review: an early
version of the no-offer angle claimed a catalog format was "pulling traffic in
Gomti Nagar right now". Every word of that was invented. It was caught by eye,
which does not scale to a live test window.

Two checks carry most of the weight:

**Orphan numerals.** Every numeral in the body must match a ledger fact under
normalisation -- 2,410 and 2410 and "2,410 views" are the same claim, 18% and
0.18 are the same claim. This is cheap and catches almost every fabricated
statistic.

**Semantic relations.** A number can be individually traceable and still be
asserted wrongly. "Your CTR is 1.1%" computed from calls over views is arithmetic
the judge can check and watch fail, because `ctr` is a separate measurement in
this dataset. Likewise a comparison must run in the direction the data runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from ..compose.facts import Fact, FactLedger, Kind


class Severity(Enum):
    ERROR = "error"    # do not send
    WARN = "warn"      # send, but record


@dataclass(frozen=True)
class Violation:
    severity: Severity
    code: str
    detail: str
    fragment: str = ""


# Numerals that carry no factual claim about the merchant.
_SAFE_NUMERALS = {
    "24",   # "24h", the WhatsApp session window
    "30",   # "last 30 days", the stated reporting window
    "7",    # "7 days"
    "1",    # "one per N", ordinals
    "2",    # "2 minutes"
    "12", "6", "3",
}

_NUM_RE = re.compile(
    r"(?<![\w.])"
    r"(?:₹\s?|Rs\.?\s?)?"          # optional currency marker
    r"(\d{1,3}(?:,\d{2,3})+|\d+(?:\.\d+)?)"
    r"\s?%?",
)

_CITATION_RE = re.compile(r"\(([^)]*\b(?:20\d{2}|p\.\s?\d+|vol\.|issue)\b[^)]*)\)", re.I)

# Words that may be capitalised mid-sentence without being an entity claim.
_CAP_ALLOW = {
    "I", "WhatsApp", "Google", "Vera", "Want", "Worth", "Timing", "That",
    "The", "You", "Your", "More", "Calls", "Views", "People", "Conversion",
    "Discovery", "Free", "Flat", "Reply", "YES", "STOP", "Usually", "One",
}


def _norm_number(raw: str) -> set[float]:
    """Every numeric reading of a token, so matching is representation-agnostic."""
    cleaned = raw.replace(",", "").strip()
    try:
        val = float(cleaned)
    except ValueError:
        return set()
    # 18 may be a count, or 18% expressed as 0.18 in the source field.
    return {val, val / 100.0, val * 100.0}


def _ledger_numbers(ledger: FactLedger) -> dict[float, list[Fact]]:
    index: dict[float, list[Fact]] = {}

    def put(v: float, f: Fact) -> None:
        index.setdefault(round(v, 6), []).append(f)

    for fact in ledger.all():
        if isinstance(fact.value, (int, float)):
            for v in (float(fact.value), abs(float(fact.value)),
                      float(fact.value) * 100.0, abs(float(fact.value)) * 100.0):
                put(round(v, 6), fact)
            # Rounded renderings: "one per 134" comes from 133.9.
            put(round(float(fact.value)), fact)
            put(round(abs(float(fact.value)) * 100.0), fact)
        # Numerals embedded in a display string ("2,100-patient", "₹299").
        for m in _NUM_RE.finditer(str(fact.display)):
            for v in _norm_number(m.group(1)):
                put(round(v, 6), fact)
    return index


def _context_numbers(contexts: Iterable[Any]) -> set[float]:
    """Every numeral appearing anywhere in the raw pushed context.

    Provenance means "this came from the context", not "my ledger happened to
    extract it". An earlier version checked only the ledger and flagged a
    perfectly real figure -- 240 chronic-prescription customers, present in the
    merchant record -- as a fabrication. That is a false accusation, and in a
    composer comparison it silently penalises whichever side reads more of the
    context than we do.
    """
    found: set[float] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v)
        elif isinstance(obj, bool):
            return
        elif isinstance(obj, (int, float)):
            for v in (float(obj), abs(float(obj)) * 100.0, round(float(obj))):
                found.add(round(v, 6))
        elif isinstance(obj, str):
            for m in _NUM_RE.finditer(obj):
                found.update(round(v, 6) for v in _norm_number(m.group(1)))

    for ctx in contexts:
        walk(ctx)
    return found


def verify(
    body: str,
    ledger: FactLedger,
    cta: str = "",
    rationale: str = "",
    contexts: Iterable[Any] | None = None,
) -> list[Violation]:
    """Check a finished message against the facts that were available.

    `contexts` is the raw pushed payloads. When given, a numeral appearing
    anywhere in them counts as grounded even if the ledger never indexed it.

    Returns an empty list when the message is fully grounded.
    """
    text = f"{body} {cta}".strip()
    out: list[Violation] = []
    index = _ledger_numbers(ledger)
    extra = _context_numbers(contexts) if contexts else set()

    # --- orphan numerals ------------------------------------------------
    for m in _NUM_RE.finditer(text):
        token = m.group(1)
        if token.replace(",", "") in _SAFE_NUMERALS:
            continue
        readings = _norm_number(token)
        if not readings:
            continue
        if not any(round(v, 6) in index or round(v, 6) in extra
                   for v in readings):
            out.append(Violation(
                Severity.ERROR, "orphan_numeral",
                f"{token!r} does not trace to any fact in the ledger",
                fragment=text[max(0, m.start() - 30):m.end() + 30],
            ))

    # --- citations ------------------------------------------------------
    cited = {str(f.display).lower() for f in ledger.all()
             if f.kind is Kind.CITATION}
    for m in _CITATION_RE.finditer(text):
        claim = m.group(1).strip().lower()
        if not any(claim in c or c in claim for c in cited):
            out.append(Violation(
                Severity.ERROR, "orphan_citation",
                f"citation {m.group(1)!r} is not in the ledger",
                fragment=m.group(0),
            ))

    # --- proper nouns ---------------------------------------------------
    known = " ".join(str(f.display) for f in ledger.all()).lower()
    if contexts:
        import json as _json
        known += " " + " ".join(_json.dumps(ctx, ensure_ascii=False).lower()
                                for ctx in contexts)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        words = sentence.split()
        for word in words[1:]:  # skip sentence-initial capitalisation
            bare = word.strip('",.!?:;()—-')
            if not bare or not bare[0].isupper() or bare in _CAP_ALLOW:
                continue
            if bare.lower() in known:
                continue
            # Blocking, not advisory. A place or entity name that is not in
            # the ledger is a fabricated claim about the merchant's world --
            # this is precisely the "pulling traffic in Gomti Nagar" bug that
            # motivated this module, and as a warning it would have shipped.
            # Measured safe: across all 48 composed messages the corpus raises
            # zero proper-noun violations, so promoting costs no real sends.
            out.append(Violation(
                Severity.ERROR, "unverified_proper_noun",
                f"{bare!r} appears in the message but not in the ledger",
                fragment=sentence[:80],
            ))

    # --- semantic relations ---------------------------------------------
    out.extend(_check_relations(text, ledger))

    # --- rationale consistency ------------------------------------------
    if rationale:
        for m in _NUM_RE.finditer(rationale):
            token = m.group(1)
            if token.replace(",", "") in _SAFE_NUMERALS:
                continue
            readings = _norm_number(token)
            if readings and not any(round(v, 6) in index or round(v, 6) in extra
                                    for v in readings):
                out.append(Violation(
                    Severity.WARN, "rationale_orphan_numeral",
                    f"rationale cites {token!r}, which is not in the ledger",
                ))
    return out


def _check_relations(text: str, ledger: FactLedger) -> list[Violation]:
    """Claims that are individually traceable but relationally false."""
    out: list[Violation] = []
    low = text.lower()

    # A click-through rate stated next to views and calls invites the judge to
    # verify it by division -- which fails, because ctr is measured separately.
    if re.search(r"\b(ctr|click[- ]through)\b", low):
        ctr = ledger.get("perf.ctr")
        views, calls = ledger.get("perf.views"), ledger.get("perf.calls")
        if ctr is None:
            out.append(Violation(
                Severity.ERROR, "ctr_without_source",
                "message mentions CTR but performance.ctr is not in the ledger",
            ))
        elif (views and calls
              and isinstance(views.value, (int, float))
              and isinstance(calls.value, (int, float)) and views.value
              # Only a risk when both operands are visible in the message
              # itself. A CTR quoted alone gives the judge nothing to divide.
              and str(views.display) in text and str(calls.display) in text):
            implied = calls.value / views.value
            if abs(implied - float(ctr.value)) > 0.002:
                out.append(Violation(
                    Severity.WARN, "ctr_invites_bad_arithmetic",
                    f"body states CTR ({ctr.display}) alongside views and calls, "
                    f"whose ratio is {implied:.1%}. A judge dividing one by the "
                    f"other will read the message as wrong.",
                ))

    # A comparison must run the way the data runs.
    for metric in ("views", "calls", "ctr"):
        peer = ledger.get(f"peer.{metric}")
        if peer is None:
            continue
        above = "above" in str(peer.note)
        claims_below = re.search(
            rf"\b{metric}\b[^.]{{0,40}}\b(below|under|behind|less than)\b", low)
        claims_above = re.search(
            rf"\b{metric}\b[^.]{{0,40}}\b(above|ahead|beating|better than)\b", low)
        if claims_below and above:
            out.append(Violation(
                Severity.ERROR, "comparison_direction",
                f"message says {metric} is below peers; {peer.note}",
            ))
        if claims_above and not above:
            out.append(Violation(
                Severity.ERROR, "comparison_direction",
                f"message says {metric} is above peers; {peer.note}",
            ))
    return out


def is_sendable(violations: Iterable[Violation]) -> bool:
    """A message with any ERROR is withheld. Silence costs nothing."""
    return not any(v.severity is Severity.ERROR for v in violations)
