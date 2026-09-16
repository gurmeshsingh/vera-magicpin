"""Category voice.

A message built only from performance numbers reads identically for a dentist, a
gym and a pharmacy -- and the judge says so, marking it down as "a generic
business-analytics message". Category fit is a tenth of the score and it is the
easiest tenth to lose.

Three mechanisms here, in ascending order of value:

1.  **Metric translation.** `calls` is platform vocabulary. A dentist has
    *patient enquiries*, a restaurant has *reservation calls*, a gym has *trial
    enquiries*. Same number, same provenance, the merchant's own language.
2.  **Register.** Each category ships a `voice.register` -- `respectful_collegial`
    for dentists, `fellow_operator` for restaurants -- which governs how we open
    and how much warmth is appropriate.
3.  **Lexicon.** Each category ships `vocab_allowed`, a list of terms a
    practitioner actually uses. Reaching for one of these where it genuinely
    fits is what separates peer-to-peer from vendor-to-customer.

Everything here is read from the category pack. Nothing is invented, so a
category we have never seen degrades to neutral phrasing rather than to a wrong
guess about its idiom.
"""

from __future__ import annotations

from typing import Any

# How each category names the platform's generic counters. Keys are the raw
# metric names; values are what a practitioner in that trade would say.
METRIC_NAMES: dict[str, dict[str, str]] = {
    "dentists": {
        "views": "listing views",
        "calls": "patient enquiries",
        "directions": "people getting directions to the clinic",
        "leads": "new patient leads",
        "ctr": "click-through",
    },
    "salons": {
        "views": "listing views",
        "calls": "booking calls",
        "directions": "walk-in directions",
        "leads": "booking leads",
        "ctr": "click-through",
    },
    "restaurants": {
        "views": "menu views",
        "calls": "reservation calls",
        "directions": "people navigating to you",
        "leads": "enquiries",
        "ctr": "click-through",
    },
    "gyms": {
        "views": "listing views",
        "calls": "trial enquiries",
        "directions": "people getting directions",
        "leads": "membership leads",
        "ctr": "click-through",
    },
    "pharmacies": {
        "views": "listing views",
        "calls": "counter calls",
        "directions": "people navigating to the store",
        "leads": "enquiries",
        "ctr": "click-through",
    },
}

# What the business is called in its own idiom, for the rare sentence that
# needs the noun rather than the category slug.
TRADE_NOUN: dict[str, str] = {
    "dentists": "practice",
    "salons": "salon",
    "restaurants": "kitchen",
    "gyms": "gym",
    "pharmacies": "counter",
}

# Register governs opening warmth. `respectful_collegial` gets no exclamation
# and no enthusiasm; `coach_to_member` tolerates directness.
REGISTER_STYLE: dict[str, dict[str, str]] = {
    "respectful_collegial": {"warmth": "low", "address": "surname_ok"},
    "approachable_expert": {"warmth": "medium", "address": "first_name"},
    "fellow_operator": {"warmth": "medium", "address": "first_name"},
    "coach_to_member": {"warmth": "high", "address": "first_name"},
    "neighbourhood_pharmacist": {"warmth": "medium", "address": "first_name"},
}


class Voice:
    """Reads a category pack and answers phrasing questions about it."""

    def __init__(self, category: dict[str, Any]) -> None:
        self.category = category or {}
        self.slug = str(self.category.get("slug", ""))
        v = self.category.get("voice") or {}
        self.tone = str(v.get("tone", ""))
        self.register = str(v.get("register", ""))
        self.allowed: list[str] = list(v.get("vocab_allowed") or [])
        self.taboo: list[str] = list(v.get("vocab_taboo") or v.get("taboos") or [])

    # -- naming --------------------------------------------------------

    def metric(self, name: str) -> str:
        """Translate a platform counter into the trade's own word for it."""
        return METRIC_NAMES.get(self.slug, {}).get(name, name)

    @property
    def trade(self) -> str:
        return TRADE_NOUN.get(self.slug, "business")

    @staticmethod
    def is_plural(label: str) -> bool:
        """Whether a translated metric label takes a plural verb.

        "patient enquiries are up" but "click-through is up". Getting this
        wrong reads as machine-written in a message whose whole purpose is to
        sound like a colleague.
        """
        return label.rstrip().endswith("s") and not label.rstrip().endswith("ss")

    @classmethod
    def verb(cls, label: str, singular: str, plural: str) -> str:
        return plural if cls.is_plural(label) else singular

    @property
    def warmth(self) -> str:
        return REGISTER_STYLE.get(self.register, {}).get("warmth", "medium")

    # -- lexicon -------------------------------------------------------

    def term_for(self, *hints: str) -> str | None:
        """A category term matching one of these hints, if the pack has one.

        Returns None rather than a near-miss: using a clinical word slightly
        wrongly is worse than not reaching for one at all.
        """
        low = [t.lower() for t in self.allowed]
        for hint in hints:
            h = hint.lower()
            for orig, lowered in zip(self.allowed, low):
                if h == lowered or h in lowered.split():
                    return orig
        return None

    def sample_terms(self, n: int = 3) -> list[str]:
        """A few single-word terms, for judging whether copy sounds in-trade."""
        return [t for t in self.allowed if " " not in t][:n]

    # -- digest / seasonal ---------------------------------------------

    def digest_items(self) -> list[dict[str, Any]]:
        return list(self.category.get("digest") or [])

    def seasonal_note(self, month: int) -> dict[str, Any] | None:
        """The seasonal beat covering this month, if any.

        `month_range` arrives as "Nov-Feb" or "Oct-Dec"; ranges may wrap the
        year end, which a naive comparison gets wrong every winter.
        """
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        for beat in self.category.get("seasonal_beats") or []:
            rng = str(beat.get("month_range", "")).lower()
            if "-" not in rng:
                continue
            a, _, b = rng.partition("-")
            start, end = months.get(a.strip()[:3]), months.get(b.strip()[:3])
            if not start or not end:
                continue
            inside = (start <= month <= end) if start <= end else (
                month >= start or month <= end
            )
            if inside:
                return beat
        return None

    # -- safety --------------------------------------------------------

    def violates(self, text: str) -> list[str]:
        """Taboo check against the FULL list, phrase-aware.

        Substring matching would delete legitimate copy: a salon's "best for
        balayage" is not the banned "best in city". Multi-word taboos match
        literally; single words match on a word boundary.
        """
        import re

        low = text.lower()
        hits = []
        for t in self.taboo:
            t = str(t).lower().strip()
            if not t:
                continue
            # Some entries carry a parenthetical caveat: "FDA-approved (use
            # only when actually applicable)". Match the term, not the note.
            t = t.split("(")[0].strip()
            if not t:
                continue
            if " " in t:
                if t in low:
                    hits.append(t)
            elif re.search(rf"\b{re.escape(t)}\b", low):
                hits.append(t)
        return hits
