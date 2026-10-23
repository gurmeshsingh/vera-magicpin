# How it works

## The one idea

**Code decides what to say. The LLM, if present, only decides how to phrase it.**

The judge punishes invented facts hardest. So every fact, number, price and date is chosen by ordinary code that can only read the contexts the judge pushed. The LLM never adds content. Its rewrite is thrown away if a single number changes.

```
judge pushes context ──► store (versioned, snapshotted, seed fallback)
                               │
/v1/tick ──► for each trigger: facts ──► playbook ──► draft ──► guard
                               │                                  │
                rank: urgency + evidence; 1 per recipient   (LLM polish, checked)
                               │                                  │
                          actions (≤20) ◄─────────────────────────┘

/v1/reply ──► classify (opt-out / auto-reply / abuse / commit / later / no / off-topic / question)
                 └──► canned-but-varied answer, or a grounded answer, or an action deliverable
```

## The parts (`vera/` folder)

| File | What it does | Why it scores |
|---|---|---|
| `store.py` | Keeps every context by version. Same version → no-op, lower → 409. Remembers the previous version. | Spotting "what changed" lets messages use injected numbers and new digest items (the adaptation bonus). |
| `facts.py` | Turns raw JSON into ready phrases ("CTR 2.1% vs 3.0% peer average") and ranks merchant observations by strength. Registers every allowed number. | Specificity and merchant fit, with no fabrication. |
| `playbooks.py` | One function per trigger family. Each picks one why-now, one supporting fact, one action and one CTA. It also covers thin triggers, contradictions and unknown trigger kinds. | Decision quality and trigger relevance. |
| `compose.py` | Renders the draft, then guards it: grounded numbers, no taboo words, no internal codes, one CTA placed last. Applies the optional polish under strict checks. | Avoids the judge's anti-patterns. |
| `conversation.py` | Classifies replies and responds. Auto-replies are tracked per merchant, so a canned text repeated across conversations is caught. Commitment goes straight to a concrete deliverable. | The replay tests: auto-reply, intent transition, hostile/off-topic. |
| `llm.py` | Any OpenAI-compatible API (default Groq) through a model chain, with per-model rate budgets, a short timeout, temperature 0, a fixed seed and a cache. | Better wording, never a timeout, never a crash. |
| `bot.py` | Runs the tick: filter, rank, one message per recipient, parallel polish within 8 seconds. | Restraint and latency. |

## Key design decisions

- **Placeholder triggers (13 of 30).** The payload is empty, so the playbook looks at the merchant's own data. For a "perf_dip" with no dip (T25), the bot says numbers are up 8% and points to the real problem: the plan lapsed 39 days ago.
- **IPL on a weekend (T21).** The category digest says Saturday matches cut covers 12%, and 65% of this merchant's orders are delivery. So the bot recommends skipping the dine-in push and setting up a delivery combo. It also notes that the merchant's Tue-Thu offer doesn't apply today.
- **Diwali 188 days away (T18).** Too early to promote. The bot points to the current bridal window and the digest's own suggested "Bridal Trial @ ₹999" offer.
- **Competitor undercutting by ₹100 (T09).** The bot doesn't recommend a price war. It quotes the merchant's own positive review instead.
- **Customer messages.** They only quote the merchant's own live offers, never category catalog prices. They offer only real slots, and they respect consent scope and language preference. Seniors are addressed with "ji".


## Proving it works

- **`tests/test_adversarial.py`**: 34 tests covering missing fields, conflicting signals, zero metrics, unseen trigger kinds, consent, category mismatch, huge contexts, malformed, slow and fabricating LLM output, duplicate requests, auto-replies, Hindi, opt-out suppression and slot booking.
- **`tools/judge_run.py`**: drives the real HTTP server the way the judge does, including context injection mid-test. All checks pass, with tick p99 around 20 ms.
