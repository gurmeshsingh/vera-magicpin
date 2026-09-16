# Vera Challenge — Strategy Note (from challenge-brief.md + challenge-testing-brief.md)

## 1. What is actually being submitted
NOT a jsonl of 30 messages. The website form asks for a **Submission URL** = a live,
public, **stateful HTTP service** exposing `/v1/context`, `/v1/tick`, `/v1/reply`,
`/v1/healthz`, `/v1/metadata`. It is run live for ~30-45 real minutes
(60 simulated minutes, 5-min ticks). challenge-brief.md §7 (bot.py + submission.jsonl)
is the older/offline framing; the testing brief is the operative contract.

## 2. The real score formula (testing-brief §4 Phase 5)
    Phase 2  : 5-dimension rubric per action  (0-10 each, 50 max per message)
    Phase 3  : adaptation bonus               max +5 PER DIMENSION (= +25)
    Phase 4  : replay test, TOP 10 ONLY       max +30
    Ops      : penalties                      max -20

=> Roughly a third of the achievable score is NOT message copy. It is
   (a) reacting to context injected mid-test, (b) multi-turn conversation handling,
   (c) not timing out / not malforming / not repeating.
   Most entrants will spend 100% of effort on copy. That is the opening.

## 3. The 5 dimensions (brief §8 — authoritative wording)
  1. Specificity          — concrete verifiable fact from context (number/date/headline/peer stat)
  2. Category fit         — voice, vocab, offer format per vertical
  3. Merchant fit         — THIS merchant's numbers, offers, history, language pref
  4. Trigger relevance    — communicates *why now*, names the trigger
  5. Engagement compulsion— would a real merchant reply?
(The website's "decision quality" == trigger relevance + which trigger you chose.)

## 4. Non-obvious scoring surfaces
- **`rationale` is scored.** FAQ: "it's included in the scoring rubric ('did the rationale
  match the actual output?'). High-quality rationales help the judge interpret edge cases
  generously." Nearly everyone will stub this. Write it as an analyst's justification
  citing the exact fields used.
- **Restraint is rewarded.** `{"actions": []}` is a legal, explicitly-praised answer.
  Spam is penalized. A scoring engine that sends 3 excellent messages beats one that
  sends 20 mediocre ones.
- **Anti-repetition: -2** per verbatim repeat in a conversation.
- **Suppression keys** are the dedupe mechanism — design a real topic:scope:period taxonomy.
- **Language pref** (`identity.languages`) — hi-en code-mix expected when `hi` present.
  Ignoring it is a named anti-pattern.
- **`send_as`** must be `vera` (merchant-facing) vs `merchant_on_behalf` (customer-facing).
  Getting this wrong on the 5 injected customer contexts is a visible miss.
- **First outbound needs a template** (`template_name` + `template_params`) per the
  WhatsApp 24h session rule.

## 5. magicpin's self-declared gaps = free differentiation (brief §3, §10)
They TELL you what production Vera does badly:
  - 40-70% of merchant "replies" are WA Business auto-replies; Vera burns 2-3 turns.
  - Intent-handoff failure: merchant says "I want to join", Vera asks another qualifying Q.
  - Generic discount copy ("10% off") vs service+price ("Haircut @ ₹99") — the latter works.
  - Low engagement frequency; needs curiosity/knowledge-driven convos not just reminders.
And of the 8 compulsion levers: "Production Vera's biggest miss is #3 social proof and
#7 asking the merchant — these families barely fire today and would unlock a lot."
=> Building explicit handlers for exactly these five things is a direct answer to the
   grader's own stated pain. Phase 4's three replay scenarios are literally
   auto-reply hell / intent transition / hostile-offtopic.

## 6. Architecture implications
- 30s budget per tick, up to 20 actions. DO NOT do 20 sequential LLM calls in a tick.
  Precompute at `/v1/context` time: when a merchant/category arrives, build and cache a
  per-merchant "angle bank". At tick, do cheap deterministic ranking + at most a small
  number of parallel, short LLM calls (or pure template fill from precomputed slots).
- Deterministic: temperature 0, seeded, and a non-LLM fallback path so a provider
  hiccup degrades to a good templated message instead of a timeout (-1) or malformed (-2).
- Stateful, no restarts mid-test. Version-idempotent context store keyed (scope, id).
- `/v1/healthz` must report real `contexts_loaded` counts — warmup gate checks 255 base
  contexts. 3 consecutive healthz failures = disqualified for the slot.
- Phase 3 adaptation: context arrives with a HIGHER `version` mid-test. Must detect the
  delta (new digest items, changed performance numbers) and reference the NEW fact in the
  next send. Suggest keeping a per-context diff log so the composer can cite "this week's
  new item" vs stale ones.

## 7. Grounding / anti-hallucination
"Bots that hallucinate (invent context that wasn't pushed) score lowest." Build a
verifier: every number, date, price, source citation and proper noun in the body must
be traceable to a field in the pushed contexts, else regenerate or fall back.
This single guard defeats the #1 fast-reject.
