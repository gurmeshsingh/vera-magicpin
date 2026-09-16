"""An LLM composer, built to lose fairly.

The architecture debate ended with a pre-registered experiment: both composers,
the same inputs, the same judge, decision rule fixed in advance. That experiment
needs an opponent, and an opponent built carelessly proves nothing -- a weak
prompt losing to a strong engine is evidence about the prompt.

So this gets the advantages an LLM-first design would actually claim:

*   The full context, unabridged -- every digest item, peer stat, seasonal beat
    and conversation turn, not the subset our angles happen to read.
*   The message spec derived from the scored examples, stated explicitly.
*   The anti-patterns named, including the ones we learned by measurement.
*   Two worked examples, including the one that scores 50 by arguing against
    its own trigger.

What it does not get is our grounding verifier. That is deliberate and it is the
point of the comparison: the deterministic engine cannot fabricate because it
can only assemble facts it holds, while a prompted model can say anything. If
the LLM wins on quality and loses on fabrication, that is the trade the decision
rule is meant to price.

Written to be deleted if it loses.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .judge.backends import BackendError, get_backend

SYSTEM = """You write WhatsApp messages for Vera, magicpin's assistant for \
Indian local businesses. You are writing to the business owner.

Your message will be scored 0-10 on five dimensions:
  specificity            concrete, checkable facts from the context -- numbers,
                         dates, headlines, peer stats, citations
  category_fit           voice and vocabulary matching this trade; a dentist
                         reads clinical-peer, never retail-promo
  merchant_fit           personalised to THIS merchant's numbers, active offers
                         and conversation history; language preference honoured
  trigger_relevance      it is obvious WHY NOW
  engagement_compulsion  a busy owner would actually reply

Rules that decide the score:
- Carry three to five concrete numbers drawn from the context.
- Exactly ONE ask, phrased as a yes/no. A numbered menu scores lower.
- No greeting. Open with the name and the fact.
- Never use a word from the category's vocab_taboo list.
- Never invent a statistic, citation, competitor, price or place. If it is not
  in the context you were given, it does not exist.
- An offer may be described as the merchant's own ONLY if its status is
  "active". Category catalog entries are suggestions, not their offers.
- `ctr` is a measured field. It is NOT calls divided by views; do not compute it.
- If the merchant accepted something in conversation_history and it was never
  delivered, delivering it outranks any new observation.
- Match identity.languages: Hindi-English code-mix where "hi" is present.
- Keep it under 60 words.

Return ONLY JSON:
{"body": "...", "cta": "binary"|"open_ended"|"none", "rationale": "..."}"""

FEW_SHOT = """Two messages that scored full marks.

CONTEXT: dentist, Dr. Meera, Lajpat Nagar. digest item "3-mo fluoride recall
cuts caries recurrence 38% better than 6-mo", JIDA Oct 2026 p.14, trial_n 2100,
segment high_risk_adults. customer_aggregate shows a high-risk adult cohort.
MESSAGE: "Dr. Meera, JIDA's Oct issue landed. One item relevant to your
high-risk adult patients - 2,100-patient trial showed 3-month fluoride recall
cuts caries recurrence 38% better than 6-month. Worth a look (2-min abstract).
Want me to pull it + draft a patient-ed WhatsApp you can share? - JIDA Oct 2026
p.14"

CONTEXT: restaurant, IPL match tonight. digest item notes Saturday match dates
drop covers 12% while weeknight matches lift them 18%.
MESSAGE: "Suresh - skip the IPL promo tonight. Saturday match dates drop covers
12% for dine-in; it is the weeknight matches that lift them 18%. Better to hold
the spend for Tuesday's fixture. Want me to set that one up instead?"
The second scores highest of all: it argues AGAINST its own trigger, using a
fact from the context."""


def build_prompt(
    merchant: dict[str, Any],
    category: dict[str, Any],
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
) -> str:
    return f"""{FEW_SHOT}

=== CATEGORY ===
{json.dumps(category, ensure_ascii=False)}

=== MERCHANT ===
{json.dumps(merchant, ensure_ascii=False)}

=== TRIGGER ===
{json.dumps(trigger or {}, ensure_ascii=False)}

=== CUSTOMER ===
{json.dumps(customer, ensure_ascii=False) if customer else "none (merchant-facing)"}

Write the message."""


def compose_llm(
    merchant: dict[str, Any],
    category: dict[str, Any],
    trigger: dict[str, Any] | None = None,
    customer: dict[str, Any] | None = None,
    backend: str = "gemini",
    timeout: int = 120,
) -> dict[str, Any] | None:
    """Compose via a model. Returns None on any provider or parse failure."""
    prompt = build_prompt(merchant, category, trigger, customer)
    try:
        raw = get_backend(backend).complete(SYSTEM, prompt, timeout)
    except BackendError:
        return None

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    body = str(data.get("body", "")).strip()
    if not body:
        return None
    return {
        "body": body,
        "cta": str(data.get("cta", "open_ended")),
        "send_as": "merchant_on_behalf" if customer else "vera",
        "suppression_key": "",
        "rationale": str(data.get("rationale", "")),
    }
