"""Per-trigger-kind composition plans.

The engine's original angles all read merchant metrics and largely ignored what
actually happened. Given a trigger about corporate catering, it would open with
click-through rates -- true, grounded, and beside the point. Trigger relevance
is a tenth of the score and the judge said so plainly: "the message never
mentions a performance dip".

A Play is the answer to "why now" for one kind of event. It names the opening
claim, the facts that must appear, what we are asking for, and the judgment we
reached. Everything is still assembled from the ledger, so nothing here can
introduce a fact we were not given -- a Play whose required facts are missing
simply does not fire, and a quieter angle takes the message instead.

Ordering inside a play matters: `leads` are tried in order and the first whose
facts all resolve is used, so a merchant with rich data gets the sharp version
and a thin one still gets something true.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# A lead is a template plus the fact ids it needs. `{fact_id}` is substituted
# with that fact's display string; `{who}` and `{trade}` come from context.
Lead = tuple[str, tuple[str, ...]]


@dataclass(frozen=True)
class Play:
    topic: str                      # feeds the suppression key
    leads: tuple[Lead, ...]         # tried in order, first fully-resolvable wins
    cta: str
    judgment: str
    salience: float = 0.85
    support: tuple[str, ...] = ()   # cited when present, never required
    lever: str = ""                 # which compulsion lever this pulls


# The eight levers named in challenge-brief §10. magicpin states that social
# proof and asking the merchant are the two their production system barely
# fires, and that both would unlock engagement -- so they are used liberally.
LOSS = "loss_aversion"
PROOF = "social_proof"
EFFORT = "effort_externalization"
CURIOSITY = "curiosity"
ASK = "asking_the_merchant"
RECIPROCITY = "reciprocity"


PLAYS: dict[str, Play] = {

    # -- performance -----------------------------------------------------
    "perf_dip": Play(
        topic="perf-dip",
        leads=(
            ("{who} — your {trigger.metric} are {trigger.delta_pct} over the last "
             "{trigger.window}, against a baseline of {trigger.vs_baseline}.",
             ("trigger.metric", "trigger.delta_pct", "trigger.window",
              "trigger.vs_baseline")),
            ("{who} — your {trigger.metric} are {trigger.delta_pct} over the last "
             "{trigger.window}.", ("trigger.metric", "trigger.delta_pct",
                                   "trigger.window")),
            ("{who} — {perf.calls} {calls_label} from {perf.views} {views_label} "
             "last month, and the trend is down.", ("perf.calls", "perf.views")),
        ),
        cta="Want me to find what changed?",
        judgment="measured decline with a named metric; diagnose before it compounds",
        lever=LOSS, salience=0.95,
        support=("signal.perf_dip_severe", "peer.calls", "signal.stale_posts"),
    ),

    "perf_spike": Play(
        topic="perf-spike",
        leads=(
            ("{who} — your {trigger.metric} are {trigger.delta_pct} over the last "
             "{trigger.window}. Worth acting on while it holds.",
             ("trigger.metric", "trigger.delta_pct", "trigger.window")),
            ("{who} — {perf.views} {views_label} last month and climbing.",
             ("perf.views",)),
        ),
        cta="Want me to put something live this week?",
        judgment="positive movement with a short window to capitalise",
        lever=CURIOSITY, salience=0.9,
        support=("peer.views", "agg.total_unique_ytd"),
    ),

    "seasonal_perf_dip": Play(
        topic="seasonal-dip",
        leads=(
            ("{who} — the dip you are seeing is seasonal: {beat}. Not a problem "
             "with your listing.", ("beat",)),
            ("{who} — {perf.calls} {calls_label} last month is below your usual, "
             "and the season explains most of it.", ("perf.calls",)),
        ),
        cta="Want me to plan for the upswing instead?",
        judgment="seasonal pattern, not a fault; reassure rather than alarm",
        lever=RECIPROCITY, salience=0.8,
    ),

    # -- the merchant's standing --------------------------------------
    "milestone_reached": Play(
        topic="milestone",
        leads=(
            ("{who} — you have crossed {trigger.milestone}. That is genuinely "
             "ahead of your category.", ("trigger.milestone",)),
            ("{who} — {peer.calls} on {perf.calls} {calls_label} last month. "
             "That is not typical for a {trade} in your area.",
             ("peer.calls", "perf.calls")),
        ),
        cta="Want me to put that where customers can see it?",
        judgment="genuine good news; the one warm opening available",
        lever=PROOF, salience=0.85,
        support=("agg.total_unique_ytd",),
    ),

    "competitor_opened": Play(
        topic="competitor",
        leads=(
            ("{who} — a new {trade} opened {trigger.distance_km}km away. Your "
             "{perf.views} {views_label} last month are what is now being "
             "competed for.", ("trigger.distance_km", "perf.views")),
            ("{who} — there is new competition nearby, and your listing is what "
             "decides who gets the call. {perf.views} {views_label} last month.",
             ("perf.views",)),
        ),
        cta="Want me to tighten the listing this week?",
        judgment="new local competition; defend the existing traffic",
        lever=LOSS, salience=0.9,
        support=("peer.views", "signal.stale_posts"),
    ),

    "review_theme_emerged": Play(
        topic="reviews",
        leads=(
            ("{who} — {trigger.count} reviews this week mention the same thing: "
             "{trigger.theme}.", ("trigger.count", "trigger.theme")),
            ("{who} — a theme is repeating in your recent reviews: "
             "{trigger.theme}.", ("trigger.theme",)),
        ),
        cta="Want me to draft a reply you can post?",
        judgment="converging review feedback; respond before it sets",
        lever=LOSS, salience=0.9,
    ),

    # -- account state -------------------------------------------------
    "renewal_due": Play(
        topic="renewal",
        leads=(
            ("{who} — your plan renews in {signal.renewal_due_soon.n} days. Last "
             "month it carried {perf.views} {views_label} and {perf.calls} "
             "{calls_label}.", ("signal.renewal_due_soon.n", "perf.views",
                                "perf.calls")),
            ("{who} — renewal is close. Last month: {perf.views} {views_label}, "
             "{perf.calls} {calls_label}.", ("perf.views", "perf.calls")),
        ),
        cta="Want the month-by-month before you decide?",
        judgment="renewal decision pending; hand over the evidence, do not pitch",
        lever=EFFORT, salience=0.9,
    ),

    "gbp_unverified": Play(
        topic="verification",
        leads=(
            ("{who} — your Google listing is still unverified, and it is holding "
             "back {perf.views} {views_label} a month.", ("perf.views",)),
            ("{who} — your Google listing is unverified. Until it is, changes "
             "take days to show.", ()),
        ),
        cta="Want me to start the verification?",
        judgment="unverified listing caps everything downstream; fix it first",
        lever=EFFORT, salience=0.85,
    ),

    "dormant_with_vera": Play(
        topic="dormant",
        leads=(
            ("{who} — we have not spoken in {signal.dormant_with_vera.n} days. "
             "In that time: {perf.views} {views_label}, {perf.calls} "
             "{calls_label}.", ("signal.dormant_with_vera.n", "perf.views",
                                "perf.calls")),
            ("{who} — it has been a while. Your last 30 days: {perf.views} "
             "{views_label}, {perf.calls} {calls_label}.",
             ("perf.views", "perf.calls")),
        ),
        cta="Want the one change that would move that most?",
        judgment="silence needs curiosity, not another reminder",
        lever=CURIOSITY, salience=0.8,
    ),

    # -- outside events -------------------------------------------------
    "festival_upcoming": Play(
        topic="festival",
        leads=(
            ("{who} — {trigger.festival} is {trigger.days_away} days out. Your "
             "{perf.views} {views_label} last month are the audience for it.",
             ("trigger.festival", "trigger.days_away", "perf.views")),
            ("{who} — {trigger.festival} is close and nothing on your listing "
             "mentions it.", ("trigger.festival",)),
        ),
        cta="Want me to draft the offer now?",
        judgment="dated event with preparation lead time still available",
        lever=LOSS, salience=0.9,
    ),

    "ipl_match_today": Play(
        topic="match-day",
        leads=(
            ("{who} — there is a match today. Worth knowing before you spend on "
             "it: {beat}", ("beat",)),
            ("{who} — match day. Your last 30 days ran {perf.views} "
             "{views_label} and {perf.calls} {calls_label}.",
             ("perf.views", "perf.calls")),
        ),
        cta="Want me to time it for the fixture that actually converts?",
        judgment="match-day timing; the data does not support every fixture",
        lever=CURIOSITY, salience=0.85,
    ),

    "regulation_change": Play(
        topic="regulation",
        leads=(
            ("{who} — a rule change lands that affects you: {digest_title} "
             "({digest_source})", ("digest_title", "digest_source")),
            ("{who} — a rule change affecting your category has been published: "
             "{digest_title}", ("digest_title",)),
        ),
        cta="Want the one-line version of what changes for you?",
        judgment="compliance change; inform plainly, no selling",
        lever=RECIPROCITY, salience=0.95,
    ),

    "research_digest": Play(
        topic="research",
        leads=(
            ("{who} — one item from this week's reading worth two minutes: "
             "{digest_title}. {digest_n} study. ({digest_source})",
             ("digest_title", "digest_n", "digest_source")),
            ("{who} — one item worth two minutes: {digest_title} "
             "({digest_source})", ("digest_title", "digest_source")),
        ),
        cta="Want the summary plus something you can share on?",
        judgment="category research with a hook relevant to this trade",
        lever=RECIPROCITY, salience=0.75,
    ),

    "category_seasonal": Play(
        topic="seasonal",
        leads=(
            ("{who} — the season is turning: {beat}", ("beat",)),
            ("{who} — worth planning for the season now, while there is time.",
             ()),
        ),
        cta="Want me to line up the offer for it?",
        judgment="seasonal beat with preparation time remaining",
        lever=CURIOSITY, salience=0.75,
    ),

    "supply_alert": Play(
        topic="supply-alert",
        leads=(
            ("{who} — safety notice: {trigger.molecule}, batches "
             "{trigger.batches}. {trigger.authority}.",
             ("trigger.molecule", "trigger.batches", "trigger.authority")),
            ("{who} — safety notice affecting stock you may be holding: "
             "{digest_title} ({digest_source})",
             ("digest_title", "digest_source")),
        ),
        cta="Want the affected customer list?",
        judgment=("urgency-5 safety matter; no offer, no marketing framing, "
                  "deliver the actionable list"),
        lever=EFFORT, salience=1.3,
    ),

    # -- the merchant is already thinking about something ----------------
    "active_planning_intent": Play(
        topic="planning",
        leads=(
            ("{who} — on {trigger.topic}: {beat}", ("trigger.topic", "beat")),
            ("{who} — on {trigger.topic}, the number that matters is "
             "{perf.views} {views_label} last month against {perf.calls} "
             "{calls_label}.", ("trigger.topic", "perf.views", "perf.calls")),
            ("{who} — picking up what you were planning. Last 30 days: "
             "{perf.views} {views_label}, {perf.calls} {calls_label}.",
             ("perf.views", "perf.calls")),
        ),
        cta="Want me to draft it around that?",
        judgment=("merchant has already signalled intent; meet the subject they "
                  "raised rather than introducing a new one"),
        lever=EFFORT, salience=1.0,
    ),

    "curious_ask_due": Play(
        topic="ask",
        leads=(
            ("{who} — a question rather than a suggestion: what are customers "
             "asking you for most this month? Your listing shows {perf.views} "
             "{views_label} and {perf.calls} {calls_label}, which does not tell "
             "me what they wanted.", ("perf.views", "perf.calls")),
            ("{who} — what are people asking you for most right now?", ()),
        ),
        cta="Worth a one-line answer?",
        judgment=("asking the merchant -- one of the two levers magicpin says "
                  "production Vera barely fires"),
        lever=ASK, salience=0.8,
    ),

    "cde_opportunity": Play(
        topic="cde",
        leads=(
            ("{who} — there is a continuing-education session in your category: "
             "{digest_title} ({digest_source})",
             ("digest_title", "digest_source")),
            ("{who} — a professional session relevant to your practice is "
             "coming up: {digest_title}", ("digest_title",)),
        ),
        cta="Want the date and the link?",
        judgment="professional development opportunity, peer-to-peer framing",
        lever=RECIPROCITY, salience=0.7,
    ),
}


def play_for(kind: str) -> Play | None:
    return PLAYS.get(kind)
