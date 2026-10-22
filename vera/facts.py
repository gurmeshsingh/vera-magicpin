"""Context normalisation and fact extraction.

`Ctx` wraps the four raw context dicts (plus "now" and what changed since the
previous version) and exposes clean, already-formatted facts:

    ctx.salutation      "Dr. Meera"
    ctx.perf_line(...)  "CTR 2.1% vs 3.0% peer average"
    ctx.insights()      ranked list of merchant observations worth mentioning

Every number the composer prints comes from here.  `ctx.allowed_numbers` is the
set of every number that appears anywhere in the contexts plus the numbers this
module derived on purpose (e.g. "111 short of 1,000").  The guard uses it to
reject any message containing a number that is not grounded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_NUM_RE = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")


# --------------------------------------------------------------------------- formatting
def fmt_int(n: float | int) -> str:
    """Indian digit grouping: 1820 -> 1,820 ; 124000 -> 1,24,000."""
    n = int(round(n))
    sign = "-" if n < 0 else ""
    s = str(abs(n))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return sign + ",".join(parts) + "," + tail


def pct_number(frac: float) -> float:
    """0.021 -> 2.1 ; 0.38 -> 38 ; -0.5 -> -50."""
    x = frac * 100
    return round(x, 1) if abs(x) < 10 and abs(x - round(x)) > 0.05 else float(round(x))


def fmt_pct(frac: float, signed: bool = False) -> str:
    x = pct_number(frac)
    body = (f"{x:.1f}" if x != int(x) else f"{int(x)}")
    if signed and x > 0:
        body = "+" + body
    return body + "%"


def fmt_date(iso: str, with_year: bool = False) -> str:
    """'2026-12-15' or full ISO -> '15 Dec' (optionally '15 Dec 2026')."""
    d = parse_dt(iso)
    if not d:
        return str(iso)
    out = f"{d.day} {MONTHS[d.month - 1]}"
    return out + (f" {d.year}" if with_year else "")


def fmt_time(iso: str) -> str:
    d = parse_dt(iso)
    if not d or (d.hour == 0 and d.minute == 0):
        return ""
    h = d.hour % 12 or 12
    suffix = "am" if d.hour < 12 else "pm"
    return f"{h}{':%02d' % d.minute if d.minute else ''}{suffix}"


def parse_dt(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    v = value.strip().replace("Z", "+00:00")
    for candidate in (v, v[:10]):
        try:
            d = datetime.fromisoformat(candidate)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def humanize(token: str) -> str:
    """'6_month_cleaning' -> '6-month cleaning' ; 'kids_yoga_post' -> 'kids yoga post'."""
    t = str(token).strip()
    t = re.sub(r"(\d)_(month|week|day|year)", r"\1-\2", t)
    return t.replace("_", " ").strip()


def numbers_in(text: str) -> list[float]:
    out = []
    for m in _NUM_RE.finditer(text or ""):
        raw = m.group().replace(",", "")
        try:
            out.append(float(raw))
        except ValueError:
            pass
    return out


def _collect_numbers(obj, out: set) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        v = float(obj)
        out.add(round(v, 2))
        out.add(float(round(v)))
        if abs(v) <= 5:  # likely a fraction: also allow the percent forms
            out.add(round(v * 100, 2))
            out.add(pct_number(v))
            out.add(abs(pct_number(v)))
            out.add(float(round(abs(v * 100))))
        out.add(abs(round(v, 2)))
        return
    if isinstance(obj, str):
        for n in numbers_in(obj):
            out.add(round(n, 2))
        d = parse_dt(obj)
        if d:
            out.update({float(d.day), float(d.month), float(d.year), float(d.hour % 12 or 12),
                        float(d.minute)})
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            _collect_numbers(k, out)
            _collect_numbers(v, out)
        return
    if isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_numbers(v, out)


# --------------------------------------------------------------------------- insights
@dataclass
class Insight:
    key: str            # stable id, e.g. "ctr_below_peer"
    text: str           # ready-to-print clause, no trailing period
    weight: float       # how strong / actionable (higher = lead with it)
    lever: str          # loss_aversion | social_proof | curiosity | reciprocity | momentum
    action: str = ""    # the natural next step this insight suggests
    tags: set = field(default_factory=set)


# --------------------------------------------------------------------------- context
class Ctx:
    def __init__(self, category: dict | None, merchant: dict | None, trigger: dict | None,
                 customer: dict | None = None, now: str | None = None,
                 prev_merchant: dict | None = None, fresh_digest_ids: set | None = None) -> None:
        self.category = category or {}
        self.merchant = merchant or {}
        self.trigger = trigger or {}
        self.customer = customer
        self.now = parse_dt(now) or datetime.now(timezone.utc)
        self.prev_merchant = prev_merchant
        self.fresh_digest_ids = fresh_digest_ids or set()
        self.payload = self.trigger.get("payload") if isinstance(self.trigger.get("payload"), dict) else {}
        self._allowed: set[float] = set()
        for src in (self.category, self.merchant, self.trigger, self.customer or {}):
            _collect_numbers(src, self._allowed)
        if prev_merchant:  # numbers from the previous version are real context too ("from 2,410 to 3,105")
            _collect_numbers(prev_merchant.get("performance") or {}, self._allowed)

    # ---- grounding -------------------------------------------------------
    def allow(self, *values: float) -> None:
        """Register a number this code derived on purpose."""
        for v in values:
            self._allowed.add(round(float(v), 2))
            self._allowed.add(float(round(v)))

    @property
    def allowed_numbers(self) -> set[float]:
        return self._allowed

    # ---- identity ----------------------------------------------------------
    @property
    def slug(self) -> str:
        return str(self.category.get("slug") or self.merchant.get("category_slug") or "business")

    @property
    def identity(self) -> dict:
        return self.merchant.get("identity") or {}

    @property
    def name(self) -> str:
        return str(self.identity.get("name") or "your business")

    @property
    def owner(self) -> str:
        own = str(self.identity.get("owner_first_name") or "").strip()
        if own:
            return own
        nm = self.name
        m = re.match(r"(?:Dr\.?\s+)?([A-Z][a-z]+)'?s?\b", nm)
        return m.group(1) if m else ""

    @property
    def salutation(self) -> str:
        own = self.owner
        if not own:
            return f"{self.identity['name']} team" if self.identity.get("name") else "Hi there"
        if self.slug == "dentists" and not own.lower().startswith("dr"):
            return f"Dr. {own}"
        return own

    @property
    def locality(self) -> str:
        return str(self.identity.get("locality") or self.identity.get("city") or "")

    @property
    def city(self) -> str:
        return str(self.identity.get("city") or "")

    @property
    def taboos(self) -> list[str]:
        return [t for t in ((self.category.get("voice") or {}).get("vocab_taboo") or []) if isinstance(t, str)]

    # ---- performance ---------------------------------------------------------
    @property
    def perf(self) -> dict:
        return self.merchant.get("performance") or {}

    def metric(self, name: str):
        v = self.perf.get(name)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def delta(self, name: str):
        d = (self.perf.get("delta_7d") or {})
        v = d.get(f"{name}_pct", d.get(name))
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def peer(self) -> dict:
        return self.category.get("peer_stats") or {}

    @property
    def agg(self) -> dict:
        return self.merchant.get("customer_aggregate") or {}

    @property
    def subscription(self) -> dict:
        return self.merchant.get("subscription") or {}

    # ---- offers ------------------------------------------------------------
    @property
    def active_offers(self) -> list[str]:
        return [o.get("title") for o in self.merchant.get("offers") or []
                if isinstance(o, dict) and o.get("title") and str(o.get("status", "active")).lower() == "active"]

    @property
    def expired_offers(self) -> list[str]:
        return [o.get("title") for o in self.merchant.get("offers") or []
                if isinstance(o, dict) and o.get("title") and str(o.get("status")).lower() in ("expired", "paused")]

    @property
    def priced_offer(self) -> str | None:
        """The merchant's own active service-at-price offer, if any."""
        for t in self.active_offers:
            if "₹" in t and "%" not in t:
                return t
        return self.active_offers[0] if self.active_offers else None

    def catalog_offer(self, *keywords: str) -> str | None:
        """Best category catalog offer (service-at-price) matching keywords."""
        cat = [o for o in self.category.get("offer_catalog") or [] if isinstance(o, dict) and o.get("title")]
        priced = [o for o in cat if o.get("type") == "service_at_price" or "@ ₹" in o["title"]]
        for kw in keywords:
            for o in priced + cat:
                if kw.lower() in o["title"].lower():
                    return o["title"]
        return priced[0]["title"] if priced else None

    # ---- signals / reviews / history -------------------------------------------
    @property
    def signals(self) -> dict[str, str]:
        out = {}
        for s in self.merchant.get("signals") or []:
            if isinstance(s, str):
                k, _, v = s.partition(":")
                out[k.strip()] = v.strip()
        return out

    @property
    def review_themes(self) -> list[dict]:
        return [r for r in self.merchant.get("review_themes") or [] if isinstance(r, dict)]

    @property
    def history(self) -> list[dict]:
        return [h for h in self.merchant.get("conversation_history") or [] if isinstance(h, dict)]

    # ---- category knowledge --------------------------------------------------
    @property
    def digest(self) -> list[dict]:
        return [d for d in self.category.get("digest") or [] if isinstance(d, dict)]

    def digest_item(self, item_id: str | None) -> dict | None:
        if not item_id:
            return None
        for d in self.digest:
            if d.get("id") == item_id:
                return d
        return None

    def find_digest(self, kinds: tuple = (), keywords: tuple = (), prefer_fresh: bool = True) -> dict | None:
        """Most relevant digest item: kind match + keyword overlap, fresh items first."""
        best, best_score = None, 0.0
        for idx, d in enumerate(self.digest):
            text = " ".join(str(d.get(k, "")) for k in ("title", "summary", "kind", "id")).lower()
            score = 0.0
            if kinds and str(d.get("kind", "")).lower() in kinds:
                score += 3
            score += sum(1.5 for kw in keywords if kw and kw.lower() in text)
            if prefer_fresh and d.get("id") in self.fresh_digest_ids:
                score += 2.5
            score += idx * 0.01  # later items (usually newer pushes) win ties
            if score > best_score:
                best, best_score = d, score
        return best if best_score >= 1.5 else None

    def seasonal_beat(self, month: int | None = None) -> dict | None:
        m = month or self.now.month
        for b in self.category.get("seasonal_beats") or []:
            if isinstance(b, dict) and month_in_range(m, str(b.get("month_range", ""))):
                return b
        return None

    def next_beat(self) -> dict | None:
        for step in range(1, 12):
            m = (self.now.month - 1 + step) % 12 + 1
            b = self.seasonal_beat(m)
            if b and b is not self.seasonal_beat():
                return b
        return None

    def trends(self) -> list[dict]:
        return [t for t in self.category.get("trend_signals") or [] if isinstance(t, dict)]

    # ---- customer ------------------------------------------------------------------
    @property
    def cust_name(self) -> str:
        nm = str(((self.customer or {}).get("identity") or {}).get("name") or "").strip()
        m = re.match(r"(Mr|Mrs|Ms|Shri|Smt)\.?\s+(.+)", nm)
        if m and self.is_senior:
            return f"{m.group(2)} ji"
        return nm or "there"

    @property
    def is_senior(self) -> bool:
        ident = (self.customer or {}).get("identity") or {}
        if ident.get("senior_citizen"):
            return True
        band = str(ident.get("age_band", ""))
        m = re.match(r"(\d+)", band)
        return bool(m and int(m.group(1)) >= 60)

    @property
    def relationship(self) -> dict:
        return (self.customer or {}).get("relationship") or {}

    def days_since(self, iso: str | None) -> int | None:
        d = parse_dt(iso) if iso else None
        if not d:
            return None
        return (self.now - d).days

    def days_until(self, iso: str | None) -> int | None:
        d = parse_dt(iso) if iso else None
        if not d:
            return None
        return (d - self.now).days

    @property
    def consent_scope(self) -> list[str]:
        return [str(s) for s in ((self.customer or {}).get("consent") or {}).get("scope") or []]

    # ---- what changed since the previous merchant version ---------------------
    def perf_changes(self) -> list[tuple[str, float, float]]:
        if not self.prev_merchant:
            return []
        old = self.prev_merchant.get("performance") or {}
        out = []
        for k in ("views", "calls", "directions", "leads"):
            a, b = old.get(k), self.perf.get(k)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a and a != b:
                out.append((k, float(a), float(b)))
        return out

    # ---- ranked insights ----------------------------------------------------------
    def insights(self) -> list[Insight]:
        """Observations about this merchant, strongest first.  Each is grounded."""
        out: list[Insight] = []
        ctr, peer_ctr = self.metric("ctr"), self.peer.get("avg_ctr")
        if ctr is not None and isinstance(peer_ctr, (int, float)) and peer_ctr > 0:
            gap = (ctr - peer_ctr) / peer_ctr
            if gap <= -0.15:
                out.append(Insight("ctr_below_peer",
                                   f"your profile CTR is {fmt_pct(ctr)} against a {fmt_pct(peer_ctr)} peer average",
                                   5 + min(4, -gap * 6), "loss_aversion",
                                   "refresh photos and the first line of your description", {"visibility"}))
            elif gap >= 0.25:
                out.append(Insight("ctr_above_peer",
                                   f"your CTR of {fmt_pct(ctr)} is ahead of the {fmt_pct(peer_ctr)} peer average",
                                   2.5, "momentum", "", {"positive"}))
        for metric, label in (("calls", "calls"), ("views", "profile views"), ("directions", "direction requests")):
            d = self.delta(metric)
            if d is None:
                continue
            if d <= -0.15:
                out.append(Insight(f"{metric}_drop", f"{label} are down {fmt_pct(-d)} this week",
                                   5 + min(4, -d * 8), "loss_aversion", "", {"dip", metric}))
            elif d >= 0.12:
                out.append(Insight(f"{metric}_up", f"{label} are up {fmt_pct(d)} this week",
                                   3 + min(3, d * 6), "momentum", "", {"spike", metric}))
        calls, peer_calls = self.metric("calls"), self.peer.get("avg_calls_30d")
        if calls is not None and isinstance(peer_calls, (int, float)) and peer_calls:
            if calls < peer_calls * 0.6:
                out.append(Insight("calls_below_peer",
                                   f"{fmt_int(calls)} calls in 30 days vs a peer average of {fmt_int(peer_calls)}",
                                   5, "loss_aversion", "", {"visibility"}))
        sig = self.signals
        if "stale_posts" in sig:
            days = re.sub(r"\D", "", sig["stale_posts"])
            if days:
                out.append(Insight("stale_posts", f"your last Google post went up {days} days ago",
                                   4 + min(2, int(days) / 20), "loss_aversion",
                                   "publish a fresh Google post", {"visibility"}))
        if "unverified_gbp" in sig or self.identity.get("verified") is False:
            out.append(Insight("unverified", "your Google profile is still unverified", 4.5, "loss_aversion",
                               "finish Google verification", {"visibility"}))
        if not self.active_offers:
            hook = self.catalog_offer()
            if hook:
                out.append(Insight("no_offer", "you have no live offer on your listing right now", 4,
                                   "loss_aversion", f"put a '{hook}' style offer live", {"offer"}))
        for key, label in (("lapsed_180d_plus", "180 days"), ("lapsed_90d_plus", "90 days")):
            v = self.agg.get(key)
            if isinstance(v, (int, float)) and v > 0:
                out.append(Insight("lapsed", f"{fmt_int(v)} of your customers haven't been back in {label}+",
                                   4.5 + min(3, v / 100), "loss_aversion",
                                   "send them a win-back note", {"retention"}))
                break
        sub = self.subscription
        if str(sub.get("status", "")).lower() == "expired" and sub.get("days_since_expiry"):
            out.append(Insight("expired", f"your {sub.get('plan', 'magicpin')} plan lapsed "
                                          f"{sub['days_since_expiry']} days ago, so profile upkeep is paused",
                               5, "loss_aversion", "renew", {"subscription"}))
        elif isinstance(sub.get("days_remaining"), (int, float)) and 0 < sub["days_remaining"] <= 14:
            out.append(Insight("renewal_soon", f"your {sub.get('plan', '')} plan renews in "
                                               f"{sub['days_remaining']} days".replace("  ", " "),
                               3.5, "loss_aversion", "", {"subscription"}))
        for r in self.review_themes:
            n = r.get("occurrences_30d")
            if r.get("sentiment") == "neg" and isinstance(n, (int, float)) and n >= 2:
                out.append(Insight("neg_review", f"{fmt_int(n)} reviews in the last 30 days mention "
                                                 f"{humanize(r.get('theme', 'an issue'))}",
                                   4.5, "loss_aversion", "reply to them and fix the root cause", {"reviews"}))
            elif r.get("sentiment") == "pos" and isinstance(n, (int, float)) and n >= 3:
                q = r.get("common_quote")
                txt = (f"{fmt_int(n)} reviews in the last 30 days praise {humanize(r.get('theme', ''))}"
                       + (f" (\"{q}\")" if q else ""))
                out.append(Insight("pos_review", txt, 3, "social_proof", "", {"reviews", "positive"}))
        for k, a, b in self.perf_changes()[:1]:
            change = (b - a) / a
            if abs(change) >= 0.08:
                self.allow(abs(round(change * 100)))
                word = "up" if change > 0 else "down"
                out.append(Insight("perf_update", f"your latest numbers just came in: {k} {word} from "
                                                  f"{fmt_int(a)} to {fmt_int(b)}",
                                   7, "curiosity" if change > 0 else "loss_aversion", "", {"fresh"}))
        out.sort(key=lambda i: -i.weight)
        return out


def month_in_range(month: int, rng: str) -> bool:
    toks = re.findall(r"[A-Za-z]{3}", rng or "")
    idx = [MONTHS.index(t.title()) + 1 for t in toks if t.title() in MONTHS]
    if not idx:
        return False
    if len(idx) == 1:
        return month == idx[0]
    a, b = idx[0], idx[1]
    return a <= month <= b if a <= b else (month >= a or month <= b)
