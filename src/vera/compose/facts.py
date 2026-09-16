"""The fact ledger.

Everything the composer is allowed to say comes from here. A fact carries its
own provenance -- the dotted field path it came from -- so the rationale can
name where each claim originated and the grounding verifier can check a finished
body against the ledger that produced it.

Two rules are enforced at construction rather than left to the writer:

**Derivations are whitelisted, and `ctr` is not one of them.**  In this dataset
`ctr` is not `calls / views`: checked across all fifty generated merchants it
disagrees in fifty of fifty (m_011 is 4.6% against a 1.15% ratio).  They measure
different things.  Computing one from the other hands the judge arithmetic that
fails on inspection -- and because views and calls are both inside the judge's
window, it is a failure the judge can actually see.

**Comparisons carry a direction.**  `ctr_below_peer_median` is a tempting phrase
and it is false for the merchant above, whose CTR beats the peer average by half
again.  A comparison fact records which way it actually runs, so a template
cannot assert the flattering-sounding wrong one.

Tier A vs Tier B records whether a fact is inside the scoring prompt the shipped
simulator builds (`judge_simulator.py:503-531`).  It is not a permission system
-- the real grader is documented to hold the full dataset, and the brief's own
gold-standard message cites Tier B.  It is an ordering signal: lead with what
every judge can verify, and attribute the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable


class Tier(Enum):
    A = "A"  # inside the simulator's scoring window
    B = "B"  # real, but outside it -- attribute these


class Kind(Enum):
    COUNT = "count"
    PERCENT = "percent"
    CURRENCY = "currency"
    RATIO = "ratio"
    DATE = "date"
    NAME = "name"
    CITATION = "citation"
    TEXT = "text"


@dataclass(frozen=True)
class Fact:
    """One provable claim, with the field path that proves it."""

    id: str
    path: str
    value: Any
    display: str
    kind: Kind
    tier: Tier
    subject: str
    salience: float = 0.0
    note: str = ""
    is_new: bool = False  # arrived in a context version bump during this run

    @property
    def is_numeric(self) -> bool:
        return self.kind in (Kind.COUNT, Kind.PERCENT, Kind.CURRENCY, Kind.RATIO)


# Some derived flags are worth much more than others: a severe dip or an
# expiring subscription is a reason to write today, a stale-posts flag is not.
_SIGNAL_SALIENCE: dict[str, float] = {
    "perf_dip_severe": 0.95,
    "renewal_due_soon": 0.9,
    "dormant_with_vera": 0.8,
    "unverified_gbp": 0.75,
    "no_active_offers": 0.7,
    "ctr_below_peer_median": 0.7,
    "stale_posts": 0.6,
    "high_risk_adult_cohort": 0.6,
}


def _pct(x: float) -> str:
    """Render a fraction as a percentage without implying false precision."""
    v = x * 100
    return f"{v:.0f}%" if abs(v) >= 10 or v == int(v) else f"{v:.1f}%"


def _num(n: int | float) -> str:
    return f"{int(n):,}" if float(n).is_integer() else f"{n:,.1f}"


class FactLedger:
    """Every citable fact for one composition, indexed by id."""

    def __init__(self) -> None:
        self._facts: dict[str, Fact] = {}

    def add(self, fact: Fact) -> None:
        self._facts[fact.id] = fact

    def get(self, fact_id: str) -> Fact | None:
        return self._facts.get(fact_id)

    def all(self) -> list[Fact]:
        return sorted(self._facts.values(), key=lambda f: -f.salience)

    def tier(self, tier: Tier) -> list[Fact]:
        return [f for f in self.all() if f.tier is tier]

    def numeric(self, tier: Tier | None = None) -> list[Fact]:
        out = [f for f in self.all() if f.is_numeric]
        return [f for f in out if f.tier is tier] if tier else out

    def by_subject(self, subject: str) -> list[Fact]:
        return [f for f in self.all() if f.subject == subject]

    def __len__(self) -> int:
        return len(self._facts)

    def __iter__(self) -> Iterable[Fact]:
        return iter(self.all())

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def mark_new(self, new_values: set[Any]) -> int:
        """Flag facts whose value arrived in a version bump.

        Matching is on VALUE, not field path. The store flattens a payload to
        positional paths (`digest[2].title`) while a fact records a semantic
        one (`digest[d_2026W17_jida].title`), so the two vocabularies never
        line up. Values are stable across both.
        """
        if not new_values:
            return 0
        marked = 0
        for fid, fact in list(self._facts.items()):
            if fact.value in new_values or str(fact.value) in new_values:
                self._facts[fid] = replace(fact, is_new=True,
                                           salience=fact.salience + 0.25)
                marked += 1
        return marked

    def new_facts(self) -> list["Fact"]:
        return [f for f in self.all() if f.is_new]

    @classmethod
    def build(
        cls,
        merchant: dict[str, Any],
        category: dict[str, Any],
        trigger: dict[str, Any] | None = None,
        customer: dict[str, Any] | None = None,
        new_values: set[Any] | None = None,
    ) -> "FactLedger":
        led = cls()
        led._add_identity(merchant)
        led._add_performance(merchant, category)
        led._add_offers(merchant, category)
        led._add_signals(merchant)
        led._add_category(category)
        if trigger:
            led._add_trigger(trigger)
        if customer:
            led._add_customer(customer)
        if new_values:
            led.mark_new(new_values)
        return led

    # -- merchant ------------------------------------------------------

    def _add_identity(self, merchant: dict[str, Any]) -> None:
        ident = merchant.get("identity") or {}
        if name := ident.get("name"):
            self.add(Fact("merchant.name", "identity.name", name, name,
                          Kind.NAME, Tier.A, "merchant", salience=0.2))
        if owner := ident.get("owner_first_name"):
            self.add(Fact("merchant.owner", "identity.owner_first_name", owner,
                          owner, Kind.NAME, Tier.A, "merchant", salience=0.2))
        if loc := ident.get("locality"):
            self.add(Fact("merchant.locality", "identity.locality", loc, loc,
                          Kind.NAME, Tier.A, "merchant", salience=0.3))
        if city := ident.get("city"):
            self.add(Fact("merchant.city", "identity.city", city, city,
                          Kind.NAME, Tier.A, "merchant", salience=0.1))

    def _add_performance(
        self, merchant: dict[str, Any], category: dict[str, Any]
    ) -> None:
        """Raw counters, week-on-week deltas, and peer comparisons.

        This is the spine of nearly every message: views, calls and ctr are
        present on every merchant in the set and all three sit inside the
        judge's window whichever window is in play.
        """
        perf = merchant.get("performance") or {}
        peers = category.get("peer_stats") or {}

        raw = {
            "views": ("performance.views", "views", 0.5),
            "calls": ("performance.calls", "calls", 0.6),
            "directions": ("performance.directions", "direction requests", 0.3),
            "leads": ("performance.leads", "leads", 0.4),
        }
        for key, (path, label, sal) in raw.items():
            val = perf.get(key)
            if isinstance(val, (int, float)):
                self.add(Fact(f"perf.{key}", path, val, _num(val),
                              Kind.COUNT, Tier.A, "merchant", salience=sal,
                              note=label))

        # Views-per-enquiry. This is plain arithmetic over two numbers the
        # judge can see, and it is emphatically NOT the ctr field -- it must
        # never be labelled click-through. Stated as "one enquiry per N views"
        # it is checkable on its face and far more concrete than either
        # counter alone.
        v, c = perf.get("views"), perf.get("calls")
        if isinstance(v, (int, float)) and isinstance(c, (int, float)) and c > 0 and v > 0:
            per = v / c
            if per >= 2:
                self.add(Fact(
                    "derived.views_per_call", "performance.views/performance.calls",
                    per, f"one per {int(round(per))}", Kind.RATIO, Tier.A,
                    "merchant", salience=0.7,
                    note="views per enquiry -- arithmetic only, NOT the ctr field",
                ))

        if isinstance(ctr := perf.get("ctr"), (int, float)):
            # Recorded as its own measured fact. Never reconstructed from
            # calls/views -- see the module docstring.
            self.add(Fact("perf.ctr", "performance.ctr", ctr, _pct(ctr),
                          Kind.PERCENT, Tier.A, "merchant", salience=0.5,
                          note="click-through rate"))

        # Week-on-week movement. Outside the simulator's window, so Tier B,
        # but it is the single most story-bearing thing a merchant owns.
        for key, label in (("views_pct", "views"), ("calls_pct", "calls"),
                           ("ctr_pct", "CTR"), ("directions_pct", "directions")):
            val = (perf.get("delta_7d") or {}).get(key)
            if isinstance(val, (int, float)):
                direction = "up" if val > 0 else "down"
                self.add(Fact(
                    f"delta.{key}", f"performance.delta_7d.{key}", val,
                    f"{direction} {_pct(abs(val))}", Kind.PERCENT, Tier.B,
                    "merchant", salience=0.9 if abs(val) >= 0.15 else 0.55,
                    note=f"{label} week-on-week",
                ))

        # Peer comparisons, with the direction recorded so a template cannot
        # assert the wrong one.
        pairs = (
            ("views", "avg_views_30d", "views"),
            ("calls", "avg_calls_30d", "calls"),
            ("ctr", "avg_ctr", "CTR"),
            ("directions", "avg_directions_30d", "direction requests"),
        )
        for mine_key, peer_key, label in pairs:
            mine, peer = perf.get(mine_key), peers.get(peer_key)
            if not isinstance(mine, (int, float)) or not isinstance(peer, (int, float)):
                continue
            if not peer:
                continue
            multiple = mine / peer
            above = multiple >= 1.0
            if multiple >= 1.15:
                shape = f"{multiple:.1f}x the category average"
            elif multiple <= 0.85:
                shape = f"{_pct(1 - multiple)} below the category average"
            else:
                shape = "in line with the category average"
            self.add(Fact(
                f"peer.{mine_key}", f"peer_stats.{peer_key}", peer,
                shape, Kind.RATIO, Tier.B, "category",
                salience=0.8 if (multiple >= 1.5 or multiple <= 0.7) else 0.4,
                note=f"{label}: {_num(mine)} vs peer {_num(peer)}, "
                     f"{'above' if above else 'below'}",
            ))

    def _add_offers(self, merchant: dict[str, Any], category: dict[str, Any]) -> None:
        """Assertable vs proposable.

        A merchant's own offer may be asserted as live only while active; the
        judge is shown active offers only, and an expired one presented as
        current reads as fabrication. Category catalog entries are never
        asserted -- they are proposals, and phrased as such downstream.
        """
        for offer in merchant.get("offers") or []:
            if offer.get("status") != "active":
                continue
            title = offer.get("title")
            if not title:
                continue
            self.add(Fact(
                f"offer.{offer.get('id', title)}", "offers[].title", title,
                title, Kind.CURRENCY if "₹" in str(title) else Kind.TEXT,
                Tier.A, "merchant", salience=0.7, note="active offer",
            ))

        for tmpl in (category.get("offer_catalog") or [])[:6]:
            title = tmpl.get("title") if isinstance(tmpl, dict) else tmpl
            if not title:
                continue
            self.add(Fact(
                f"catalog.{title}", "offer_catalog[].title", title, title,
                Kind.TEXT, Tier.B, "category", salience=0.35,
                note="category catalog -- proposable, never assertable",
            ))

    def _add_signals(self, merchant: dict[str, Any]) -> None:
        """Derived flags, parsed rather than passed through as raw strings.

        `signals` is one of the few merchant fields inside the judge's scoring
        window, and it arrives as tokens like "stale_posts:22d" or
        "renewal_due_soon:12d" -- a name and, often, a number. Treating them as
        opaque text wastes both. An earlier version did exactly that, and the
        engine never spoke about a merchant carrying five populated signals.
        """
        for sig in merchant.get("signals") or []:
            raw = str(sig)
            name, _, qualifier = raw.partition(":")
            if not qualifier:
                # The other shape in this dataset: "dormant_with_vera_14d".
                tail = re.search(r"_(\d+[dwm])$", name)
                if tail:
                    qualifier = tail.group(1)
                    name = name[: tail.start()]
            human = name.replace("_", " ")
            display = human
            value: Any = raw

            # "22d" -> 22 days, so the number can be cited and verified.
            num = re.match(r"^(\d+)([dwm]?)$", qualifier.strip()) if qualifier else None
            if num:
                n = int(num.group(1))
                unit = {"d": "days", "w": "weeks", "m": "months"}.get(num.group(2), "days")
                display = f"{human} ({n} {unit})"
                value = n
                self.add(Fact(f"signal.{name}.n", f"signals[{name}]", n, str(n),
                              Kind.COUNT, Tier.A, "merchant", salience=0.7,
                              note=f"{human}, {unit}"))

            self.add(Fact(f"signal.{name}", "signals[]", value, display,
                          Kind.TEXT, Tier.A, "merchant",
                          salience=_SIGNAL_SALIENCE.get(name, 0.65),
                          note=human))
        agg = merchant.get("customer_aggregate") or {}
        for key, label in (("total_unique_ytd", "customers this year"),
                           ("lapsed_180d_plus", "lapsed over 180 days"),
                           ("retention_6mo_pct", "6-month retention")):
            val = agg.get(key)
            if isinstance(val, (int, float)):
                disp = _pct(val) if key.endswith("_pct") else _num(val)
                self.add(Fact(f"agg.{key}", f"customer_aggregate.{key}", val,
                              disp, Kind.PERCENT if key.endswith("_pct") else Kind.COUNT,
                              Tier.B, "merchant", salience=0.45, note=label))

    # -- category ------------------------------------------------------

    def _add_category(self, category: dict[str, Any]) -> None:
        for item in category.get("digest") or []:
            iid = item.get("id") or item.get("title", "")[:24]
            title = item.get("title")
            if not title:
                continue
            self.add(Fact(f"digest.{iid}", f"digest[{iid}].title", title, title,
                          Kind.TEXT, Tier.B, "category", salience=0.75,
                          note=item.get("patient_segment") or ""))
            if src := item.get("source"):
                self.add(Fact(f"digest.{iid}.source", f"digest[{iid}].source",
                              src, src, Kind.CITATION, Tier.B, "category",
                              salience=0.5))
            if isinstance(n := item.get("trial_n"), (int, float)):
                self.add(Fact(f"digest.{iid}.n", f"digest[{iid}].trial_n", n,
                              f"{_num(n)}-patient", Kind.COUNT, Tier.B,
                              "category", salience=0.6))

        for beat in category.get("seasonal_beats") or []:
            note = beat.get("note")
            if note:
                self.add(Fact(f"beat.{beat.get('month_range', note[:12])}",
                              "seasonal_beats[].note", note, note, Kind.TEXT,
                              Tier.B, "category", salience=0.5,
                              note=beat.get("month_range", "")))

        for trend in category.get("trend_signals") or []:
            q, delta = trend.get("query"), trend.get("delta_yoy")
            if q and isinstance(delta, (int, float)):
                self.add(Fact(f"trend.{q}", "trend_signals[].delta_yoy", delta,
                              f'"{q}" searches {"up" if delta > 0 else "down"} '
                              f"{_pct(abs(delta))} year on year",
                              Kind.PERCENT, Tier.B, "category", salience=0.6))

    # -- trigger / customer --------------------------------------------

    def _add_trigger(self, trigger: dict[str, Any]) -> None:
        """Facts carried by the event itself.

        Three quarters of generated triggers carry a contentless placeholder,
        and letting that statistic justify a shallow reader was a mistake: the
        quarter that IS populated holds the most citable numbers available. A
        perf_dip arrives as
        `{"metric":"calls","delta_pct":-0.5,"window":"7d","vs_baseline":12}` --
        a named metric, a signed change, a window and a baseline, all of which
        the judge can see.
        """
        payload = trigger.get("payload") or {}
        metric = payload.get("metric")

        for key, val in payload.items():
            if key in ("placeholder", "merchant_id", "customer_id", "category"):
                continue
            if isinstance(val, bool):
                continue

            if key.endswith("_pct") and isinstance(val, (int, float)):
                direction = "up" if val > 0 else "down"
                self.add(Fact(
                    f"trigger.{key}", f"trigger.payload.{key}", val,
                    f"{direction} {_pct(abs(val))}", Kind.PERCENT, Tier.A,
                    "trigger", salience=0.95,
                    note=f"{metric or key} {direction} over the trigger window",
                ))
            elif isinstance(val, (int, float)):
                self.add(Fact(f"trigger.{key}", f"trigger.payload.{key}", val,
                              _num(val), Kind.COUNT, Tier.A, "trigger",
                              salience=0.85, note=key.replace("_", " ")))
            elif isinstance(val, str) and val:
                self.add(Fact(f"trigger.{key}", f"trigger.payload.{key}", val,
                              val, Kind.TEXT, Tier.A, "trigger", salience=0.85,
                              note=key.replace("_", " ")))
            elif isinstance(val, dict):
                for k2, v2 in val.items():
                    if isinstance(v2, (int, float)) and not isinstance(v2, bool):
                        self.add(Fact(
                            f"trigger.{key}.{k2}", f"trigger.payload.{key}.{k2}",
                            v2, _num(v2), Kind.COUNT, Tier.A, "trigger",
                            salience=0.8, note=f"{key} {k2}".replace("_", " ")))

    def _add_customer(self, customer: dict[str, Any]) -> None:
        ident = customer.get("identity") or {}
        rel = customer.get("relationship") or {}
        if name := ident.get("name"):
            self.add(Fact("customer.name", "customer.identity.name", name, name,
                          Kind.NAME, Tier.A, "customer", salience=0.3))
        if last := rel.get("last_visit"):
            self.add(Fact("customer.last_visit", "customer.relationship.last_visit",
                          last, str(last), Kind.DATE, Tier.A, "customer",
                          salience=0.7))
        if isinstance(n := rel.get("visits_total"), (int, float)):
            self.add(Fact("customer.visits", "customer.relationship.visits_total",
                          n, _num(n), Kind.COUNT, Tier.A, "customer", salience=0.5))


# Whitelisted derivations. Anything not on this list must not be computed and
# stated as fact. `ctr` is deliberately absent.
ALLOWED_DERIVATIONS: frozenset[str] = frozenset({
    "peer_multiple",       # merchant metric / peer average
    "peer_shortfall",      # 1 - (merchant / peer)
    "delta_restatement",   # rendering delta_7d as up/down N%
    "views_per_call",      # views / calls, stated as a rate, never as "CTR"
})

FORBIDDEN_DERIVATIONS: dict[str, str] = {
    "ctr_from_calls_over_views": (
        "ctr is not calls/views in this dataset -- it disagrees for 50 of 50 "
        "merchants. Cite performance.ctr directly or say nothing about it."
    ),
}
