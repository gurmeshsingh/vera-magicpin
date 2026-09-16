"""Our judge. Deliberately a superset of the shipped judge_simulator.py.

The shipped scorer has four defects we do not reproduce:

1.  Missing keys in the model's JSON default to 5/10, silently inflating any
    truncated response (`judge_simulator.py:549-559`).  We fail loudly.
2.  On any LLM or parse failure it falls back to `3 + 2 * digit_count` for
    specificity and a flat 5 elsewhere (`:566-578`), so digit-stuffed nonsense
    scores well against a flaky call.  We have no heuristic fallback at all.
3.  The penalties its own system prompt describes -- fabrication -2, jargon -1
    -- are never wired into the output schema, so `penalties` is always 0.
    Ours are explicit fields the judge must fill.
4.  It truncates `vocab_taboo` to the first five entries (`:509`), making taboo
    words six and beyond invisible.  We pass the full list.

It also passes the judge a much narrower context window than the real grader
gets.  challenge-brief §16 says the evaluating session receives the entire brief
and the full base dataset, and the gold-standard message in Appendix A cites
`digest` and `customer_aggregate` -- both outside the simulator's window.  So we
score against the full context by default, and expose `window="narrow"` to
reproduce the simulator's view for the tiering experiment.

Backend is the local `claude` CLI, which uses the operator's existing session
credentials.  No API key is required, and nothing here ships to production: the
bot's own composer does not depend on it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from .backends import BackendError, get_backend

DIMENSIONS = (
    "specificity",
    "category_fit",
    "merchant_fit",
    "trigger_relevance",
    "engagement_compulsion",
)

# The rubric's prose name is "trigger relevance"; the shipped parser's JSON key
# is `decision_quality` and it accepts either (judge_simulator.py:555-556).
DIMENSION_ALIASES = {"decision_quality": "trigger_relevance"}


class JudgeError(RuntimeError):
    """Raised rather than silently substituting a default score."""


@dataclass
class ScoreResult:
    scores: dict[str, int]
    reasons: dict[str, str]
    penalties: dict[str, int] = field(default_factory=dict)
    rationale_consistent: bool = True
    rationale_note: str = ""
    raw: str = ""
    backend: str = ""

    @property
    def subtotal(self) -> int:
        return sum(self.scores.values())

    @property
    def penalty_total(self) -> int:
        return sum(self.penalties.values())

    @property
    def total(self) -> int:
        return max(0, self.subtotal - self.penalty_total)

    def as_row(self) -> dict[str, Any]:
        row: dict[str, Any] = dict(self.scores)
        row["penalties"] = self.penalty_total
        row["total"] = self.total
        row["rationale_consistent"] = self.rationale_consistent
        return row


SYSTEM = """You are a strict evaluator for magicpin's Vera challenge, scoring \
WhatsApp messages written to Indian local-business merchants (or to their \
customers on their behalf).

Score each of five dimensions 0-10. 5 is average. Be strict: reserve 9-10 for \
messages that could not reasonably be improved on that dimension.

  specificity           Does the message anchor on concrete, verifiable facts
                        drawn from the context -- numbers, dates, headlines,
                        peer stats, source citations? Generic framings like
                        "10% off" or "grow your sales" score low.
  category_fit          Do the voice, vocabulary and offer format match this
                        business type? A dentist should read clinical-peer, not
                        retail-promo. Any use of a vocab_taboo word is a
                        serious failure.
  merchant_fit          Is it personalised to THIS merchant -- their numbers,
                        their active offers, their history? Is the language
                        preference honoured (hi-en code-mix where indicated)?
  trigger_relevance     Is it clear WHY NOW? Does the message communicate the
                        specific event that prompted it, rather than a generic
                        improvement nudge?
  engagement_compulsion Would a real, busy merchant reply? One strong reason,
                        one low-effort action. A single binary ask outperforms
                        a numbered menu.

Then assess penalties, each as a non-negative integer:

  fabrication   2 per claim that is not supported by the context you were given
                -- an invented statistic, citation, competitor or price. Note
                that an offer the merchant holds but which is NOT active must
                not be presented as currently available.
  jargon        1 if the message uses internal or platform jargon a merchant
                would not recognise.
  multi_cta     1 if the message contains more than one distinct call to action.
  repetition    1 if the message restates its own content redundantly.

Finally judge rationale consistency: does the stated rationale actually describe
the message that was sent? Answer true or false with one short sentence.

Return ONLY a JSON object, no prose before or after, with exactly these keys:

{"specificity": {"score": int, "reason": str},
 "category_fit": {"score": int, "reason": str},
 "merchant_fit": {"score": int, "reason": str},
 "trigger_relevance": {"score": int, "reason": str},
 "engagement_compulsion": {"score": int, "reason": str},
 "penalties": {"fabrication": int, "jargon": int, "multi_cta": int, "repetition": int},
 "rationale_consistent": bool,
 "rationale_note": str}"""


def _render_context(
    bundle: dict[str, Any], window: Literal["full", "narrow"]
) -> str:
    """Serialise the context handed to the judge.

    `narrow` reproduces judge_simulator.py:503-531 exactly, for the tiering
    experiment.  `full` is what the real grader is documented to receive.
    """
    category = bundle.get("category") or {}
    merchant = bundle.get("merchant") or {}
    trigger = bundle.get("trigger") or {}
    customer = bundle.get("customer")

    identity = merchant.get("identity") or {}
    perf = merchant.get("performance") or {}
    voice = category.get("voice") or {}
    active = [
        o.get("title")
        for o in (merchant.get("offers") or [])
        if o.get("status") == "active"
    ]

    lines = [
        "=== CONTEXT PROVIDED TO BOT ===",
        f"Category: {category.get('slug', 'unknown')}",
        f"Voice: {voice.get('tone', 'unknown')}",
        # Full taboo list, not the shipped scorer's first five.
        f"Taboos: {voice.get('vocab_taboo', [])}",
        "",
        f"Merchant: {identity.get('name', 'unknown')}",
        f"Owner: {identity.get('owner_first_name', 'unknown')}",
        f"Locality: {identity.get('locality', 'unknown')}",
        f"Languages: {identity.get('languages', [])}",
        f"Performance: views={perf.get('views', '?')}, "
        f"calls={perf.get('calls', '?')}, ctr={perf.get('ctr', '?')}",
        f"Signals: {merchant.get('signals', [])}",
        f"Active Offers: {active}",
        "",
        f"Trigger Kind: {trigger.get('kind', 'unknown')}",
        f"Trigger Payload: {json.dumps(trigger.get('payload', {}))}",
        f"Trigger Urgency: {trigger.get('urgency', '?')}",
        "",
        f"Customer: {json.dumps((customer or {}).get('identity', {})) if customer else 'None (merchant-facing)'}",
    ]

    if window == "full":
        # Everything the simulator withholds but the real grader is given.
        lines += [
            "",
            "--- additional context the grader also holds ---",
            f"Peer stats: {json.dumps(category.get('peer_stats', {}))}",
            f"Category digest: {json.dumps(category.get('digest', []))}",
            f"Seasonal beats: {json.dumps(category.get('seasonal_beats', []))}",
            f"Trend signals: {json.dumps(category.get('trend_signals', []))}",
            f"Offer catalog: {json.dumps(category.get('offer_catalog', []))}",
            f"All merchant offers (incl. inactive): "
            f"{json.dumps(merchant.get('offers', []))}",
            f"Performance deltas: {json.dumps(perf.get('delta_7d', {}))}",
            f"Customer aggregate: {json.dumps(merchant.get('customer_aggregate', {}))}",
            f"Conversation history: "
            f"{json.dumps(merchant.get('conversation_history', []))}",
        ]
        if customer:
            lines.append(f"Customer (full): {json.dumps(customer)}")

    return "\n".join(lines)


def build_prompt(
    action: dict[str, Any],
    bundle: dict[str, Any],
    window: Literal["full", "narrow"] = "full",
) -> str:
    body = action.get("body", "")
    return f"""SCORE THIS MESSAGE:

{_render_context(bundle, window)}

=== BOT'S MESSAGE ===
Body ({len(body)} chars): "{body}"
CTA: {action.get('cta', 'none')}
Send As: {action.get('send_as', 'vera')}
Suppression key: {action.get('suppression_key', '')}
Stated rationale: "{action.get('rationale', '')}"

Return only the JSON object."""


def _invoke(prompt: str, system: str, backend: str, timeout: int) -> str:
    """Send the scoring prompt to whichever judge backend was selected."""
    try:
        return get_backend(backend).complete(system, prompt, timeout)
    except BackendError as exc:
        # Deliberately fatal. The shipped scorer falls back to a digit-count
        # heuristic here, which is how digit-stuffed nonsense scores well
        # against a flaky provider.
        raise JudgeError(str(exc)) from exc


def parse(raw: str) -> ScoreResult:
    """Strict parse. Every dimension must be present; nothing defaults."""
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise JudgeError(f"no JSON object in judge output: {raw[:300]!r}")

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        # A truncated response is the likely cause, and the shipped scorer's
        # missing-key default would have hidden it.
        raise JudgeError(f"judge output is not valid JSON ({exc}); "
                         f"likely truncated: ...{raw[-200:]!r}") from exc

    for alias, canonical in DIMENSION_ALIASES.items():
        if alias in data and canonical not in data:
            data[canonical] = data.pop(alias)

    scores: dict[str, int] = {}
    reasons: dict[str, str] = {}
    missing = []
    for dim in DIMENSIONS:
        entry = data.get(dim)
        if entry is None:
            missing.append(dim)
            continue
        if isinstance(entry, dict):
            score, reason = entry.get("score"), entry.get("reason", "")
        else:
            score, reason = entry, ""
        if not isinstance(score, (int, float)):
            missing.append(dim)
            continue
        scores[dim] = int(score)
        reasons[dim] = str(reason)

    if missing:
        raise JudgeError(
            f"judge omitted dimension(s): {missing}. Refusing to substitute a "
            f"default -- that is the inflation bug we exist to avoid."
        )

    pen_raw = data.get("penalties") or {}
    penalties = {
        k: int(v)
        for k, v in pen_raw.items()
        if isinstance(v, (int, float)) and int(v) > 0
    }

    return ScoreResult(
        scores=scores,
        reasons=reasons,
        penalties=penalties,
        rationale_consistent=bool(data.get("rationale_consistent", True)),
        rationale_note=str(data.get("rationale_note", "")),
        raw=raw,
    )


def score(
    action: dict[str, Any],
    bundle: dict[str, Any],
    window: Literal["full", "narrow"] = "full",
    backend: str = "claude",
    timeout: int = 180,
) -> ScoreResult:
    """Score one message. Raises JudgeError rather than guessing."""
    result = parse(_invoke(build_prompt(action, bundle, window), SYSTEM, backend, timeout))
    result.backend = backend
    return result


if __name__ == "__main__":  # pragma: no cover
    import sys

    demo_bundle = {
        "category": {
            "slug": "dentists",
            "voice": {"tone": "peer_clinical", "vocab_taboo": ["cure", "guaranteed"]},
            "peer_stats": {"avg_ctr": 0.030, "scope": "delhi_solo_practices"},
            "digest": [
                {
                    "id": "d_2026W17_jida_fluoride",
                    "title": "3-mo fluoride recall cuts caries 38% better than 6-mo",
                    "source": "JIDA Oct 2026, p.14",
                    "trial_n": 2100,
                    "patient_segment": "high_risk_adults",
                }
            ],
        },
        "merchant": {
            "identity": {
                "name": "Dr. Meera's Dental Clinic",
                "owner_first_name": "Meera",
                "locality": "Lajpat Nagar",
                "languages": ["en", "hi"],
            },
            "performance": {"views": 2410, "calls": 18, "ctr": 0.021},
            "signals": ["stale_posts:22d", "ctr_below_peer_median"],
            "offers": [{"title": "Dental Cleaning @ Rs299", "status": "active"}],
            "customer_aggregate": {"total_unique_ytd": 540, "lapsed_180d_plus": 78},
        },
        "trigger": {"kind": "research_digest", "urgency": 2, "payload": {}},
        "customer": None,
    }
    demo_action = {
        "body": (
            "Dr. Meera, JIDA's Oct issue landed. One item relevant to your "
            "high-risk adult patients - 2,100-patient trial showed 3-month "
            "fluoride recall cuts caries recurrence 38% better than 6-month. "
            "Worth a look (2-min abstract). Want me to pull it + draft a "
            "patient-ed WhatsApp you can share? - JIDA Oct 2026 p.14"
        ),
        "cta": "open_ended",
        "send_as": "vera",
        "suppression_key": "research:dentists:2026-W17",
        "rationale": (
            "External research digest with a merchant-relevant clinical anchor; "
            "merchant is a dentist with a high-risk-adult cohort."
        ),
    }

    window = sys.argv[1] if len(sys.argv) > 1 else "full"
    backend = sys.argv[2] if len(sys.argv) > 2 else "claude"
    result = score(demo_action, demo_bundle, window=window, backend=backend)  # type: ignore[arg-type]
    print(f"backend={backend}  window={window}  total={result.total}/50  "
          f"(penalties -{result.penalty_total})")
    for d in DIMENSIONS:
        print(f"  {d:<24} {result.scores[d]:>2}/10  {result.reasons[d][:90]}")
    print(f"  rationale consistent: {result.rationale_consistent} "
          f"-- {result.rationale_note}")
