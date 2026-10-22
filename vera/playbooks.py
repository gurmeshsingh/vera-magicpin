"""Playbooks: one decision function per trigger family.

A playbook looks at the trigger and the merchant facts and DECIDES:

    * the single strongest "why now" (hook)
    * at most one supporting merchant observation (insight)
    * one concrete next step Vera will do (action / effort externalisation)
    * one call-to-action, always the last sentence (cta + cta_type)

It returns a `Draft`.  No LLM is involved, so every number in a Draft comes
from `Ctx` and is grounded.  When a trigger arrives with an empty payload
(13 of the 30 canonical test pairs), the playbook builds the why-now from the
merchant's own data instead of inventing one, and says so honestly when the
data does not support the trigger (e.g. a "perf_dip" with no actual dip).

Unknown trigger kinds are mapped to the closest family by keywords, so a
brand-new kind like "weather_heatwave" still gets a sensible, grounded message.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Callable

from .facts import (Ctx, Insight, fmt_date, fmt_int, fmt_pct, fmt_time, humanize, parse_dt,
                    pct_number)
from .lang import customer_mode, merchant_mode, pick


@dataclass
class Draft:
    family: str
    hook: str = ""
    insight: str = ""
    action: str = ""
    cta: str = ""
    cta_type: str = "binary_yes_no"
    send_as: str = "vera"
    levers: list = field(default_factory=list)
    anchor: str = ""          # the key fact (kept in template params, rationale)
    reasons: list = field(default_factory=list)  # rationale fragments
    strength: float = 5.0     # 0-10: how compelling / well-evidenced this send is
    skip: str = ""            # non-empty -> do not send (reason)
    body: str = ""            # filled in for customer drafts that are written whole
    deliverable: str = ""     # what "yes" unlocks; used by the reply engine
    mode: str = "en"


# ------------------------------------------------------------------ small helpers
def _sent(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?:" else text + "."


def _first_sentence(text: str, limit: int = 170) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    m = re.match(r"(.+?(?<!\bDr)(?<!\bMr)(?<!\bMs)(?<!\bvs)(?<!\bSt)(?<!\bNo)(?<!\s[A-Z])[.!?])(\s|$)", text)
    s = m.group(1) if m else text
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0] + "…"
    return s


def _variant(seed: str, options: list[str]) -> str:
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    return options[h % len(options)]


def _clean_title(title: str) -> str:
    """Replace ISO dates inside a title with readable ones."""
    return re.sub(r"\b(\d{4}-\d{2}-\d{2})\b", lambda m: fmt_date(m.group(1), with_year=True), title or "")


def cta_yes(ctx: Ctx, offer: str) -> str:
    """'Want me to <offer>? Reply YES.' in the merchant's language mode."""
    mode = merchant_mode(ctx.merchant, ctx.category)
    seed = str(ctx.trigger.get("id", "")) + offer
    en = _variant(seed, [f"Want me to {offer}? Reply YES.",
                         f"Shall I {offer}? Just reply YES.",
                         f"Should I {offer}? Reply YES and it's done."])
    mix = _variant(seed, [f"Want me to {offer}? Bas YES reply kar dijiye.",
                          f"Shall I {offer}? Bas YES boliye, main kar deti hoon.",
                          f"Should I {offer}? Ek YES bhejiye, baaki main sambhal lungi."])
    return pick(mode, en, mix, mix)


def _segment_count(ctx: Ctx, segment: str) -> tuple[str, float] | None:
    """Map a digest 'patient_segment' to a matching customer_aggregate count."""
    seg = humanize(segment).lower()
    words = [w for w in re.findall(r"[a-z]+", seg) if len(w) > 2]
    for k, v in ctx.agg.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 1:
            continue
        kl = k.lower()
        if words and sum(1 for w in words if w.rstrip("s") in kl) >= max(1, len(words) - 1):
            return seg, v
    return None


def _pick_insight(ctx: Ctx, exclude_keys: set = frozenset(), want_tags: set | None = None,
                  avoid_tags: set = frozenset()) -> Insight | None:
    for ins in ctx.insights():
        if ins.key in exclude_keys or ins.tags & avoid_tags:
            continue
        if want_tags and not (ins.tags & want_tags):
            continue
        return ins
    return None


_PEOPLE = {"dentists": "patients", "pharmacies": "customers", "gyms": "members",
           "salons": "clients", "restaurants": "diners"}


def people(ctx: Ctx) -> str:
    return _PEOPLE.get(ctx.slug, "customers")


# ================================================================= merchant playbooks
def pb_research(ctx: Ctx) -> Draft:
    p = ctx.payload
    item = ctx.digest_item(p.get("top_item_id") or p.get("digest_item_id")) or \
        ctx.find_digest(kinds=("research", "trend", "tech"), keywords=(humanize(p.get("topic", "")),))
    if not item:
        return pb_generic(ctx, family="research")
    d = Draft("research", levers=["curiosity", "reciprocity", "specificity"])
    source = item.get("source", "")
    title = _clean_title(item.get("title", ""))
    d.hook = f"{source} just landed one worth your time: {title}" if source else f"New this week: {title}"
    n = item.get("trial_n")
    finding = _first_sentence(item.get("summary", ""))
    if n:
        d.insight = finding.rstrip(".") + f" (sample: {fmt_int(n)} {'patients' if ctx.slug in ('dentists', 'pharmacies') else 'people'})."
    else:
        d.insight = finding
    seg = _segment_count(ctx, str(item.get("patient_segment", ""))) if item.get("patient_segment") else None
    if seg:
        d.insight += f" That maps straight onto your {fmt_int(seg[1])} {seg[0]} {people(ctx)}."
        d.reasons.append(f"linked to the merchant's {fmt_int(seg[1])} {seg[0]}")
    d.action = (f"I can pull the abstract and draft a {'patient' if ctx.slug == 'dentists' else 'customer'}-friendly "
                f"WhatsApp you can forward")
    d.cta = cta_yes(ctx, "send both")
    d.anchor = f"{title} ({source})"
    d.deliverable = "abstract + shareable WhatsApp draft"
    d.reasons.insert(0, f"fresh digest item '{title}' from {source}")
    d.strength = 6.5 + (1 if seg else 0) + (1 if item.get("id") in ctx.fresh_digest_ids else 0)
    return d


def pb_regulation(ctx: Ctx) -> Draft:
    p = ctx.payload
    item = ctx.digest_item(p.get("top_item_id") or p.get("digest_item_id") or p.get("alert_id")) or \
        ctx.find_digest(kinds=("compliance", "alert"))
    if not item:
        return pb_generic(ctx, family="compliance")
    d = Draft("compliance", levers=["urgency", "specificity", "effort_externalization"])
    title = _clean_title(item.get("title", ""))
    d.hook = f"compliance heads-up from {_clean_title(item.get('source', 'the regulator'))}: {title}"
    d.insight = _first_sentence(item.get("summary", ""), 200)
    summ = str(item.get("summary", ""))
    second = summ[len(_first_sentence(summ, 10_000)):].strip()
    if second and len(d.insight) < 140:
        d.insight += " " + _first_sentence(second, 140)
    deadline = p.get("deadline_iso") or p.get("deadline")
    days = ctx.days_until(deadline) if deadline else None
    if deadline and days is not None and days >= 0:
        ctx.allow(days)
        d.insight += f" Deadline: {fmt_date(deadline)}, {days} days from now."
    elif deadline:
        d.insight += f" Deadline: {fmt_date(deadline)}."
    act = str(item.get("actionable", "")).strip().rstrip(".")
    d.action = (f"I've turned it into a short checklist for {ctx.name} ({act[0].lower() + act[1:]})"
                if act else f"I've turned it into a short checklist for {ctx.name}")
    d.cta = cta_yes(ctx, "send the checklist here")
    d.anchor = title
    d.deliverable = "compliance checklist"
    d.reasons.append(f"regulatory change '{title}'" + (f", deadline {fmt_date(deadline)}" if deadline else ""))
    d.strength = 8
    return d


def pb_cde(ctx: Ctx) -> Draft:
    p = ctx.payload
    item = ctx.digest_item(p.get("digest_item_id") or p.get("top_item_id")) or ctx.find_digest(kinds=("cde",))
    if not item:
        return pb_generic(ctx, family="learning")
    d = Draft("learning", levers=["specificity", "effort_externalization", "curiosity"])
    when = item.get("date")
    when_txt = ""
    if when:
        when_txt = fmt_date(when) + (f", {fmt_time(when)}" if fmt_time(when) else "")
    d.hook = f"{_clean_title(item.get('title', ''))} ({item.get('source', '')}" + (f", {when_txt})" if when_txt else ")")
    bits = []
    credits = p.get("credits") or item.get("credits")
    if credits:
        bits.append(f"{credits} CDE credits" if ctx.slug == "dentists" else f"{credits} credits")
    fee = p.get("fee")
    if fee:
        bits.append(humanize(fee))
    elif item.get("actionable") and "₹" in str(item.get("actionable")):
        bits.append(str(item["actionable"]).rstrip("."))
    summary = _first_sentence(item.get("summary", ""), 150)
    d.insight = ((", ".join(bits)[0].upper() + ", ".join(bits)[1:]) + ". " if bits else "") + summary
    d.action = "I can register you and block the slot in your calendar"
    d.cta = cta_yes(ctx, "book your seat")
    d.anchor = item.get("title", "")
    d.deliverable = "registration + calendar block"
    d.reasons.append(f"learning event '{item.get('title', '')}' on {when_txt or 'upcoming date'}")
    d.strength = 5.5
    return d


def _dip_from_data(ctx: Ctx) -> tuple[str, float] | None:
    worst = None
    for m in ("calls", "views", "directions", "ctr", "leads"):
        v = ctx.delta(m)
        if v is not None and v <= -0.1 and (worst is None or v < worst[1]):
            worst = (m, v)
    return worst


def _spike_from_data(ctx: Ctx) -> tuple[str, float] | None:
    best = None
    for m in ("calls", "views", "directions", "ctr", "leads"):
        v = ctx.delta(m)
        if v is not None and v > 0 and (best is None or v > best[1]):
            best = (m, v)
    return best


_METRIC_LABEL = {"calls": "calls", "views": "profile views", "directions": "direction requests",
                 "ctr": "click-through rate", "leads": "leads", "review_count": "reviews",
                 "rating": "rating", "orders": "orders"}


def _season_note(ctx: Ctx, words=("low", "lowest", "slow", "drop", "dip", "lull", "slowdown", "drops")) -> dict | None:
    b = ctx.seasonal_beat()
    note_words = set(re.findall(r"[a-z]+", str((b or {}).get("note", "")).lower()))
    if b and note_words & set(words):
        return b
    return None


def _fix_for(ctx: Ctx, ins: Insight | None) -> tuple[str, str]:
    """(action phrase for cta_yes, deliverable) for the most likely cause."""
    if ins is None:
        hook = ctx.catalog_offer()
        return (f"draft a fresh Google post with a '{hook}' hook" if hook else "draft a fresh Google post",
                "Google post draft")
    if ins.key == "no_offer":
        hook = ctx.catalog_offer()
        return f"set up a '{hook}' offer on your listing today", "offer set-up"
    if ins.key == "unverified":
        return "walk you through Google verification right now", "verification walkthrough"
    if ins.key == "stale_posts":
        return "draft this week's Google post for you to approve", "Google post draft"
    if ins.key == "ctr_below_peer":
        return "rewrite your listing's first line and pick better cover photos", "listing refresh"
    if ins.key == "expired":
        return "reactivate your plan so upkeep restarts", "plan reactivation"
    if ins.key == "lapsed":
        return "draft a win-back WhatsApp for them", "win-back message"
    if ins.key == "neg_review":
        return "draft polite replies to those reviews", "review replies"
    return "draft a quick fix plan for this week", "fix plan"


def pb_perf_dip(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("performance_dip", levers=["loss_aversion", "specificity", "effort_externalization"])
    metric, delta = p.get("metric"), p.get("delta_pct")
    if not isinstance(delta, (int, float)):
        found = _dip_from_data(ctx)
        metric, delta = (found if found else (None, None))
    if delta is None or delta > -0.05:
        # The data does not show a dip. Say so, and lead with what does matter.
        up = _spike_from_data(ctx)
        lead = _pick_insight(ctx, avoid_tags={"spike", "positive", "dip"})
        d.family = "performance_check"
        d.hook = (f"I checked your numbers this week: {_METRIC_LABEL.get(up[0], up[0])} are up "
                  f"{fmt_pct(up[1])}, so demand for {ctx.name} is holding" if up else
                  f"I checked {ctx.name}'s numbers this week and nothing has dropped sharply")
        if lead:
            d.insight = f"The thing actually costing you: {lead.text}."
            d.levers = ["loss_aversion", "reciprocity"]
        act, deliv = _fix_for(ctx, lead)
        d.cta = cta_yes(ctx, act)
        d.deliverable = deliv
        d.anchor = lead.text if lead else ""
        d.reasons.append("trigger flagged a dip but 7-day data shows none; pivoted to the real issue"
                         + (f" ({lead.key})" if lead else ""))
        d.strength = 5.5 if lead else 3
        return d
    label = _METRIC_LABEL.get(str(metric), humanize(metric or "performance"))
    window = humanize(p.get("window", "7d")).replace("7d", "this week").replace("30d", "this month")
    d.hook = f"your {label} dropped {fmt_pct(-delta)} {window if window.startswith('this') else 'over ' + window}"
    base = p.get("vs_baseline")
    if isinstance(base, (int, float)) and base:
        d.hook += f" against a usual {fmt_int(base)}"
    season = _season_note(ctx)
    if season:
        d.insight = (f"Part of this is seasonal ({season.get('month_range')}: {season.get('note')}), "
                     f"so don't chase it with ad spend")
        d.reasons.append("dip framed against the category's seasonal pattern")
        cause = _pick_insight(ctx, avoid_tags={"dip", "spike", "positive", "visibility"}, want_tags={"retention"})
    else:
        cause = _pick_insight(ctx, exclude_keys={f"{metric}_drop"}, avoid_tags={"dip", "spike", "positive", "fresh"})
        if cause:
            d.insight = f"Likely reason: {cause.text}"
    act, deliv = _fix_for(ctx, cause)
    d.cta = cta_yes(ctx, act)
    d.deliverable = deliv
    d.anchor = f"{label} {fmt_pct(delta, signed=True)}"
    d.reasons.insert(0, f"{label} {fmt_pct(delta, signed=True)} ({'payload' if p.get('delta_pct') is not None else 'derived from 7-day data'})")
    d.strength = 6 + min(3, -delta * 5)
    return d


def pb_seasonal_dip(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("seasonal_dip", levers=["anxiety_preemption", "specificity", "reciprocity"])
    metric, delta = p.get("metric", "views"), p.get("delta_pct")
    label = _METRIC_LABEL.get(str(metric), humanize(metric))
    if isinstance(delta, (int, float)):
        d.hook = f"your {label} are {fmt_pct(-delta) if delta < 0 else fmt_pct(delta)} {'down' if delta < 0 else 'up'} this week"
    else:
        return pb_perf_dip(ctx)
    note = p.get("season_note") or (ctx.seasonal_beat() or {}).get("note", "")
    d.insight = f"That's the expected pattern ({humanize(note)}), not a problem with your listing" if note else ""
    members = ctx.agg.get("total_active_members") or ctx.agg.get("total_unique_ytd")
    if members:
        d.insight += f". The smart move now is keeping your {fmt_int(members)} {people(ctx)} engaged, not buying ads"
    d.cta = cta_yes(ctx, f"draft a retention challenge for your {people(ctx)}")
    d.deliverable = "retention challenge draft"
    d.anchor = f"{label} {fmt_pct(delta, signed=True)} (seasonal)"
    d.reasons.append("seasonal dip reframed as expected; recommend retention over acquisition")
    d.strength = 7
    return d


def pb_perf_spike(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("performance_spike", levers=["momentum", "curiosity", "effort_externalization"])
    metric, delta = p.get("metric"), p.get("delta_pct")
    if not isinstance(delta, (int, float)):
        found = _spike_from_data(ctx)
        metric, delta = (found if found else (None, None))
    if delta is None or delta <= 0:
        return pb_dormant(ctx)
    label = _METRIC_LABEL.get(str(metric), humanize(metric or "activity"))
    d.hook = f"your {label} are up {fmt_pct(delta)} this week"
    base = p.get("vs_baseline")
    if isinstance(base, (int, float)) and base:
        d.hook += f" (baseline {fmt_int(base)})"
    driver = p.get("likely_driver")
    if driver:
        d.insight = f"The likely driver is your {humanize(driver)}, so that's the format to repeat"
        d.reasons.append(f"spike driven by {humanize(driver)}")
        act = f"draft two follow-ups on the same theme" if ctx.slug else ""
        act = "draft a follow-up series on the same theme"
    else:
        lead = _pick_insight(ctx, avoid_tags={"spike", "dip", "positive"})
        if lead:
            d.insight = f"Good moment to fix the one gap left: {lead.text}"
            act, _ = _fix_for(ctx, lead)
        else:
            act = "turn this week's momentum into a Google post"
    offer = ctx.priced_offer
    if offer and "offer" not in act:
        d.insight += f" and pin your '{offer}' to it" if d.insight and driver else ""
    d.cta = cta_yes(ctx, act)
    d.deliverable = act
    d.anchor = f"{label} {fmt_pct(delta, signed=True)}"
    d.reasons.insert(0, f"{label} {fmt_pct(delta, signed=True)} this week")
    d.strength = 4.5 + min(3, delta * 10)
    return d


_ROUND_MILESTONES = (50, 100, 150, 200, 250, 300, 400, 500, 750, 1000, 1500, 2000, 2500, 3000, 5000,
                     7500, 10000, 15000, 20000, 25000, 50000, 100000)


def _nice_milestone(v: float) -> float | None:
    for target in _ROUND_MILESTONES:
        if target > v:
            return float(target) if target - v <= max(15, target * 0.15) else None
    return None


def pb_milestone(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("milestone", levers=["social_proof", "goal_gradient", "effort_externalization"])
    metric, now_v, goal = p.get("metric"), p.get("value_now"), p.get("milestone_value")
    if not isinstance(now_v, (int, float)):
        for key, label in (("total_unique_ytd", "unique customers this year"),
                           ("total_active_members", "active members"), ("review_count", "reviews")):
            v = ctx.agg.get(key) or ctx.metric(key)
            if isinstance(v, (int, float)) and v > 0:
                tgt = _nice_milestone(v)
                if tgt:
                    metric, now_v, goal = label, v, tgt
                    break
        if not isinstance(now_v, (int, float)):
            return pb_dormant(ctx)
    label = _METRIC_LABEL.get(str(metric), humanize(str(metric)))
    if isinstance(goal, (int, float)) and goal > now_v:
        gap = goal - now_v
        ctx.allow(gap, goal)
        d.hook = f"you're at {fmt_int(now_v)} {label}, just {fmt_int(gap)} short of {fmt_int(goal)}"
        if "review" in label:
            d.insight = "A quick ask to this week's happy " + people(ctx) + " usually closes a gap this small"
            act = "draft the review-request WhatsApp"
        else:
            d.insight = f"Crossing {fmt_int(goal)} makes a strong Google post for {ctx.locality or 'your area'}"
            act = "draft the celebration post so it's ready the day you cross it"
    else:
        d.hook = f"you've crossed {fmt_int(goal or now_v)} {label}"
        d.insight = "That's worth telling people about while it's fresh"
        act = "draft a thank-you post for your listing"
    d.cta = cta_yes(ctx, act)
    d.deliverable = act
    d.anchor = d.hook
    d.reasons.append(f"milestone: {fmt_int(now_v)} → {fmt_int(goal) if goal else ''} {label}")
    d.strength = 5
    return d


def pb_competitor(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("competition", levers=["loss_aversion", "curiosity", "social_proof"])
    name, dist, offer, opened = p.get("competitor_name"), p.get("distance_km"), p.get("their_offer"), p.get("opened_date")
    if name:
        d.hook = f"{name} opened {dist} km from you" if dist else f"{name} opened near you"
        if opened:
            d.hook += f" on {fmt_date(opened)}"
        if offer:
            d.hook += f", leading with '{offer}'"
        mine = ctx.priced_offer
        theirs_p = re.search(r"₹\s?([\d,]+)", str(offer or ""))
        mine_p = re.search(r"₹\s?([\d,]+)", str(mine or ""))
        if theirs_p and mine_p:
            a, b = int(theirs_p.group(1).replace(",", "")), int(mine_p.group(1).replace(",", ""))
            if a < b:
                ctx.allow(b - a)
                d.insight = f"That's ₹{fmt_int(b - a)} under your '{mine}'. I wouldn't match on price"
    else:
        d.hook = f"a new competitor has opened in your catchment around {ctx.locality}" if ctx.locality \
            else "a new competitor has opened near you"
    pos = next((r for r in ctx.review_themes if r.get("sentiment") == "pos"), None)
    rep = ctx.agg.get("repeat_customer_pct") or ctx.agg.get("retention_6mo_pct") or ctx.agg.get("retention_3mo_pct")
    if pos and pos.get("common_quote"):
        lead = f"your reviews already say \"{pos['common_quote']}\""
        d.insight = (d.insight + "; " + lead) if d.insight else f"Your edge: {lead}"
        act = "draft a Google post that leads with what your " + people(ctx) + " already praise"
    elif isinstance(rep, (int, float)) and rep > 0:
        lead = f"{fmt_pct(rep)} of your {people(ctx)} come back"
        d.insight = (d.insight + f". Protect the base: {lead}") if d.insight else f"Protect the base: {lead}"
        base_offer = ctx.priced_offer
        act = (f"draft a thank-you note for your regulars built on your '{base_offer}'" if base_offer
               else "draft a thank-you note for your regulars")
    else:
        ins = _pick_insight(ctx, avoid_tags={"positive"})
        if ins:
            d.insight = (d.insight + ". " if d.insight else "") + f"Close your gap first: {ins.text}"
        act, _ = _fix_for(ctx, ins)
    if d.insight and not d.insight.endswith((".", "!", "?")):
        d.insight += ""
    d.cta = cta_yes(ctx, act)
    d.deliverable = act
    d.anchor = d.hook
    d.reasons.append(f"competitor event: {name or 'unnamed new competitor'}")
    d.strength = 6.5 if name else 5
    return d


_ASK_BY_TEMPLATE = {
    "what_service_in_demand_this_week": "which service are people asking for most this week",
    "what_dish_selling_most": "which dish is moving fastest this week",
}
_ASK_BY_CATEGORY = {
    "dentists": "what's the most-asked treatment at your chair this week",
    "salons": "which service are people asking for most this week",
    "restaurants": "which dish is moving fastest this week",
    "gyms": "which class or slot is filling up fastest this week",
    "pharmacies": "which product are customers asking for that you keep running short on",
}


def pb_curious(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("curious_ask", cta_type="open_ended", levers=["asking_the_merchant", "reciprocity"])
    q = _ASK_BY_TEMPLATE.get(str(p.get("ask_template", "")), "") or _ASK_BY_CATEGORY.get(ctx.slug,
                                                                                       "what are customers asking you about most this week")
    lead = _pick_insight(ctx, want_tags={"spike", "positive", "fresh"}) or _pick_insight(ctx)
    if lead:
        d.hook = f"quick one. {lead.text[0].upper() + lead.text[1:]}"
        d.reasons.append(f"opened with {lead.key}")
    else:
        d.hook = "quick one"
    d.action = _sent(q[0].upper() + q[1:] + "?")
    d.cta = ("Tell me and I'll turn it into a Google post plus a ready WhatsApp reply for enquiries."
             if merchant_mode(ctx.merchant, ctx.category) == "en" else
             "Bata dijiye, main usse ek Google post aur enquiries ke liye ready WhatsApp reply bana dungi.")
    d.deliverable = "Google post + WhatsApp reply template"
    d.anchor = q
    d.reasons.insert(0, "curiosity/ask-the-merchant cadence")
    d.strength = 4.5
    return d


def pb_dormant(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("re_engage", levers=["curiosity", "reciprocity", "loss_aversion"])
    days = p.get("days_since_last_merchant_message")
    last_topic = humanize(p.get("last_topic", "")) if p.get("last_topic") else ""
    avoid = {"subscription"} if "subscription" in last_topic or "expir" in last_topic else set()
    lead = _pick_insight(ctx, avoid_tags=avoid | {"positive"}) or _pick_insight(ctx)
    intro = (f"it's been {days} days since we last spoke, so here's something new" if days
             else "spotted something on your listing worth two minutes")
    if lead:
        d.hook = f"{intro}: {lead.text}"
        act, deliv = _fix_for(ctx, lead)
        if lead.key.endswith("_drop"):
            cause = _pick_insight(ctx, exclude_keys={lead.key}, avoid_tags={"dip", "spike", "positive", "fresh"})
            if cause:
                d.insight = f"Likely reason: {cause.text}"
                act, deliv = _fix_for(ctx, cause)
        d.reasons.append(f"fresh hook {lead.key}" + (f" (not the old '{last_topic}' topic)" if last_topic else ""))
    else:
        tr = max(ctx.trends(), key=lambda t: t.get("delta_yoy", 0), default=None)
        if tr:
            d.hook = f"{intro}: searches for \"{tr['query']}\" are up {fmt_pct(tr['delta_yoy'])} year on year"
            act, deliv = "draft a post that catches that search", "Google post draft"
        else:
            d.hook = intro
            act, deliv = "run a quick check of your listing and send you the top fix", "listing check"
    d.cta = cta_yes(ctx, act)
    d.deliverable = deliv
    d.anchor = lead.text if lead else ""
    d.strength = 4.5 + (1.5 if lead and lead.weight > 6 else 0)
    return d


def pb_festival(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("festival", levers=["specificity", "loss_aversion", "effort_externalization"])
    fest, date, days = p.get("festival"), p.get("date"), p.get("days_until")
    rel = p.get("category_relevance")
    if isinstance(rel, list) and rel and ctx.slug not in rel:
        d.skip = f"{fest or 'festival'} flagged as not relevant to {ctx.slug}; holding back (restraint)"
        return d
    if not isinstance(days, (int, float)) and date:
        days = ctx.days_until(date)
        if days is not None:
            ctx.allow(days)
    if not fest:
        beat = ctx.seasonal_beat() or ctx.next_beat()
        if not beat:
            return pb_dormant(ctx)
        d.family = "season"
        d.hook = f"season check for {ctx.name} ({beat.get('month_range')}): {humanize(beat.get('note'))}"
        members = ctx.agg.get("total_active_members") or ctx.agg.get("total_unique_ytd")
        if "retention" in str(beat.get("note")) and members:
            d.insight = f"So the play is your {fmt_int(members)} existing {people(ctx)}, not new ads"
            act = f"draft a members-only challenge for this window"
        else:
            offer = ctx.priced_offer or ctx.catalog_offer()
            act = f"draft a seasonal post around '{offer}'" if offer else "draft a seasonal post"
        d.cta = cta_yes(ctx, act)
        d.deliverable = act
        d.anchor = beat.get("note", "")
        d.reasons.append(f"no festival named in trigger; used seasonal beat {beat.get('month_range')}")
        d.strength = 4
        return d
    when = f" ({fmt_date(date)})" if date else ""
    if isinstance(days, (int, float)) and days > 45:
        d.hook = f"{fest}{when} is {int(days)} days out, too early to promote"
        far_beat = ctx.seasonal_beat((parse_dt(date).month) if parse_dt(date) else None)
        near = ctx.seasonal_beat()
        if far_beat:
            d.hook += f", but worth planning for. Your {far_beat.get('month_range')} pattern: {humanize(far_beat.get('note'))}"
        if near and near is not far_beat:
            d.insight = f"The nearer opportunity is right now ({near.get('month_range')}): {humanize(near.get('note'))}"
            nw = tuple(w for w in re.findall(r"[a-z]{5,}", str(near.get("note", "")).lower()))
            tip = ctx.find_digest(kinds=("seasonal", "trend"), keywords=nw)
            m = re.search(r"'([^']*@ ₹[\d,]+)'", str((tip or {}).get("actionable", "")))
            if m:
                d.insight += f". {tip.get('source', 'Category data')} suggests a '{m.group(1)}' offer for exactly this"
                act = f"set up the '{m.group(1)}' offer now"
                d.reasons.append(f"near-term move from digest '{tip.get('id')}'")
            else:
                offer = ctx.priced_offer or ctx.catalog_offer()
                act = f"draft a post for this window around '{offer}'" if offer else "draft a post for this window"
        else:
            act = f"block a {fest} launch date and draft the package in advance"
        d.reasons.insert(0, f"{fest} is {int(days)} days away: plan, don't promote yet")
        d.strength = 4
    else:
        d.hook = f"{fest}{when} is {int(days)} days away" if isinstance(days, (int, float)) else f"{fest} is coming up{when}"
        offer = ctx.priced_offer or ctx.catalog_offer()
        d.insight = (f"{people(ctx).capitalize()} start booking now; your '{offer}' is the natural hook"
                     if offer else f"{people(ctx).capitalize()} start planning now")
        act = f"set up a {fest} version of '{offer}' and post it" if offer else f"draft your {fest} post"
        d.reasons.append(f"{fest} within {days} days")
        d.strength = 7
    d.cta = cta_yes(ctx, act)
    d.deliverable = act
    d.anchor = f"{fest}{when}"
    return d


def pb_gbp(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("verification", levers=["loss_aversion", "effort_externalization"])
    d.hook = "your Google Business Profile is still unverified"
    up = p.get("estimated_uplift_pct")
    if isinstance(up, (int, float)) and up > 0:
        d.hook += f", which is costing you an estimated {fmt_pct(up)} in visibility"
    path = p.get("verification_path")
    views = ctx.metric("views")
    d.insight = (f"You already get {fmt_int(views)} views a month without the verified badge. " if views else "")
    if path:
        d.insight += f"Verification is by {humanize(path).replace(' or ', ' or by ')}, and I can guide each step"
    d.cta = cta_yes(ctx, "start the verification with you now")
    d.deliverable = "verification walkthrough"
    d.anchor = d.hook
    d.reasons.append("unverified GBP" + (f", est. uplift {fmt_pct(up)}" if isinstance(up, (int, float)) else ""))
    d.strength = 7
    return d


def pb_renewal(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("renewal", levers=["loss_aversion", "specificity"])
    days = p.get("days_remaining") or ctx.subscription.get("days_remaining")
    plan = p.get("plan") or ctx.subscription.get("plan") or "magicpin"
    amt = p.get("renewal_amount")
    if str(ctx.subscription.get("status", "")).lower() == "expired" and not p.get("days_remaining"):
        return pb_winback(ctx)
    if isinstance(days, (int, float)) and days > 30 and not p.get("days_remaining"):
        d = pb_dormant(ctx)
        d.reasons.append(f"renewal is {days} days away, too early to ask; led with value instead")
        return d
    d.hook = f"your {plan} plan renews in {days} days" if days else f"your {plan} plan is up for renewal"
    if isinstance(amt, (int, float)):
        d.hook += f" (₹{fmt_int(amt)})"
    v, c = ctx.metric("views"), ctx.metric("calls")
    if v and c:
        d.insight = (f"In the last 30 days it brought {fmt_int(v)} profile views and {fmt_int(c)} calls. "
                     f"If it lapses, profile upkeep and posts pause")
    d.cta = cta_yes(ctx, f"renew it on the same {plan} plan")
    d.deliverable = "renewal"
    d.anchor = d.hook
    d.reasons.append(f"renewal in {days} days")
    d.strength = 6.5
    return d


def pb_winback(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("winback", levers=["loss_aversion", "specificity"])
    days = p.get("days_since_expiry") or ctx.subscription.get("days_since_expiry")
    dip = p.get("perf_dip_pct")
    d.hook = f"it's been {days} days since your plan lapsed" if days else "your plan has lapsed"
    if isinstance(dip, (int, float)) and dip:
        d.hook += f", and your listing performance is down {fmt_pct(abs(dip))} since"
    lap = p.get("lapsed_customers_added_since_expiry")
    if isinstance(lap, (int, float)) and lap:
        d.insight = f"{fmt_int(lap)} more {people(ctx)} have gone quiet in that time"
    d.cta = cta_yes(ctx, "reactivate it so upkeep restarts this week")
    d.deliverable = "plan reactivation"
    d.anchor = d.hook
    d.reasons.append("win-back after expiry")
    d.strength = 6
    return d


def pb_ipl(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("event", levers=["specificity", "contrarian_insight", "effort_externalization"])
    match = p.get("match", "tonight's match")
    t = fmt_time(p.get("match_time_iso", "")) if p.get("match_time_iso") else ""
    d.hook = f"{match} is on today" + (f" at {t}" if t else "") + (f", {p['venue']}" if p.get("venue") else "")
    item = ctx.find_digest(kinds=("seasonal", "trend"), keywords=("ipl", "match"))
    weeknight = p.get("is_weeknight")
    deliv_orders, dine = ctx.agg.get("delivery_orders_30d"), ctx.agg.get("dine_in_orders_30d")
    combo = ctx.catalog_offer("match")
    share = None
    if isinstance(deliv_orders, (int, float)) and isinstance(dine, (int, float)) and deliv_orders + dine > 0:
        share = deliv_orders / (deliv_orders + dine)
        ctx.allow(round(share * 100))
    if weeknight is False:
        if item:
            d.insight = f"Weekend matches pull people home: {_first_sentence(item.get('summary', ''), 160)}"
        if share is not None:
            d.insight += f" Delivery is already {round(share * 100)}% of your orders ({fmt_int(deliv_orders)} of {fmt_int(deliv_orders + dine)})"
        d.insight += ". So skip the dine-in push tonight and go after home-watch orders"
        act = f"set up a '{combo}' for delivery before the toss" if combo else "set up a match-night delivery combo"
        d.reasons.append("weekend match: data says covers fall, so pivot to delivery")
    else:
        if item:
            d.insight = _first_sentence(item.get("summary", ""), 170)
        act = f"put a '{combo}' live for tonight's dine-in crowd" if combo else "put a match-night combo live"
        d.reasons.append("weeknight match: push dine-in")
    own = ctx.priced_offer
    if own and "Tue-Thu" in own and weeknight is False:
        d.insight += f" (your '{own}' doesn't apply today)"
    d.cta = cta_yes(ctx, act)
    d.deliverable = act
    d.anchor = d.hook
    d.strength = 7
    return d


def pb_planning(ctx: Ctx) -> Draft:
    """Merchant asked for a plan: deliver a first draft immediately, no qualifying questions."""
    p = ctx.payload
    d = Draft("planning", levers=["effort_externalization", "specificity"])
    topic = humanize(p.get("intent_topic") or p.get("topic") or "your plan")
    title = topic.title().replace("Kids", "Kids'") if "kids" in topic else topic.title()
    lines = []
    base = ctx.priced_offer
    if base:
        lines.append(f"Price anchor: your '{base}'")
    tw = set(re.findall(r"[a-z]+", topic.lower()))
    trend = next((t for t in ctx.trends() if set(re.findall(r"[a-z]+", str(t.get("query", "")).lower())) & (tw | {"lunch", "thali"} if "thali" in tw else tw)), None)
    if "corporate" in tw or "office" in tw or "bulk" in tw:
        lines.append(f"Who: offices around {ctx.locality}, ordered by the admin or facilities team" if ctx.locality
                     else "Who: nearby offices, ordered by the admin team")
        lines.append("How: pre-orders the day before, one monthly bill per company")
    if "kids" in tw or "children" in tw:
        lines.append("Who: parents in " + (ctx.locality or "your area") + ", school-holiday batches")
        sched = ctx.find_digest(keywords=("slot", "morning", "schedule"))
        if sched:
            lines.append("When: weekday mornings. " + _first_sentence(sched.get("summary", ""), 140))
        else:
            lines.append("When: weekday mornings while schools are out")
    if trend:
        lines.append(f"Demand: \"{trend['query']}\" searches are up {fmt_pct(trend['delta_yoy'])} year on year")
    beat = ctx.seasonal_beat()
    beat_words = set(re.findall(r"[a-z]{4,}", str((beat or {}).get("note", "")).lower()))
    if beat and len(lines) < 5 and beat_words & (tw | {"school", "holiday", "summer", "corporate", "office"} & tw):
        lines.append(f"Timing ({beat.get('month_range')}): {humanize(beat.get('note'))}")
    if len(lines) < 2:
        ins = _pick_insight(ctx)
        if ins:
            lines.append(f"Context: {ins.text}")
    d.hook = f"here's a first cut of the {title}:\n" + "\n".join(f"• {l}" for l in lines)
    d.cta = cta_yes(ctx, "publish it on your listing and draft the launch message")
    d.deliverable = f"{title} published + launch message"
    d.anchor = title
    d.reasons.append(f"merchant asked for a {topic} plan: delivered a draft instead of more questions")
    d.strength = 8.5
    return d


def pb_supply(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("alert", levers=["urgency", "specificity", "reciprocity"])
    item = ctx.digest_item(p.get("alert_id") or p.get("top_item_id")) or ctx.find_digest(kinds=("alert", "supply"))
    mol = p.get("molecule", "")
    batches = p.get("affected_batches") or []
    mfr = p.get("manufacturer")
    src = (item or {}).get("source", "")
    d.hook = f"recall alert{(' (' + src + ')') if src else ''}: {mol} batches {', '.join(batches)}" if batches \
        else f"recall alert{(' (' + src + ')') if src else ''}: {mol or (item or {}).get('title', '')}"
    if mfr:
        d.hook += f" from {mfr}"
    if item:
        d.insight = _first_sentence(item.get("summary", ""), 160)
        rest = str(item.get("summary", ""))[len(_first_sentence(item.get("summary", ""), 10_000)):]
        if "risk" in rest.lower():
            d.insight += " " + _first_sentence(rest.strip(), 150)
    rx = ctx.agg.get("chronic_rx_count")
    if rx:
        d.insight += f" Worth checking which of your {fmt_int(rx)} chronic-Rx customers got these batches."
    d.cta = cta_yes(ctx, "draft the customer WhatsApp and the replacement-pickup note")
    d.deliverable = "customer notice + replacement workflow"
    d.anchor = d.hook
    d.reasons.append(f"product recall: {mol} {', '.join(batches)}")
    d.strength = 9
    return d


def pb_category_seasonal(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("demand_shift", levers=["specificity", "reciprocity"])
    parsed = []
    for t in p.get("trends") or []:
        m = re.match(r"(.+?)_demand_([+-]?\d+)", str(t))
        if m:
            parsed.append((humanize(m.group(1)).replace("cold cough", "cold & cough"), int(m.group(2))))
    if not parsed:
        return pb_generic(ctx, family="demand_shift")
    parsed.sort(key=lambda x: -x[1])
    up = [f"{n} +{v}%" for n, v in parsed if v > 0]
    down = [f"{n} {v}%" for n, v in parsed if v < 0]
    season = humanize(p.get("season", "")).replace("2026", "").strip()
    d.hook = f"the {season} shift is showing up: " if season else "demand is shifting: "
    d.hook += ", ".join(up) + (f"; {', '.join(down)}" if down else "")
    if p.get("shelf_action_recommended"):
        tops = [n for n, v in parsed if v > 0][:2]
        d.insight = f"Move {' and '.join(tops)} to the counter" + (f" and trim {parsed[-1][0]} stock" if down else "")
    n = ctx.agg.get("total_unique_ytd")
    rep = ctx.agg.get("repeat_customer_pct")
    if n:
        d.insight += f". Your {fmt_int(n)} customers" + (f" ({fmt_pct(rep)} repeat)" if rep else "") + \
                     " will buy these from whoever reminds them first"
    d.cta = cta_yes(ctx, "send a summer-essentials WhatsApp to your regulars")
    d.deliverable = "seasonal customer note"
    d.anchor = d.hook
    d.reasons.append("category demand shift with shelf action")
    d.strength = 6.5
    return d


def pb_review_theme(ctx: Ctx) -> Draft:
    p = ctx.payload
    d = Draft("reviews", levers=["specificity", "reciprocity", "loss_aversion"])
    theme, n, quote, trend = p.get("theme"), p.get("occurrences_30d"), p.get("common_quote"), p.get("trend")
    if not theme:
        r = next((r for r in ctx.review_themes if r.get("sentiment") == "neg"), None) or \
            (ctx.review_themes[0] if ctx.review_themes else None)
        if not r:
            return pb_dormant(ctx)
        theme, n, quote = r.get("theme"), r.get("occurrences_30d"), r.get("common_quote")
    d.hook = f"{fmt_int(n)} reviews in the last 30 days mention {humanize(theme)}" if n else \
        f"a review theme is building around {humanize(theme)}"
    if quote:
        d.hook += f": \"{quote}\""
    if trend:
        d.hook += f" ({humanize(trend)})"
    neg = any(w in str(theme).lower() for w in ("wait", "price", "rude", "late", "dirty", "cold", "delay")) or \
        any(r.get("theme") == theme and r.get("sentiment") == "neg" for r in ctx.review_themes)
    if neg:
        d.insight = "Left alone, this becomes the first thing new " + people(ctx) + " read"
        act = "draft polite replies to those reviews and a fix you can announce"
    else:
        d.insight = "That's social proof worth putting front and centre"
        act = "turn it into a Google post"
    d.cta = cta_yes(ctx, act)
    d.deliverable = act
    d.anchor = d.hook
    d.reasons.append(f"review theme {theme} x{n}")
    d.strength = 6
    return d


_EVENT_SYNONYMS = {
    "heat": ("summer", "heat", "ors", "sunscreen", "hydration", "cold beverages"),
    "rain": ("monsoon", "rain", "delivery", "anti-fungal"), "monsoon": ("monsoon", "rain", "delivery"),
    "cold": ("winter", "cold", "respiratory", "cough"), "winter": ("winter", "cold", "respiratory"),
    "pollution": ("respiratory", "allergic", "mask"), "exam": ("exam", "stress", "students"),
    "wedding": ("wedding", "bridal"), "school": ("school", "holiday", "kids", "pediatric"),
}
_DISRUPTION = ("closed", "closure", "traffic", "jam", "strike", "bandh", "protest", "flood", "waterlogging",
               "diversion", "shutdown", "maintenance", "blocked")


def _payload_phrase(p: dict) -> str:
    bits = []
    for k, v in p.items():
        kl = k.lower()
        if kl in ("placeholder", "metric_or_topic", "merchant_id", "customer_id", "category") or isinstance(v, (dict, list, bool)):
            continue
        if v is None or len(str(v)) > 90:
            continue
        if "temp" in kl and isinstance(v, (int, float)):
            bits.append(f"{v}°C")
        elif kl in ("headline", "title", "event", "name", "festival", "match"):
            bits.insert(0, str(v))
        elif kl in ("city", "locality", "area", "venue"):
            bits.append(f"in {v}")
        elif kl in ("days", "duration_days"):
            bits.append(f"for {v} days")
        elif isinstance(v, str) and parse_dt(v) and re.match(r"\d{4}-", v):
            bits.append(f"on {fmt_date(v)}")
        elif isinstance(v, (int, float)) and "pct" in kl:
            bits.append(f"{humanize(k).replace(' pct', '')} {fmt_pct(v, signed=True)}")
        elif isinstance(v, (int, float)):
            bits.append(f"{humanize(k)} {v}")
        else:
            bits.append(humanize(v))
    return ", ".join(bits[:4])


def pb_generic(ctx: Ctx, family: str = "update") -> Draft:
    """Unknown trigger: say what happened in plain words, connect it to category knowledge, one action."""
    p = ctx.payload
    kind = humanize(ctx.trigger.get("kind") or "update")
    d = Draft(family, levers=["specificity", "reciprocity"])
    phrase = _payload_phrase(p)
    label = re.sub(r"\b(event|alert|update|upcoming)\b", "", kind).strip() or kind
    d.hook = f"heads-up: {label}" + (f" ({phrase})" if phrase else "")
    text_all = (kind + " " + " ".join(str(v) for v in p.values())).lower()
    words = set(re.findall(r"[a-z]{4,}", text_all))
    for k, syn in _EVENT_SYNONYMS.items():
        if k in text_all:
            words |= set(syn)
    item = ctx.find_digest(keywords=tuple(sorted(words)))
    beat = next((b for b in ctx.category.get("seasonal_beats") or []
                 if isinstance(b, dict) and words & set(re.findall(r"[a-z]{4,}", str(b.get("note", "")).lower()))), None)
    disrupt = any(w in text_all for w in _DISRUPTION)
    offer = ctx.priced_offer
    if disrupt:
        share = ctx.agg.get("delivery_share_pct")
        d.insight = ("Expect fewer walk-ins that day, so lean on delivery and pre-bookings"
                     + (f"; delivery is already {fmt_pct(share)} of your orders" if isinstance(share, (int, float)) else ""))
        act = "send your regulars a heads-up with an order-ahead option"
        d.reasons.append("local disruption: shift to delivery / pre-booking")
    elif item:
        d.insight = f"What it means for {ctx.slug}: {_first_sentence(item.get('summary', '') or item.get('title', ''), 170)}"
        tip = str(item.get("actionable", "")).strip().rstrip(".")
        if tip:
            d.insight += f" Suggested move: {tip[0].lower() + tip[1:]}"
        act = "set that up for you this week" if tip else "draft a timely post for your listing"
        d.reasons.append(f"linked to digest '{item.get('id')}'")
    elif beat:
        d.insight = f"It lines up with {beat.get('month_range')}: {humanize(beat.get('note'))}"
        act = f"draft a timely post around your '{offer}'" if offer else "draft a timely post for your listing"
    else:
        ins = _pick_insight(ctx)
        if ins:
            d.insight = f"Worth pairing with this: {ins.text}"
            act, _ = _fix_for(ctx, ins)
        else:
            act = f"draft a timely post around your '{offer}'" if offer else "draft a timely post for your listing"
    d.cta = cta_yes(ctx, act)
    d.deliverable = act
    d.anchor = d.hook
    d.reasons.insert(0, f"event '{kind}'" + (f": {phrase}" if phrase else ""))
    d.strength = 3.5 + (1.5 if (item or disrupt or beat) else 0) + (1 if phrase else 0)
    return d


# ================================================================= customer playbooks
def _consent_ok(ctx: Ctx, needs: tuple) -> bool:
    scope = set(ctx.consent_scope)
    if not scope:
        return False
    return bool(scope & set(needs)) or "promotional_offers" in scope


def _cust_open(ctx: Ctx, mode: str) -> str:
    nm = ctx.cust_name
    if ctx.is_senior:
        return pick(mode, f"Namaste {nm}, {ctx.name} here.", f"Namaste {nm}, {ctx.name} se.", f"Namaste {nm}, {ctx.name} se.")
    return pick(mode, f"Hi {nm}, {ctx.name} here.", f"Hi {nm}, {ctx.name} se.", f"Namaste {nm}, {ctx.name} se.")


def _slots(p: dict) -> list[str]:
    out = []
    for s in p.get("available_slots") or p.get("next_session_options") or []:
        if isinstance(s, dict):
            lab = s.get("label") or (fmt_date(s.get("iso", "")) + " " + fmt_time(s.get("iso", ""))).strip()
            if lab:
                out.append(lab)
        elif isinstance(s, str):
            out.append(fmt_date(s) + (" " + fmt_time(s) if fmt_time(s) else "") if parse_dt(s) else s)
    return out[:3]


def _short_slot(label: str, others: list[str]) -> str:
    first = label.split()[0].rstrip(",") if label.split() else label
    return first if sum(1 for o in others if o.split() and o.split()[0].rstrip(",") == first) == 1 else label


def _slot_cta(mode: str, slots: list[str]) -> str:
    if len(slots) >= 2:
        nums = ", ".join(f"{i + 1} for {_short_slot(s, slots)}" for i, s in enumerate(slots))
        return pick(mode, f"Reply {nums}, or tell us a time that suits you.",
                    f"Reply {nums}, ya apna time bata dijiye.",
                    f"{nums} reply kijiye, ya apna samay bataiye.")
    return pick(mode, "Reply YES and we'll hold a slot for you.",
                "Reply YES, hum aapke liye slot hold kar lenge.",
                "YES reply kijiye, hum aapka slot rakh lenge.")


def _cust_offer(ctx: Ctx, *kw: str) -> str | None:
    """Only the merchant's own active offers are quoted to customers (never catalog prices)."""
    for o in ctx.active_offers:
        if any(k in o.lower() for k in kw):
            return o
    return None


def pb_recall(ctx: Ctx) -> Draft:
    p = ctx.payload
    mode = customer_mode(ctx.customer)
    d = Draft("recall", send_as="merchant_on_behalf", cta_type="multi_choice_slot",
              levers=["loss_aversion", "effort_externalization", "specificity"], mode=mode)
    default_svc = {"dentists": "check-up", "gyms": "next session", "salons": "next appointment",
                   "pharmacies": "refill", "restaurants": "next visit"}.get(ctx.slug, "check-up")
    service = humanize(p.get("service_due") or default_svc).replace("_", " ")
    due = p.get("due_date")
    last = p.get("last_service_date") or ctx.relationship.get("last_visit")
    since = ctx.days_since(last)
    if since is not None and since >= 60:
        months = round(since / 30)
        ctx.allow(months)
        lead = pick(mode, f"It's been {months} months since your last visit, and your {service} is due"
                          + (f" on {fmt_date(due)}." if due else "."),
                    f"Aapki last visit ko {months} mahine ho gaye, aur aapki {service} "
                    + (f"{fmt_date(due)} ko due hai." if due else "due hai."),
                    f"Aapki pichhli visit ko {months} mahine ho gaye hain, {service} "
                    + (f"{fmt_date(due)} ko due hai." if due else "ka samay ho gaya hai."))
    else:
        lead = pick(mode, f"Your {service} is due" + (f" on {fmt_date(due)}." if due else " soon."),
                    f"Aapki {service} " + (f"{fmt_date(due)} ko due hai." if due else "due hone wali hai."),
                    f"Aapki {service} ka samay " + (f"{fmt_date(due)} ko hai." if due else "aa gaya hai."))
        if last and not due:
            lead = lead[:-1] + pick(mode, f" (last visit {fmt_date(last)}).", f" (last visit {fmt_date(last)}).",
                                    f" (pichhli visit {fmt_date(last)}).")
    slots = _slots(p)
    offer = _cust_offer(ctx, *re.findall(r"[a-z]{4,}", service.lower()), "clean", "check", "consult") or \
        (ctx.active_offers[0] if ctx.active_offers else None)
    mid = ""
    if slots:
        pref = str(((ctx.customer or {}).get("preferences") or {}).get("preferred_slots", ""))
        tag = pick(mode, " (evening slots, as you prefer)", " (aapke pasand ke evening slots)",
                   " (shaam ke slot, jaise aapko pasand hai)") if "evening" in pref and all(
            re.search(r"(5|6|7|8)\s?pm", s.lower()) for s in slots) else ""
        mid = pick(mode, f"We've kept {len(slots)} slots for you{tag}: {' or '.join(slots)}.",
                   f"Aapke liye {len(slots)} slots ready hain{tag}: {' ya '.join(slots)}.",
                   f"Aapke liye {len(slots)} slot rakhe hain{tag}: {' ya '.join(slots)}.")
        ctx.allow(len(slots))
    if offer:
        same = any(w in offer.lower() for w in re.findall(r"[a-z]{4,}", service.lower()))
        mid += " " + (pick(mode, f"{offer} as before.", f"{offer}, same as before.", f"{offer}.") if same else
                      pick(mode, f"{offer} is on right now.", f"Abhi {offer} chal raha hai.", f"Abhi {offer} chal raha hai."))
    d.body = " ".join(x for x in (_cust_open(ctx, mode), lead, mid.strip(), _slot_cta(mode, slots)) if x)
    d.cta_type = "multi_choice_slot" if len(slots) >= 2 else "binary_yes_no"
    d.anchor = f"{service} due {fmt_date(due) if due else ''}".strip()
    d.deliverable = "booking confirmation"
    d.reasons.append(f"customer recall: {service}" + (f", {len(slots)} real slots offered" if slots else ""))
    d.strength = 7.5 if slots else 5.5
    return d


def pb_appointment(ctx: Ctx) -> Draft:
    p = ctx.payload
    mode = customer_mode(ctx.customer)
    d = Draft("appointment", send_as="merchant_on_behalf", cta_type="binary_confirm_cancel",
              levers=["specificity", "commitment"], mode=mode)
    when = p.get("appointment_iso") or p.get("slot_iso") or p.get("time_iso")
    svc = humanize(p.get("service", "")) if p.get("service") else ""
    t = fmt_time(when) if when else ""
    what = (svc + " ") if svc else ""
    at = ""
    line = pick(mode, f"Just a reminder: your {what}appointment{at} is tomorrow" + (f" at {t}" if t else "") + ".",
                f"Reminder: kal aapka {what}appointment hai" + (f", {t} baje" if t else "") + ".",
                f"Yaad dila rahe hain: kal aapka {what}appointment hai" + (f", {t} baje" if t else "") + ".")
    cta = pick(mode, "Reply 1 to confirm or 2 to reschedule.",
               "Confirm karne ke liye 1, reschedule ke liye 2 reply kijiye.",
               "Confirm ke liye 1, samay badalne ke liye 2 reply kijiye.")
    opener = _cust_open(ctx, mode)
    if ctx.locality:
        opener = opener.replace(ctx.name, f"{ctx.name}, {ctx.locality}", 1)
    d.body = f"{opener} {line} {cta}"
    d.anchor = "appointment tomorrow" + (f" {t}" if t else "")
    d.deliverable = "appointment confirmation"
    d.reasons.append("appointment reminder for tomorrow" + ("" if when else " (no time in payload, so none stated)"))
    d.strength = 6
    return d


def pb_refill(ctx: Ctx) -> Draft:
    p = ctx.payload
    mode = customer_mode(ctx.customer)
    d = Draft("refill", send_as="merchant_on_behalf", levers=["specificity", "effort_externalization"], mode=mode)
    mols = [humanize(m) for m in p.get("molecule_list") or []]
    runs_out = p.get("stock_runs_out_iso")
    if mols:
        lst = (", ".join(mols[:-1]) + pick(mode, " and ", " aur ", " aur ") + mols[-1]) if len(mols) > 1 else mols[0]
        line = pick(mode, f"Your {lst} will run out" + (f" by {fmt_date(runs_out)}." if runs_out else " soon."),
                    f"Aapki {lst} " + (f"{fmt_date(runs_out)} tak khatam ho jayegi." if runs_out else "jaldi khatam hone wali hai."),
                    f"Aapki {lst} ki dawai " + (f"{fmt_date(runs_out)} tak khatam ho jayegi." if runs_out else "jaldi khatam hogi."))
        offer_line = ""
        if p.get("delivery_address_saved"):
            pref = str(((ctx.customer or {}).get("preferences") or {}).get("preferred_slots", ""))
            slot = pick(mode, " in the morning", " subah", " subah") if "morning" in pref else ""
            offer_line = pick(mode, f"We can deliver the refill to your saved address{slot}.",
                              f"Hum refill aapke saved address pe{slot} deliver kar sakte hain.",
                              f"Hum dawai aapke ghar{slot} pahuncha sakte hain.")
        senior = _cust_offer(ctx, "senior")
        if senior and ctx.is_senior:
            offer_line += " " + pick(mode, f"Your {senior} applies.", f"{senior} bhi lagega.", f"{senior} bhi milega.")
        cta = pick(mode, "Reply YES to confirm, or CALL if you'd like us to ring you.",
                   "Confirm karne ke liye YES reply kijiye, ya call chahiye toh CALL likhiye.",
                   "Haan ho toh YES likhiye, phone chahiye toh CALL likhiye.") if ctx.is_senior else \
            pick(mode, "Reply YES to confirm the refill.", "Refill confirm karne ke liye YES reply kijiye.",
                 "Refill ke liye YES reply kijiye.")
        d.body = " ".join(x for x in (_cust_open(ctx, mode), line, offer_line.strip(), cta) if x)
        d.anchor = f"{lst} refill by {fmt_date(runs_out) if runs_out else 'soon'}"
        d.reasons.append(f"chronic refill: {lst}")
        d.strength = 8
    else:
        # Category mismatch or empty payload: treat it as a routine follow-up reminder.
        return pb_customer_followup(ctx, "follow-up")
    d.deliverable = "refill order + delivery"
    return d


def pb_customer_followup(ctx: Ctx, label: str = "check-up") -> Draft:
    """Generic, honest customer reminder when the trigger carries no specifics."""
    mode = customer_mode(ctx.customer)
    d = Draft("customer_followup", send_as="merchant_on_behalf", levers=["reciprocity", "effort_externalization"],
              mode=mode)
    word = {"dentists": "check-up", "gyms": "session", "salons": "appointment", "pharmacies": "refill",
            "restaurants": "table"}.get(ctx.slug, label)
    last = ctx.relationship.get("last_visit")
    visits = ctx.relationship.get("visits_total")
    since = ctx.days_since(last)
    if since is not None and since >= 45:
        months = max(1, round(since / 30))
        ctx.allow(months)
        line = pick(mode, f"It's been about {months} month{'s' if months > 1 else ''} since your last visit, so your next {word} is due.",
                    f"Last visit ko lagbhag {months} mahine ho gaye, ab aapka next {word} due hai.",
                    f"Pichhli visit ko lagbhag {months} mahine ho gaye, ab agla {word} karwa lijiye.")
    elif last:
        line = pick(mode, f"Since your last visit on {fmt_date(last)}, it's a good time to book your next {word}.",
                    f"{fmt_date(last)} ki last visit ke baad, ab next {word} book karne ka sahi time hai.",
                    f"{fmt_date(last)} ki visit ke baad ab agla {word} book kar lijiye.")
    else:
        line = pick(mode, f"It's a good time to book your next {word}.", f"Next {word} book karne ka sahi time hai.",
                    f"Agla {word} book karne ka sahi samay hai.")
    extra = ""
    if isinstance(visits, (int, float)) and visits >= 3:
        extra = pick(mode, f"Thanks for your {fmt_int(visits)} visits with us.", f"Aapki {fmt_int(visits)} visits ke liye shukriya.",
                     f"Aapki {fmt_int(visits)} visits ke liye dhanyavaad.")
    offer = ctx.active_offers[0] if ctx.active_offers else None
    if offer:
        extra += " " + pick(mode, f"{offer} is on right now.", f"Abhi {offer} chal raha hai.", f"Abhi {offer} chal raha hai.")
    cta = _slot_cta(mode, [])
    d.body = " ".join(x for x in (_cust_open(ctx, mode), line, extra.strip(), cta) if x)
    d.anchor = f"next {word}"
    d.deliverable = "slot hold"
    d.reasons.append("customer trigger had no specifics; sent an honest follow-up from visit history")
    d.strength = 4.5
    return d


def pb_lapsed(ctx: Ctx) -> Draft:
    p = ctx.payload
    mode = customer_mode(ctx.customer)
    d = Draft("winback_customer", send_as="merchant_on_behalf",
              levers=["no_shame", "effort_externalization", "specificity"], mode=mode)
    days = p.get("days_since_last_visit")
    if not isinstance(days, (int, float)):
        days = ctx.days_since(ctx.relationship.get("last_visit"))
        if days is not None and days < 30:
            return pb_customer_followup(ctx)
        if days is not None:
            ctx.allow(days)
    focus = p.get("previous_focus") or ((ctx.customer or {}).get("preferences") or {}).get("training_focus")
    line = pick(mode, f"It's been {int(days)} days since your last visit. Happens to all of us, no stress." if days else
                "It's been a while since your last visit. Happens to all of us.",
                f"Aapki last visit ko {int(days)} din ho gaye. Koi baat nahi, sabke saath hota hai." if days else
                "Kaafi time ho gaya aapko dekhe hue. Koi baat nahi.",
                f"Aapko aaye {int(days)} din ho gaye. Koi baat nahi." if days else "Kaafi samay ho gaya. Koi baat nahi.")
    mid = ""
    if focus:
        mid = pick(mode, f"Your {humanize(focus)} plan is right where you left it.",
                   f"Aapka {humanize(focus)} plan wahin se shuru ho sakta hai.",
                   f"Aapka {humanize(focus)} plan wahin se shuru kar sakte hain.")
    months = p.get("previous_membership_months")
    if isinstance(months, (int, float)) and months:
        mid += " " + pick(mode, f"You put in {int(months)} solid months with us before.", f"Aapne pehle {int(months)} mahine humare saath train kiya hai.",
                          f"Aapne {int(months)} mahine humare saath bitaye hain.")
    offer = ctx.active_offers[0] if ctx.active_offers else None
    if offer:
        mid += " " + pick(mode, f"Come back with our {offer}.", f"Wapas aaiye, {offer} ke saath.", f"{offer} ke saath wapas aaiye.")
    pref = str(((ctx.customer or {}).get("preferences") or {}).get("preferred_slots", ""))
    slot = humanize(pref) if pref else ""
    cta = pick(mode, f"Reply YES and we'll book your first one{(' on a ' + slot) if slot else ''}.",
               f"YES reply kijiye, hum aapka pehla session{(' ' + slot + ' mein') if slot else ''} book kar denge.",
               f"YES likhiye, hum pehla session book kar denge.")
    d.body = " ".join(x for x in (_cust_open(ctx, mode), line, mid.strip(), cta) if x)
    d.anchor = f"{int(days)} days since last visit" if days else "lapsed customer"
    d.deliverable = "comeback booking"
    d.reasons.append("lapsed customer win-back" + (f" ({int(days)} days)" if days else ""))
    d.strength = 6.5
    return d


def pb_trial_followup(ctx: Ctx) -> Draft:
    p = ctx.payload
    mode = customer_mode(ctx.customer)
    d = Draft("trial_followup", send_as="merchant_on_behalf", cta_type="multi_choice_slot",
              levers=["effort_externalization", "commitment"], mode=mode)
    td = p.get("trial_date")
    slots = _slots(p)
    line = pick(mode, f"Hope you enjoyed your trial on {fmt_date(td)}!" if td else "Hope you enjoyed your trial!",
                f"Umeed hai {fmt_date(td)} ka trial accha laga!" if td else "Umeed hai trial accha laga!",
                f"Umeed hai {fmt_date(td)} ka trial pasand aaya!" if td else "Umeed hai trial pasand aaya!")
    mid = pick(mode, f"Next sessions open: {' or '.join(slots)}.", f"Agle sessions: {' ya '.join(slots)}.",
               f"Agle session: {' ya '.join(slots)}.") if slots else ""
    d.body = " ".join(x for x in (_cust_open(ctx, mode), line, mid, _slot_cta(mode, slots)) if x)
    d.cta_type = "multi_choice_slot" if len(slots) >= 2 else "binary_yes_no"
    d.anchor = f"trial {fmt_date(td) if td else ''}"
    d.deliverable = "next session booking"
    d.reasons.append("post-trial follow-up with real session options")
    d.strength = 7 if slots else 5
    return d


def pb_wedding(ctx: Ctx) -> Draft:
    p = ctx.payload
    mode = customer_mode(ctx.customer)
    d = Draft("bridal_followup", send_as="merchant_on_behalf", levers=["urgency", "specificity"], mode=mode)
    days, wdate = p.get("days_to_wedding"), p.get("wedding_date")
    trial = p.get("trial_completed")
    win = p.get("next_step_window_open")
    line = pick(mode, f"{int(days)} days to go for your wedding" + (f" on {fmt_date(wdate)}" if wdate else "") + "!" if days else
                "Your big day is getting close!",
                f"Shaadi mein bas {int(days)} din bache hain" + (f" ({fmt_date(wdate)})" if wdate else "") + "!" if days else
                "Shaadi ka din paas aa raha hai!",
                f"Shaadi mein {int(days)} din bache hain!" if days else "Shaadi paas aa rahi hai!")
    mid = ""
    if trial:
        mid = pick(mode, f"Your trial on {fmt_date(trial) if parse_dt(str(trial)) else humanize(trial)} is done, so this is the right window for your skin-prep sessions.",
                   "Trial ho chuka hai, ab skin-prep sessions shuru karne ka sahi time hai.",
                   "Trial ho gaya hai, ab skin-prep shuru karne ka sahi samay hai.")
    if win:
        mid += " " + pick(mode, f"The window opens {fmt_date(win) if parse_dt(str(win)) else humanize(win)}.",
                          f"Window {fmt_date(win) if parse_dt(str(win)) else humanize(win)} se khul rahi hai.",
                          f"{fmt_date(win) if parse_dt(str(win)) else humanize(win)} se shuru kar sakte hain.")
    offer = _cust_offer(ctx, "bridal", "skin", "package")
    if offer:
        mid += " " + offer + "."
    cta = pick(mode, "Reply YES and we'll lock your dates.", "YES reply kijiye, hum dates lock kar denge.",
               "YES likhiye, hum dates pakki kar denge.")
    d.body = " ".join(x for x in (_cust_open(ctx, mode), line, mid.strip(), cta) if x)
    d.anchor = f"{days} days to wedding" if days else "wedding follow-up"
    d.deliverable = "bridal package booking"
    d.reasons.append("bridal package countdown")
    d.strength = 7
    return d


# ================================================================= routing
MERCHANT_PLAYBOOKS: dict[str, Callable[[Ctx], Draft]] = {
    "research_digest": pb_research, "category_research_digest_release": pb_research,
    "regulation_change": pb_regulation, "compliance_alert": pb_regulation,
    "cde_opportunity": pb_cde,
    "perf_dip": pb_perf_dip, "seasonal_perf_dip": pb_seasonal_dip, "perf_spike": pb_perf_spike,
    "milestone_reached": pb_milestone, "competitor_opened": pb_competitor,
    "curious_ask_due": pb_curious, "scheduled_recurring": pb_curious,
    "dormant_with_vera": pb_dormant, "festival_upcoming": pb_festival,
    "gbp_unverified": pb_gbp, "renewal_due": pb_renewal, "winback_eligible": pb_winback,
    "ipl_match_today": pb_ipl, "active_planning_intent": pb_planning, "supply_alert": pb_supply,
    "category_seasonal": pb_category_seasonal, "review_theme_emerged": pb_review_theme,
    "category_trend_movement": pb_research,
}

CUSTOMER_PLAYBOOKS: dict[str, tuple[Callable[[Ctx], Draft], tuple]] = {
    "recall_due": (pb_recall, ("recall_reminders", "appointment_reminders")),
    "appointment_tomorrow": (pb_appointment, ("appointment_reminders",)),
    "chronic_refill_due": (pb_refill, ("refill_reminders", "recall_reminders", "delivery_notifications")),
    "customer_lapsed_soft": (pb_lapsed, ("winback_offers", "recall_reminders")),
    "customer_lapsed_hard": (pb_lapsed, ("winback_offers", "renewal_reminders")),
    "trial_followup": (pb_trial_followup, ("appointment_reminders", "program_updates")),
    "wedding_package_followup": (pb_wedding, ("bridal_package_followup", "appointment_reminders")),
}

# keyword -> playbook, for trigger kinds we have never seen
_INFER: list[tuple[tuple, Callable[[Ctx], Draft]]] = [
    (("regulat", "compliance", "circular", "law", "mandate"), pb_regulation),
    (("recall", "alert", "supply", "shortage", "batch"), pb_supply),
    (("research", "digest", "journal", "study", "trend"), pb_research),
    (("webinar", "cde", "training", "workshop", "conference"), pb_cde),
    (("seasonal_dip", "seasonal_perf"), pb_seasonal_dip),
    (("dip", "drop", "decline", "fall"), pb_perf_dip),
    (("spike", "surge", "jump", "growth"), pb_perf_spike),
    (("milestone", "crossed", "anniversary"), pb_milestone),
    (("competitor", "rival", "new_store", "opened"), pb_competitor),
    (("review", "rating", "feedback"), pb_review_theme),
    (("renew", "subscription", "plan_expir"), pb_renewal),
    (("winback", "expired", "churn"), pb_winback),
    (("dormant", "inactive", "silent"), pb_dormant),
    (("festival", "holiday", "diwali", "holi", "eid", "christmas", "navratri"), pb_festival),
    (("ask", "question", "poll", "weekly", "recurring"), pb_curious),
    (("verif", "gbp", "profile_incomplete"), pb_gbp),
    (("planning", "intent", "plan_request"), pb_planning),
]
_CUSTOMER_INFER: list[tuple[tuple, str]] = [
    (("appointment", "booking", "visit_tomorrow"), "appointment_tomorrow"),
    (("refill", "medicine", "rx"), "chronic_refill_due"),
    (("recall", "due", "reminder", "checkup"), "recall_due"),
    (("lapsed", "winback", "inactive", "churn"), "customer_lapsed_soft"),
    (("trial",), "trial_followup"),
    (("wedding", "bridal"), "wedding_package_followup"),
]


def choose_playbook(ctx: Ctx) -> tuple[Callable[[Ctx], Draft], tuple | None, str]:
    """Return (playbook, consent_needs or None for merchant-facing, how it was chosen)."""
    kind = str(ctx.trigger.get("kind") or "").lower()
    is_customer = (ctx.trigger.get("scope") == "customer") or bool(ctx.trigger.get("customer_id"))
    if is_customer:
        if kind in CUSTOMER_PLAYBOOKS:
            fn, needs = CUSTOMER_PLAYBOOKS[kind]
            return fn, needs, "known"
        for words, k in _CUSTOMER_INFER:
            if any(w in kind for w in words):
                fn, needs = CUSTOMER_PLAYBOOKS[k]
                return fn, needs, f"inferred:{k}"
        return pb_customer_followup, ("promotional_offers",), "fallback"
    if kind in MERCHANT_PLAYBOOKS:
        return MERCHANT_PLAYBOOKS[kind], None, "known"
    if kind in CUSTOMER_PLAYBOOKS:  # customer-type kind with merchant scope: talk to the merchant
        return pb_generic, None, "customer_kind_merchant_scope"
    payload_keys = " ".join(ctx.payload.keys()).lower()
    for words, fn in _INFER:
        if any(w in kind for w in words):
            return fn, None, f"inferred:{fn.__name__}"
    for words, fn in _INFER:
        if any(w in payload_keys for w in words):
            return fn, None, f"inferred_payload:{fn.__name__}"
    return pb_generic, None, "generic"


def consent_ok(ctx: Ctx, needs: tuple) -> bool:
    if ctx.trigger.get("kind") == "appointment_tomorrow":
        # Transactional reminder for a booking the customer made.
        prefs = (ctx.customer or {}).get("preferences") or {}
        return bool(ctx.consent_scope) or prefs.get("reminder_opt_in") is True
    return _consent_ok(ctx, needs)
