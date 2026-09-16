# ARCHITECT-L — The LLM-First Architecture ("Speculative Composer")

**Stance**: The bot is scored by an LLM on qualities that are not slot-shaped. The scoring
surface is dominated by free-text judgment (5 × 0-10 rubric, +25 adaptation, +30 replay).
A template engine has a *high floor and a low ceiling*; it lands 30-35/50 and never enters
the top 10, so it never even plays for the +30. The LLM has a low floor and a high ceiling.
**The entire engineering problem is raising the LLM's floor to the template's floor without
lowering its ceiling.** This document is that engineering.

**The single load-bearing idea**: *the LLM never runs inside a judge-facing request.*
Composition is moved off the request path entirely, into speculative background work that
starts at `/v1/context` time. `/v1/tick` is a cache read plus a ranking sort — O(ms),
zero network dependencies, no timeout risk. This is what makes an LLM-first design
*safer* than a naive template design, not riskier: I get frontier-model copy with
template-engine tail latency.

---

## 0. Thesis in five lines

1. The 50/50 exemplars win on **judgment**, not on fields. Case 5 was told "IPL match
   today" and argued the merchant should **skip** the promo (Saturday matches drop covers
   -12%). Case 7 was told "views -30%" and argued it was **not a problem**. Both are
   *arguments against the trigger's own implied action*. No dispatch table produces that.
2. The judge prompt (judge-spec §1) is a free-text LLM with the instruction "Be STRICT.
   5 is average, 7+ is good, 9+ is excellent." Templates read as templates and get 6-7s.
3. 75% of trigger payloads are `{"placeholder": true}` — and the judge *sees that literal
   string* in its prompt. There is no payload to slot-fill. The only way to earn
   `decision_quality` on 75 of 100 triggers is to reason from merchant + category data to
   a "why now". That is a language task by construction.
4. Phase 3 (+25) is "cite the new fact, not the stale one, and do not hallucinate" and
   Phase 4 (+30) is an adversarial LLM merchant across 5 turns. Both are open-ended.
5. Everything the ops-first camp is right about (determinism, deadlines, suppression,
   schema, healthz) is **plumbing I also build**, deterministically, in Python. LLM-first
   is a claim about the composer, not about the server.

---

## 1. The composition stack

### 1.1 System topology

```
                     ┌───────────────────── request path (never calls an LLM) ────────┐
POST /v1/context ──► ContextStore.put()  ──► 200 {accepted:true}        (p99 < 25 ms)
      │                    │
      │                    └─► enqueue SpeculationJob(s)  ──┐
      │                                                      │
POST /v1/tick ────► Eligibility → Rank → CompositionCache.get()  ──► actions[]  (p99 < 120 ms)
      │                                          │ MISS → TemplateFloor or drop
POST /v1/reply ───► TurnClassifier (pure Python) ─┴─► ReplyCache / inline LLM w/ 8s deadline
GET  /v1/healthz ─► counters only, no locks, no I/O                     (p99 < 5 ms)
                     └──────────────────────────────────────────────────────────────┘

                     ┌───────────────────── background workers (all LLM work) ───────┐
       SpeculationQueue ──► 8 workers ──► [T1 rank] ──► [T2 compose] ──► [Verifier]
                                                              ▲              │ fail
                                                              └──── repair ◄─┘ (max 2)
                                                                             │ fail×2
                                                                   TemplateFloor (deterministic)
                     └──────────────────────────────────────────────────────────────┘
```

Three stores, all in-process (single uvicorn process, no restarts per testing brief §12):

- `ContextStore`: `(scope, context_id) -> {version, payload, received_at, diff_vs_prev}`
- `CompositionCache`: `CompositionKey -> ComposedMessage` (content-addressed, see §2.3)
- `ConversationStore`: `conversation_id -> [turns] + policy state (suppression, strikes)`

### 1.2 Precomputed artifacts (built at `/v1/context` time, never at tick time)

**(a) MerchantDossier** — built the moment a merchant context is stored, or re-built on a
version bump. Pure Python, no LLM. This is the compaction layer that turns a 4 KB merchant
JSON into a 550-token prompt block and simultaneously produces the fact ledger (§4).

```python
@dataclass(frozen=True)
class MerchantDossier:
    merchant_id: str
    salutation: str            # "Dr. Meera" | "Suresh"  (owner_first_name + category honorific)
    display: str               # "Dr. Meera's Dental Clinic, Lajpat Nagar, Delhi"
    lang_mode: str             # "en" | "hi-en" | "hi-en+regional"   from identity.languages
    perf_lines: list[str]      # ["views 2410 (30d), +18% w/w", "calls 18, -5% w/w",
                               #  "CTR 2.1% vs peer median 3.0%  ← BELOW PEER by 0.9pt"]
    peer_deltas: list[Delta]   # computed: merchant metric vs category.peer_stats, signed
    active_offers: list[str]   # ONLY status=="active"   (judge-spec §7.7 — hard rule)
    dead_offers: list[str]     # kept solely so the verifier can BAN mentioning them
    aggregate_lines: list[str] # "540 unique patients YTD; 78 lapsed >180d; 6mo retention 38%"
    recent_turns: list[str]    # last 3 conversation_history entries, with engagement tags
    signal_lines: list[str]    # ["stale_posts: 22d", "ctr_below_peer_median"]
    thinness: float            # 0.0 = seed-rich, 1.0 = generated-thin (see §1.6)
    fact_ledger: FactLedger    # §4.1
```

**(b) CategoryPack** — built once per category push. Compacts the category JSON and
pre-indexes `digest`, `seasonal_beats`, `trend_signals`, `patient_content_library`,
`offer_catalog` into retrieval-ready rows with stable IDs. Also extracts
`voice.vocab_taboo` **in full** (the judge only sees the first 5 — judge-spec §6 — but I
enforce all of them; being stricter than the judge is free).

**(c) AngleBank** — the one *cheap-model* precompute. For each merchant, a T1 (Haiku-class)
call produces 4-6 candidate "angles": one-line hypotheses about what would make this
specific merchant reply, each with a provenance path. Example output for a thin generated
merchant:

```json
{"angles":[
 {"id":"a1","line":"calls up 16% w/w while views down 20% — quality of discovery improved, volume didn't","paths":["performance.delta_7d.calls_pct","performance.delta_7d.views_pct"]},
 {"id":"a2","line":"CTR 4.6% is 1.6pt above the dentist peer median 3.0% — he is a peer-stat outlier and doesn't know it","paths":["performance.ctr","category.peer_stats.avg_ctr"]},
 {"id":"a3","line":"subscription expired 28d ago; 27 leads still arrived in the last 30d — the loss is quantifiable","paths":["subscription.days_since_expiry","performance.leads"]}
]}
```

This is the *judgment substrate*. It is computed once per merchant during the 15-minute
warmup window (T-15min), when there is no latency pressure at all, and reused across every
trigger that merchant ever receives. 50 merchants × 1 call ≈ 50 T1 calls, at concurrency 10
and ~1.4 s each ≈ **7 seconds of wall clock** inside a 900-second warmup window.

### 1.3 Retrieval — deliberately not vectors

The retrievable corpus per category is: 5 digest items, 3-5 seasonal beats, 4 trend signals,
2-3 content-library items, 8 catalog offers. **That is ~22 rows.** An embedding index over
22 rows is theatre; it adds a nondeterministic dependency and a cold-start cost to solve a
problem that a scored lexical join solves exactly. So retrieval is a deterministic scorer:

```python
def retrieve(pack: CategoryPack, trg: Trigger, dossier: MerchantDossier, now: date) -> Retrieved:
    # 1. hard pin: trigger payload may name the item outright
    if tid := trg.payload.get("top_item_id") or trg.payload.get("digest_item_id"):
        digest = [pack.digest_by_id[tid]]                     # exact, provenanced
    else:
        digest = top_k(pack.digest, k=2, key=lambda d: (
              3.0 * KIND_AFFINITY[trg.kind].get(d.kind, 0)     # research_digest→research=3
            + 2.0 * token_overlap(d.title + d.summary, dossier.signal_lines + dossier.aggregate_lines)
            + 1.0 * bool(d.get("deadline") and 0 <= days_until(d.deadline, now) <= 60)
            + 0.5 * bool(d.get("trial_n"))))                   # citable N → specificity
    beats  = [b for b in pack.seasonal_beats if month_in_range(now, b.month_range)]
    trends = top_k(pack.trend_signals, k=2, key=lambda t: abs(t.delta_yoy))
    offers = [o for o in pack.offer_catalog
              if audience_matches(o, dossier, customer) and o.type != "percentage_discount"] [:3]
              # brief §11: service+price beats "% off"; demote percentage_discount to last resort
    return Retrieved(digest, beats, trends, offers, content=pack.content_for(trg.kind))
```

`KIND_AFFINITY` is a 26 × 9 table (trigger kind → digest kind) written by hand. Ties are
broken by item `id` lexicographically so the result is byte-stable. Everything is O(22).

**Why `seasonal_beats` matters more than it looks**: the 50/50 IPL message's contrarian
claim ("Saturday IPL matches usually shift -12% restaurant covers") is *category seasonal
knowledge*, not trigger payload. The retrieval layer surfacing an in-window beat is exactly
what lets the composer argue against its own trigger. This is the mechanism of the case the
whole debate is about, and it is a retrieval + prompt design, not a template.

### 1.4 Few-shot selection from the scored case studies

I have 10 case studies with per-dimension judge feedback. They are the single highest-value
asset in the package and also the single biggest plagiarism trap (case-studies.md closing
note: *"the judge runs a similarity check on submissions vs the case studies and penalizes
near-duplicates"*). So:

- Cases are stored **structurally, not verbatim**. Each is decomposed into
  `{opening_move, fact_moves[], judgment_move, cta_move, citation_move, scores, judge_notes}`
  plus the verbatim body held **only** for the negative constraint.
- Selection: exactly 2 exemplars, chosen deterministically by
  `(same_category ? 2 : 0) + (same_scope ? 1.5 : 0) + (kind_family_match ? 1 : 0)`, ties
  broken by case number. For a dentist `research_digest` this picks Case 1 and Case 9
  (different category, same "external-authority + computed-cohort-count" family).
- Presented to the composer as **annotated skeletons with the judge's own reasons**, e.g.:

```
EXEMPLAR (dentists / research_digest, scored 50/50):
  move 1 — salutation is the owner's name alone, zero throat-clearing
  move 2 — name the external artifact that landed, by name and issue
  move 3 — bridge it to a COHORT COUNT computed from this merchant's own aggregate
  move 4 — the finding, as a number with a comparison baseline
  move 5 — cap the merchant's effort explicitly ("2-min abstract")
  move 6 — offer to do the work (reciprocity), single binary-ish ask
  move 7 — trailing source citation, em-dash form
  judge said: "Numbers + source + page reference" / "\"your high-risk adult patients\"
              derived from her customer_aggregate" / "Curiosity + reciprocity + clear next step"
  DO NOT REUSE ITS SENTENCES. The skeleton is the lesson; the words are forbidden.
```

- A **plagiarism validator** (§1.7) then enforces the prohibition mechanically:
  5-gram Jaccard and longest-common-substring against all 10 verbatim bodies.

### 1.5 The composer prompt (T2, frontier, temperature 0)

Four blocks, in this fixed order so that prefix caching works: `[SYSTEM+RULES]`,
`[CATEGORY PACK]`, `[EXEMPLAR SKELETONS]` — all cacheable — then `[THIS SEND]`, which varies.

```
=== SYSTEM (static, ~1,400 tok, cached) ===
You are Vera's composer. You write ONE WhatsApp message and nothing else.
You are a peer and an operator, never a marketer.

HARD RULES (violating any one voids the message):
 R1  Every number, date, price, proper noun, batch code, journal name and percentage in
     BODY must come from a FACT listed in the ALLOWED FACTS block, or be arithmetic you
     declare in facts_used with its operands. Inventing anything is total failure.
 R2  You may reference ONLY offers listed under ACTIVE OFFERS. Offers under
     DEAD OFFERS (expired/paused) exist but are invisible to the reader — never mention them.
 R3  Never use any word or phrase in TABOO.
 R4  No URLs. No phone numbers unless one is in ALLOWED FACTS.
 R5  Exactly ONE ask, in the final sentence. Prefer a binary ("Want me to X?", "Reply YES").
     Never stack two asks. Never bury the ask mid-message.
 R6  Open with the addressee's name as the first token. No "I hope you're doing well."
     No re-introducing yourself if PRIOR TURNS is non-empty.
 R7  If you claim research, compliance, or an external authority, cite it inline
     (journal + issue + page, circular number, batch codes). Uncited claims are capped at 7.
 R8  Merchant-facing: zero emoji. Customer-facing warm registers: at most one.
 R9  Cap the reader's effort with a real number ("2-min abstract", "live in 10 min",
     "90 seconds") and, where relevant, remove a risk ("no commitment, no auto-charge").
 R10 Never expose internal jargon: suppression_key, trigger kind slugs, "context",
     "payload", "CTR" is fine (merchants know it), "engagement_compulsion" is not.

THE HIGHEST-SCORING MOVE — do this whenever the data supports it:
 Reason PAST the trigger. The trigger says what happened; you say what it MEANS for THIS
 merchant, even when that means recommending they do the opposite of what the trigger
 implies. A message that says "this metric dropped, and here is why that is NOT a problem"
 or "this event is here, and here is why you should skip the obvious play" outscores a
 message that faithfully restates the trigger. Use SEASONAL BEATS, PEER STATS and TREND
 SIGNALS as the evidence for the contrarian read. Never be contrarian without evidence.

WHEN THE TRIGGER PAYLOAD IS A PLACEHOLDER (it will say so explicitly):
 The trigger tells you only the KIND of moment this is. Derive the actual facts from the
 merchant's own performance, aggregate, signals, and the category pack, following the
 DERIVATION RECIPE given for this kind. Say why NOW in terms of those derived numbers.
 Do not paraphrase the kind slug back at the merchant.

RESTRAINT: if the ALLOWED FACTS are too thin to say anything a competent operator would
find worth reading, set send=false and explain why in rationale. Not sending is a valid,
rewarded outcome. It is better than a message that reads like a template.
```

```
=== CATEGORY PACK: {slug} (cached per category, ~1,200 tok) ===
TONE: peer_clinical / respectful_collegial / code-mix: hindi_english_natural
VOCAB YOU SHOULD USE: fluoride varnish, caries, IOPA, OPG, RCT, zirconia, recall interval, ...
TABOO (never write these): guaranteed, 100% safe, cure, painless, FDA-approved, miracle
SALUTATION FORMS: "Dr. {first_name}", "Doc"
PEER STATS (delhi_solo_practices): avg_rating 4.4 | avg_reviews 62 | avg_ctr 0.030 |
   avg_views_30d 3100 | avg_calls_30d 34 | retention_6mo_pct 0.44
OFFER CATALOG (service+price forms preferred over % discounts):
   den_001 Dental Cleaning @ ₹299 (new_user, service_at_price)
   den_004 Teeth Whitening @ ₹1,499 (all, service_at_price) ...
DIGEST (retrieved, 2 of 5):
   d_2026W17_jida_fluoride | research | "3-mo fluoride recall cuts caries 38% better than 6-mo"
     source: JIDA Oct 2026, p.14 | trial_n: 2100 | segment: high_risk_adults
SEASONAL BEATS IN WINDOW: (Apr-May) "secondary pediatric check-up window before school break"
TREND SIGNALS: "clear aligners delhi" +62% YoY, age 28-45
```

```
=== THIS SEND (varies, ~1,150 tok) ===
ADDRESSEE: merchant (send_as=vera) | Dr. Meera's Dental Clinic, Lajpat Nagar, Delhi
SALUTATION: "Dr. Meera"     LANGUAGE MODE: en + hi (natural code-mix allowed, keep it light)
TRIGGER: kind=research_digest urgency=2 source=external
  payload: {"category":"dentists","top_item_id":"d_2026W17_jida_fluoride"}   [RICH]
  why-now framing: an external authority published something; you are the one who read it
ANGLES (from prior analysis of this merchant — pick ONE, or find a better one):
  a2 — CTR 2.1% is 0.9pt below the dentist peer median 3.0%; discovery is leaking
  a3 — 124 high-risk adults on roster vs 540 YTD; the digest item is about exactly that cohort
PRIOR TURNS WITH THIS MERCHANT (2):
  2026-04-24 vera→ "Profile audit done..."            [merchant_replied]
  2026-04-24 mx→   "Yes please, focus on whitening and aligners"  [intent_action]
  NOTE: the merchant has an OPEN stated interest in whitening + aligners. Honour it or
        acknowledge it; do not act as if this is a cold first touch.
ACTIVE OFFERS: Dental Cleaning @ ₹299
DEAD OFFERS (FORBIDDEN TO MENTION): Deep Cleaning @ ₹499
ALLOWED FACTS  (id | value | provenance | how to phrase it)
  F01 | 2410            | performance.views                       | "2,410 views in 30 days"
  F02 | 18              | performance.calls                       | "18 calls"
  F03 | 0.021           | performance.ctr                         | "2.1% CTR"
  F04 | 0.030           | category.peer_stats.avg_ctr             | "peer median 3.0%"
  F05 | 0.009 (F04-F03) | DERIVED diff                            | "0.9 points below peers"
  F06 | 124             | customer_aggregate.high_risk_adult_count| "124 high-risk adults"
  F07 | 540             | customer_aggregate.total_unique_ytd     | "540 patients YTD"
  F08 | 78              | customer_aggregate.lapsed_180d_plus     | "78 lapsed past 180 days"
  F09 | 2100            | digest.d_..._jida.trial_n               | "2,100-patient trial"
  F10 | 38%             | digest.d_..._jida.title                 | "38% better"
  F11 | "JIDA Oct 2026, p.14" | digest.d_..._jida.source           | citation form
  F12 | 22              | signals["stale_posts:22d"]              | "last post 22 days ago"
BANNED PHRASES (already used with this merchant, do not repeat): <n-grams from prior sends>
EXEMPLAR SKELETONS: <2 annotated skeletons, per §1.4>
```

### 1.6 Structured output — the enforcement schema

The composer is called with a forced tool / JSON-schema response. Nothing is parsed out of
prose. The `facts_used` array is the mechanism that makes hallucination *mechanically
detectable* rather than a matter of taste.

```json
{
  "name": "emit_message",
  "input_schema": {
    "type": "object",
    "required": ["send","rationale"],
    "properties": {
      "send": {"type":"boolean"},
      "abstain_reason": {"type":"string"},

      "body": {"type":"string","maxLength":900},
      "cta": {"enum":["binary_yes_no","binary_confirm_cancel","open_ended",
                      "multi_choice_slot","none"]},
      "send_as": {"enum":["vera","merchant_on_behalf"]},

      "facts_used": {
        "type":"array","minItems":2,"maxItems":8,
        "items":{"type":"object",
          "required":["fact_id","surface_form"],
          "properties":{
            "fact_id":{"type":"string"},               // F01.. or "DERIVED:<op>(F04,F03)"
            "surface_form":{"type":"string"},          // exact substring as it appears in body
            "operands":{"type":"array","items":{"type":"string"}}
          }}},

      "judgment_move": {
        "type":"object","required":["type"],
        "properties":{
          "type":{"enum":["restate_trigger","reframe","contrarian_override",
                          "derive_from_thin_payload","escalate_urgency","defer"]},
          "evidence_fact_ids":{"type":"array","items":{"type":"string"}},
          "one_line":{"type":"string"}}},

      "compulsion_levers": {"type":"array","minItems":1,"maxItems":3,
        "items":{"enum":["specificity","loss_aversion","social_proof",
                         "effort_externalization","curiosity","reciprocity",
                         "asking_the_merchant","binary_commitment"]}},

      "template_name": {"type":"string"},
      "template_params": {"type":"array","items":{"type":"string"}},
      "suppression_key": {"type":"string"},
      "rationale": {"type":"string","maxLength":420},
      "self_check": {
        "type":"object",
        "properties":{
          "single_cta": {"type":"boolean"},
          "cta_is_last_sentence": {"type":"boolean"},
          "no_taboo": {"type":"boolean"},
          "no_url": {"type":"boolean"},
          "offers_referenced": {"type":"array","items":{"type":"string"}},
          "emoji_count": {"type":"integer"}}}
    }
  }
}
```

Two design notes that matter:

- **`facts_used[].surface_form` must be an exact substring of `body`.** This is not a
  request, it is a checkable invariant. It converts "did the model hallucinate?" from an
  LLM-judgment problem into a string-membership problem.
- **`judgment_move.type` is a scored-by-me field.** If the composer picks
  `restate_trigger` when the angle bank offered a `contrarian_override` with evidence, the
  orchestrator can re-roll once with an explicit nudge. This is how I systematically
  manufacture Case-5-shaped messages instead of hoping for them.
- `rationale` is a graded artifact (testing brief §14 FAQ; case-studies cross-case #9). It
  is generated in the same call as the body so it is *by construction* a description of the
  same reasoning, then validated for consistency (§1.7 V9).

### 1.7 Validators (pure Python, ~2 ms, run on every candidate)

| # | Check | Action on fail |
|---|---|---|
| V1 | every `surface_form` is a substring of `body` | repair |
| V2 | every `fact_id` resolves in the ledger; `DERIVED` operands resolve and the arithmetic checks to 2 dp | repair |
| V3 | **orphan-numeral scan**: every `\d[\d,.]*%?`, every `₹\d+`, every date-like token, and every Capitalized-Multiword span in `body` is covered by some `surface_form` | repair |
| V4 | no token from `voice.vocab_taboo` (full list, case-insensitive, stemmed) | repair |
| V5 | no URL / bare domain / `http` / `www.` | repair (hard fail per api F.4, -3) |
| V6 | exactly one `?` or one imperative-ask sentence, and it is in the last sentence | repair |
| V7 | no mention of any `dead_offers` title or its price token | repair |
| V8 | plagiarism: 5-gram Jaccard vs each of the 10 case bodies < 0.18 **and** LCS < 40 chars | repair |
| V9 | rationale-body consistency: every fact_id cited in rationale ∈ facts_used; rationale mentions the trigger kind's why-now | repair |
| V10 | anti-repetition: body 5-gram Jaccard vs every prior body in this `conversation_id` < 0.35, and vs every prior body to this `merchant_id` < 0.55 | repair with banned-phrase list |
| V11 | schema completeness: `conversation_id, merchant_id, send_as, trigger_id, cta, suppression_key, rationale, body` all non-empty (api F.2: missing → 0 and -2) | rebuild from defaults, never emit partial |
| V12 | `send_as` matches scope: `customer_id != null ⟺ merchant_on_behalf` | force-correct |
| V13 | emoji count ≤ 0 merchant-facing, ≤ 2 customer-facing | strip |
| V14 | language mode: if `lang_mode` includes `hi` and body is 100% English, warn (soft — not every message should be code-mixed) | log only |

Repair loop: at most **2** repair attempts, each a *short* T2 call (~250 input tokens: the
failing body + the specific violated rule + the ledger delta), ~1.8 s each. After 2
failures, the TemplateFloor (§4.4) is used instead. Because this all runs in the background,
a repair loop costs latency budget I am not spending.

---

## 2. Determinism with an LLM — the rigorous version

The contract (brief §7.1) says: *"Must be deterministic given the same inputs (set
temperature=0 if using LLMs)."* I am going to be precise about what I can and cannot
guarantee, because hand-waving here is the fastest way to lose this debate.

### 2.1 What I control exactly

- `temperature=0`, `top_p=1`, `top_k=1` — greedy decoding.
- `seed` where the provider exposes one (OpenAI-family); pinned `system_fingerprint`
  logged and asserted at startup.
- **Pinned model id, never an alias.** `claude-sonnet-4-5-20250929`, not `-latest`.
  An alias silently repointing mid-competition is a real and stupid way to lose.
- **Byte-stable prompt construction.** This is where most "nondeterministic LLM" bugs
  actually live, and it is 100% my fault when it happens:
  - `json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",",":"))` everywhere.
  - No `set` iteration in prompt assembly — every collection is a `list` sorted by an
    explicit key.
  - No `dict` ordering assumptions from JSON parse order; dossiers are built by explicit
    field enumeration.
  - Floats formatted through one function: `fmt(0.021) == "2.1%"`, never `repr()`.
  - **No wall-clock in the prompt** except the judge-supplied `now` (which is simulated
    time and is itself an input). No `datetime.utcnow()` anywhere in the composer path.
  - Prompt template version is a constant in the source, `PROMPT_V = "c7"`, and is part of
    every cache key.
- Fixed `max_tokens`, fixed stop sequences, fixed tool-choice (`{"type":"tool","name":"emit_message"}`).

### 2.2 The residual, stated honestly

Greedy decoding is **not** a mathematical guarantee of byte-identical output. Batch
composition on the provider's side changes the order of floating-point reductions in the
attention and MLP kernels; near-tied logits can flip. Empirically this shows up as a
divergence rate on the order of 1-3% of long generations, usually a synonym or comma. I
cannot fix it at the model. **I fix it at the system boundary.**

### 2.3 Content-addressed composition cache — determinism by construction

```python
CompositionKey = sha256("|".join([
    PROMPT_V, MODEL_ID, DECODE_SIG,          # "c7|claude-sonnet-4-5-20250929|t0p1k1"
    merchant_id, str(merchant_version),
    category_slug, str(category_version),
    trigger_id, str(trigger_version),
    customer_id or "-", str(customer_version or 0),
    conversation_state_digest,               # turns so far, suppression state
]))
```

Semantics: **a CompositionKey is computed at most once, ever.** The first computation
persists; every subsequent request for the same key returns the same bytes. Therefore:

> *For any pair of identical inputs within one test run, the system emits byte-identical
> output — by construction, not by hope.*

This is the strongest determinism claim available to any architecture, LLM or not, and it
is exactly the property the contract is trying to buy. The version components mean Phase 3
works correctly and automatically: a category `version: 2` push changes the key, which
forces a *fresh* composition against the *new* digest — stale-composition reuse is
structurally impossible.

### 2.4 The determinism harness (evidence, not assertion)

Before submitting I run `determinism_probe.py`: all 30 canonical test pairs, **cache
disabled**, 5 repetitions each = 150 compositions. It reports:

- byte-identity rate across repetitions (target: report the actual number; I expect 96-99%),
- for every divergence, a diff and whether it survived the validators,
- **semantic-invariance rate**: do all 5 runs cite the *same fact_ids*, the *same
  `judgment_move.type`*, the *same `cta`*, and the same numeric surface forms? This is the
  number that actually matters and I expect it at 100%, because the ledger + schema +
  validators collapse the output space to a narrow manifold. A comma moving is not a
  determinism failure in any sense the judge can observe.

I will publish that number in `/v1/metadata.approach` and the README rather than claim
"deterministic" as a boolean. An architecture that reports `byte_identity=0.98,
fact_invariance=1.00` is more credible than one that asserts 1.0 and is lying.

### 2.5 What determinism is actually worth here

Worth saying plainly: **no scoring mechanism in either brief or in the reference simulator
rewards determinism directly.** The judge never calls the bot twice with the same input
(judge-spec §7.10 confirms no cross-call determinism check exists in the reference harness).
Determinism's real cash value is: (a) contract compliance, (b) anti-repetition (-2/repeat),
and (c) reproducible debugging. (b) is handled by suppression + V10 independently of the
model. So I take determinism seriously as a contract obligation and engineer it properly —
but I will not accept a trade that costs 10 rubric points per message to buy a property
that is worth at most a few operational points.

---

## 3. Fitting 30 s / 20 actions — the latency architecture

### 3.1 The move: composition is speculative and happens at context-push time

Read the harness lifecycle carefully (testing brief §4, judge-spec §4):

- Phase 1 pushes 255 contexts over a **15-minute** window, then waits 60 s.
- Phase 2, per tick: *first* the judge POSTs new contexts, *then* it POSTs `/v1/tick`.
- `judge_simulator._full` pushes **all** triggers and *then* ticks in batches of 5.

So triggers arrive at `/v1/context` **before** they appear in `available_triggers`. The gap
is seconds in the simulator and minutes in the live harness. That gap is my entire compute
budget, and it is free.

```
t=0.000  POST /v1/context {scope:trigger, id:trg_042}
t=0.012  ← 200 {"accepted":true}                        ← the judge is already unblocked
t=0.013  SpeculationQueue.push(job(trg_042))
t=0.9    T1 rank: is this trigger worth composing at all? (cheap, batched)
t=1.1    T2 compose starts
t=6.0    T2 returns; validators run (2 ms); cached under CompositionKey
         ...
t=180.0  POST /v1/tick {available_triggers:[..., trg_042, ...]}
t=180.04 ← 200 {"actions":[...]}                        ← pure cache read + sort
```

`/v1/tick` p99 target: **120 ms**. The 30-second budget is not a budget I spend; it is
headroom I never touch. This is the crux of my answer to the ops architect: my timeout risk
is not "lower than you think", it is *structurally the same as a template engine's*, because
no judge-facing handler awaits an LLM.

### 3.2 Latency and token math (concrete)

Per T2 composition:

| Block | Tokens | Cacheable |
|---|---:|---|
| system + hard rules | 1,400 | yes |
| category pack (compacted) | 1,200 | yes (5 variants) |
| exemplar skeletons | 700 | yes (pool of 10) |
| merchant dossier + ledger | 750 | no |
| trigger + angles + prior turns | 400 | no |
| customer block (when present) | 200 | no |
| **input total** | **~4,450** (≈3,300 cached after first hit) | |
| output (structured JSON) | ~320 | |

Sonnet-class, streaming off: TTFT p50 ≈ 0.55 s, output ≈ 75 tok/s.
- p50 = 0.55 + 320/75 ≈ **4.8 s**
- p95 ≈ **9 s**, p99 ≈ **18 s** (provider tail, 529s, retry)

Repair pass: ~250 in / ~330 out ≈ **1.9 s** p50.
Worst realistic background path: 18 s + 1.9 + 1.9 ≈ **22 s** — entirely off the request path.

**Concurrency.** 8 background workers. Sustained throughput ≈ 8 / 4.8 s ≈ **1.7
compositions/s ≈ 100/min**. Load: 100 base + 15 injected triggers = 115; even composing
*every* trigger speculatively with 2 variants = 230 compositions ≈ **2.3 minutes of
aggregate work** spread across a 30-45 minute run. There is no throughput problem. The T1
ranker (§3.3) cuts it further by skipping compositions for triggers that fail eligibility.

**Cost.** ~4,450 in / 320 out at $3/$15 per Mtok ≈ $0.018, ~$0.011 with cache hits.
230 compositions + ~150 reply turns + 50 angle-bank T1 calls ≈ **$5-8 for the entire run.**
Cost is not a constraint in this problem and any architecture arguing on cost grounds is
arguing about a rounding error.

### 3.3 Model tiering

| Tier | Model class | Used for | p50 | Determinism posture |
|---|---|---|---|---|
| T0 | none (Python) | eligibility, suppression, consent gate, urgency rank, all validators, turn classification | <2 ms | exact |
| T1 | Haiku-class | angle bank (warmup), speculative worth-composing filter, batched triage of 20 triggers in one call | 1.2-1.5 s | temp 0; output is structured ranks, low entropy |
| T2 | Sonnet-class frontier | composition, repair, reply bodies | 4.8 s | temp 0 + cache |

T1's triage call takes up to 20 candidate (merchant, trigger) pairs and returns a ranked
list with a one-line reason — one call, not twenty. Its output feeds the deterministic
ranker as one feature among several, never as the sole decision, so a T1 wobble cannot
change *whether* a high-urgency trigger fires, only its position among ties.

### 3.4 Tick-time algorithm (no LLM, hard-bounded)

```python
def tick(now, available_triggers):                       # deadline: 1.5 s soft, 3 s hard
    deadline = monotonic() + 1.5
    cands = []
    for tid in available_triggers:
        trg = store.trigger(tid)
        if not trg or expired(trg, now): continue
        if suppressed(trg.suppression_key, now): continue       # §3.5
        if conversation_ended(merchant_of(trg)): continue       # opted out → never again
        if not consent_ok(trg): continue                        # walk-in customer, empty scope
        cands.append(trg)

    cands.sort(key=lambda t: (-t.urgency,
                              -freshness_bonus(t, now),          # injected-this-tick first
                              -cache.quality_score(key(t)),      # verified > floor
                              t.id))                             # stable tiebreak
    actions, used_merchants = [], set()
    for trg in cands:
        if monotonic() > deadline: break
        if trg.merchant_id in used_merchants: continue           # FAQ: 1 action per merchant/tick
        c = cache.get(key(trg))
        if c is None:                                            # speculation not done yet
            if trg.urgency >= 4 and floor.available(trg):
                c = floor.compose(trg)                           # deterministic template
            else:
                continue                                         # skip; restraint is rewarded
        if not c.send: continue                                  # composer chose to abstain
        actions.append(c.as_action()); used_merchants.add(trg.merchant_id)
        if len(actions) >= SEND_BUDGET(now): break
    return {"actions": actions}
```

`SEND_BUDGET` is **3-5 per tick, never 20.** Twelve ticks × 4 = ~48 scored messages. The
cap is deliberate and doctrinal: restraint is explicitly rewarded, spam explicitly
penalized, and the Phase 2 score is an *average* across scored messages (judge-spec §2:
`total // n`). Sending 20 mediocre messages actively lowers the mean that everything else is
computed from. **Sending fewer, better messages is a scoring strategy, not just politeness.**

### 3.5 Suppression taxonomy

`topic:scope:period` — legible, decodable (cross-case #8 rewards this):

```
research:dentists:2026-W17           # category+week
perf_dip:m_002:calls:2026-W17        # merchant+metric+week
recall:c_001_priya:6mo               # customer+cycle
renewal:m_004:2026-05                # merchant+month
curious_ask:m_002:2026-W17           # one ask per merchant per week
alert:atorvastatin:2026-04           # incident-scoped
```

Rules: honour the trigger's own `suppression_key` when present; otherwise synthesize.
Additional global governors: ≤1 send per merchant per tick, ≤3 per merchant per run,
hard stop on any merchant whose conversation reached `end`.

### 3.6 Deadline handling, top to bottom

- Every handler wrapped in `asyncio.wait_for` with an internal deadline well under the
  judge's (tick 3 s, reply 8 s, context 0.5 s).
- On internal deadline: return the *valid degraded* response, never an error.
  tick → `{"actions": []}`; reply → `{"action":"wait","wait_seconds":1800,"rationale":...}`.
  Both are legal, both score better than a timeout (-1) or malformed (-2).
- `/v1/healthz` is served by a handler that touches only three integer counters, on a
  dedicated route with no shared locks, so background saturation cannot cause the three
  consecutive failures that mean disqualification (-10).
- Background workers use a bounded queue (maxsize 512) and shed load from the *tail*
  (lowest urgency first), never from the head.
- Provider calls: 6 s connect / 25 s read timeout, one retry on 429/5xx with jitter, and a
  **hedge**: if a T2 call has not returned by 8 s, fire a second identical call to the
  secondary provider and take the first to land. (Hedging is a determinism wrinkle: two
  providers can disagree. Resolution — the hedge result is only cached if the primary lost
  the race *and* passed all validators; the key still memoizes exactly one answer, so the
  determinism-by-construction property holds.)

---

## 4. Grounding — the part that decides the whole competition

*"Bots that hallucinate (invent context that wasn't pushed) score lowest."* And 75% of
trigger payloads are `{"placeholder": true, "metric_or_topic": "<kind>"}`, 86% of merchants
have zero offers, 84% have no conversation history, 80% have no signals. The composer is
being asked to be specific about a merchant about whom almost nothing specific is known.
This is the crux, and it is where a template engine quietly fails too — it just fails
*blandly* instead of *falsely*.

### 4.1 The FactLedger

Built deterministically from the pushed contexts at dossier time. Every entry is
`(fact_id, raw_value, normalized_surface_forms[], provenance_path, class)`.

```python
class FactLedger:
    facts: dict[str, Fact]              # F01..Fnn
    surface_index: dict[str, str]       # "2,410" -> F01 ; "2410" -> F01 ; "2.1%" -> F03
    derivations: set[str]               # whitelisted ops: diff, pct_diff, ratio, share, days_between
```

Population sources, in priority order:
1. `merchant.performance.*` (always present — this is the reliable floor: views, calls,
   directions, ctr, leads, delta_7d)
2. `category.peer_stats.*` — and every **computed delta** between (1) and (2). This is the
   single most productive fact factory for thin merchants: it turns two boring numbers into
   "0.9 points below the Delhi solo-practice median", which is a *judgment*, not a readout.
3. `merchant.customer_aggregate.*` (key set is non-standard — treat as a loose bag; iterate
   whatever keys exist rather than looking for named ones)
4. `merchant.subscription.*` (with the trap guarded: `status=="expired"` ⇒ never phrase as
   "renewal upcoming"; `days_remaining==0` is not "0 days left to renew")
5. `merchant.signals[]` — parse the `name:value` suffix form into citable numbers
   (`stale_posts:22d` → "last post 22 days ago")
6. `merchant.offers[]` — **active only**, plus `dead_offers` as an explicit ban list
7. `merchant.review_themes[]` (incl. `common_quote`, quotable verbatim)
8. `category.digest[]` retrieved items (title, source, `trial_n`, `deadline`, `credits`)
9. `category.seasonal_beats[]`, `category.trend_signals[]` (delta_yoy is a number)
10. `category.offer_catalog[]` — **catalog offers are proposable, not assertable.** Phrasing
    rule: "we can run Dental Cleaning @ ₹299" is legal; "your ₹299 cleaning offer" is a
    fabrication unless it is in `merchant.offers` with `status=="active"`. This is exactly
    the trap that cost Case 3 and Case 6 a point each ("assumes the program exists in
    catalog"), and it is enforced as validator V7b, not left to the model's discretion.
11. `customer.*` when scope is customer (relationship dates, visits, services, lifetime_value,
    language_pref, consent scope)
12. `trigger.payload.*` — **only when not a placeholder.**
13. `now` (judge-supplied) and every `days_between(now, date_fact)` derivation — this is
    how "196 days to your wedding" and "it's been 5 months since your last visit" get made.

Derived facts are first-class ledger entries with their operands recorded, so V2 can
re-execute the arithmetic. Nothing else may appear as a number in the body. Ever.

### 4.2 Placeholder payloads — the derivation recipes

When `payload.get("placeholder")` is true, the prompt swaps in a kind-specific
**DERIVATION RECIPE** that tells the composer exactly which real fields carry the why-now.
This is a 15-entry table (one per generatable kind). Excerpts:

```
perf_dip [PLACEHOLDER]
  The trigger only says "a dip happened". Find it yourself:
  pick the most negative of performance.delta_7d.{views_pct, calls_pct} and name it with
  its absolute number too ("calls fell 20% w/w — 18 down from ~23"). Then check
  seasonal_beats: if the current month sits in a known down-window for this category,
  the HIGHEST-SCORING move is to say so and tell them NOT to spend against it.

research_digest [PLACEHOLDER]
  No item id given. Use the retrieved digest item. Cite source + issue + page. Bridge to
  the merchant's own cohort via customer_aggregate. Never invent a finding not in the item.

renewal_due [PLACEHOLDER]
  Use subscription.{status, plan, days_remaining}. If status=="expired", this is a WINBACK,
  not a renewal — reframe it and quantify what accrued while they were off
  (leads, views in the last 30d). Never say "your plan expires in 0 days".

competitor_opened [PLACEHOLDER]
  You do NOT have a competitor name, distance, or offer. NEVER invent one — naming a
  competitor that isn't in context is the single most-cited hallucination example in the
  brief. Pivot to defensible ground: this merchant's own peer-stat position
  (ctr vs peer median, views vs avg_views_30d) and what to shore up. If that is also thin,
  set send=false.

chronic_refill_due [PLACEHOLDER]
  No molecule list, no run-out date. Do not invent molecules or dates. Use the customer's
  relationship.last_visit + visits_total, and the merchant's active offers
  (free delivery / senior discount). Ask rather than assert:
  "Sharma ji ki monthly refill due lag rahi hai — confirm karein toh pack ready kar dein?"

curious_ask_due [PLACEHOLDER]
  This is a question, not a report. Brief §10 names "asking the merchant" as production
  Vera's biggest miss — this kind is a free run at an undersupplied lever. Raise
  specificity by GUESSING from data before asking (Case 4 lost exactly one point here for
  not guessing): "Is it still the keratin treatment, or has something else taken over?"
  Always pair with reciprocity: what you'll do with the answer, and how long it takes.
```

The recipes are the thing that makes thin-payload triggers scoreable at all, and they are
prompt content — editable, testable, and not a code path. A template engine needs 15 hand-
written message shapes here; I need 15 paragraphs of guidance and one composer.

### 4.3 The verifier, precisely

```python
def verify(c: Composed, ledger: FactLedger, ctx) -> list[Violation]:
    v = []
    for f in c.facts_used:
        if f.surface_form not in c.body:                     v.append(V1(f))
        if f.fact_id.startswith("DERIVED:"):
            if not recompute_ok(f, ledger):                  v.append(V2(f))
        elif f.fact_id not in ledger.facts:                  v.append(V2(f))

    covered = set()                                          # char spans claimed by facts_used
    for f in c.facts_used: covered |= spans(c.body, f.surface_form)
    for m in NUMERIC_OR_PROPER.finditer(c.body):             # \d[\d,.]*%?|₹[\d,]+|Jan-Dec|Capitalized+
        if m.span() not in covered and m.group() not in SAFE_WORDS:
            v.append(V3_ORPHAN(m.group()))                   # ← the hallucination catcher
    ...
    return v
```

`SAFE_WORDS` is a small, explicit allowlist: the merchant's own name tokens, the owner's
name, the locality/city, the category display name, "WhatsApp", "Google", "YES", weekday
names, and the digits inside already-covered spans. Everything else that looks like a fact
must be claimed. **An orphan numeral is treated as a hallucination until proven otherwise.**

### 4.4 The regenerate / fallback ladder

```
compose (T2, temp 0)
   └─ validators pass? → cache as quality="verified"           [target: ~85% first-pass]
   └─ fail → repair #1 (T2, ~1.9 s, told exactly which rule and which token offended)
        └─ pass → cache quality="repaired"
        └─ fail → repair #2, with the offending facts REMOVED from the ledger
             └─ pass → cache quality="repaired"
             └─ fail → TemplateFloor
```

**TemplateFloor** is a real, deterministic, non-LLM composer — roughly 20 hand-written
shapes keyed by `(trigger_kind_family, scope, has_customer)`, filled strictly from ledger
facts. It is what my opponents would ship as their *whole product*; I ship it as my
*failure mode*. It is exercised in three situations only: two failed repairs, a
speculation cache miss on an urgency≥4 trigger, and total provider outage. Its expected
score is 30-35/50 — which is precisely why I refuse to make it the primary path.

And one more rung below that: **abstain.** If the floor cannot produce ≥2 ledger facts,
the trigger is dropped and nothing is sent. `{"actions": []}` is explicitly legal and
explicitly rewarded, and it protects the Phase 2 *average*.

### 4.5 Phase 3 — the adaptation machinery

When `/v1/context` accepts a higher version, the store computes a structural diff and keeps
it:

```python
ContextDiff(
  scope="category", id="dentists", from_v=1, to_v=2, at=now,
  added   = ["digest[d_2026W17_dci_radiograph_NEW]"],
  changed = [],
  removed = [])
```

Three consequences fire automatically:

1. **Every CompositionKey touching that context is invalidated** (the version is in the
   key), so nothing stale can be re-served. Speculation for affected triggers re-runs
   immediately in the background.
2. The diff is injected into the prompt as a distinguished block, which is the single
   highest-leverage 80 tokens in the whole system:
   ```
   NEW SINCE YOUR LAST MESSAGE TO THIS MERCHANT (arrived 2026-04-26T10:50Z):
     + digest d_2026W17_dci_radiograph_NEW | compliance | "DCI revised radiograph dose
       limits effective 2026-12-15" | source: DCI circular 2026-11-04
       | detail: "Max dose drops 1.5→1.0 mSv per IOPA. E-speed film passes; D-speed does not."
     + performance.views 2410 → 2580 (+7.1%)
   PREFER THE NEW ITEM. If you cite the older digest item when this newer one is relevant
   to this merchant, you are sending a stale message. Name the change explicitly
   ("as of this morning", "this week's circular").
   ```
3. The ranker applies a `freshness_bonus` so a merchant with fresh context outranks one
   without, ensuring the adaptation actually gets *sent* and therefore *scored*.

This is where LLM-first has its cleanest structural advantage. A template engine must have
anticipated the shape of a *DCI radiograph dose-limit compliance item* to say anything
intelligent about it. The composer just reads it and writes the message a dentist would
want. Phase 3 is worth +25 and is, by design, made of content nobody saw during development.

---

## 5. Multi-turn `/v1/reply`

### 5.1 Hybrid by design — and I will defend the hybrid honestly

`/v1/reply` is the one judge-facing endpoint that *cannot* be fully precomputed: the
merchant's text is unknown until it arrives. So here I run a **deterministic classifier
first, LLM second**, with an 8-second internal deadline.

```python
def reply(req):
    conv = conversations.get_or_create(req.conversation_id)
    conv.append(req)
    sig = classify(req.message, conv)          # pure Python, <1 ms
    policy = POLICY[sig.route](conv, sig)      # decides action BEFORE any LLM runs
    if policy.action in ("end", "wait"):
        return policy.as_response()            # ← no LLM in the path at all
    body = compose_reply(conv, sig, deadline=8.0) or floor_reply(conv, sig)
    return {"action":"send", "body":body.text, "cta":body.cta, "rationale":body.rationale}
```

`classify` is deterministic and covers the four named failure families:

| Route | Detection (pure Python) | Policy |
|---|---|---|
| `auto_reply` | (a) normalized-text exact match against a previous inbound turn; (b) canned-phrase set: "thank you for contacting", "we will respond shortly", "our team will get back", "automated assistant", "aapki jaankari ke liye", "hamari team tak pahuncha"; (c) sub-second reply latency; (d) reply is identical across two different sends | strike 1 → **send** one flag-for-the-owner line; strike 2 → **wait 86400**; strike 3 → **end** |
| `opt_out / hostile` | lexicon: "stop", "not interested", "don't message", "spam", "useless", "band karo", "mat bhejo", "unsubscribe", "bakwaas", + a small profanity/frustration set | **end** immediately (or one-line apology + end), and set a 30-day merchant-wide suppression |
| `intent_commit` | "let's do it", "ok do it", "go ahead", "yes please", "chalo karo", "kar do", "haan", "sounds good", "what's next", "start" | **send in ACTION MODE** (§5.2) — never another qualifying question |
| `off_topic` | a topic classifier over a small out-of-scope set (GST/tax, legal, HR, personal) | **send**: one-line decline + redirect to the open thread |
| `question` / `engaged` | default | **send**, LLM-composed |

Escalation for auto-reply is exactly the ladder the package rewards
(api-call-examples: send → wait 24h → end), and the judge's `_auto_reply` scenario accepts
`end` (pass) or `wait` (ok), which this ladder reaches by turn 3-4 out of 4.

### 5.2 ACTION MODE — beating a keyword-matching grader with an LLM

The judge's `_intent` check is literally:
`if any(actioning) and not any(qualifying) → PASS`, where
`qualifying = ["would you","do you","can you tell","what if","how about"]` and
`actioning = ["done","sending","draft","here","confirm","proceed","next"]`.

So ACTION MODE gets a **constrained decode plus a validator**:

```
ACTION MODE. The merchant has committed. You are executing, not qualifying.
 - First word of your reply is an execution verb: Done / Drafting / Sending / Here's / Setting up.
 - Deliver the ARTIFACT in this message — the actual draft, the actual tiers, the actual
   copy. Do not promise to deliver it later.
 - Quantify the scope of what you just did ("to your 124 high-risk adults", "3 tiers").
 - You may end with exactly one CONFIRMATION ask ("Reply CONFIRM to send") — that is a
   go/no-go, not a discovery question.
 - FORBIDDEN openings and phrasings: "would you", "do you", "can you tell", "what if",
   "how about", "just to plan well", "quick question", "before we start".
```

`V_ACTION`: reject any candidate containing a `qualifying` phrase or lacking an `actioning`
token; repair once; floor to a deterministic action-mode template if it fails twice. So I
satisfy the keyword grader *mechanically* while the LLM supplies the actual artifact — the
tiered price list, the drafted patient WhatsApp — that earns the qualitative points. A pure
state machine can emit "Done, sending the draft." and pass the keyword check; it cannot
emit *the draft*, and Case 6 (49/50) shows the draft is where the points are.

### 5.3 Why an LLM beats a state machine here — specifically

A state machine handles the three *named* scenarios. The Phase 4 spec says the judge plays a
merchant with an **LLM**, for 5 turns, scored on *conversation flow*. The tail is where the
points are, and the tail is unbounded:

- "Ok but my son handles the WhatsApp, send it Tuesday" — not opt-out, not commitment, not
  auto-reply, not off-topic. It's a conditional deferral with a channel change. A state
  machine has no state for it. The composer acknowledges the son, moves to Tuesday, and
  keeps the thread.
- A merchant who switches from English to Hindi mid-conversation (brief §12.4). The
  classifier notices; only a generative composer can *answer* in the switched register.
- "Why are you bothering me" followed by "btw can you help with GST?" in the *same* replay
  (testing brief §4, Phase 4 scenario 3) — hostile **then** engaged-off-topic. A state
  machine that ended on turn 2 has nothing left to score for turns 3-5. The correct play is
  a graceful acknowledgment that stays available, then a scoped decline plus redirect. That
  is a judgment call about *how much* hostility warrants termination, and it is exactly the
  kind of call that reads as human when a model makes it and as brittle when a table does.
- The judge's own reference `_hostile` check accepts `send` with an apology — meaning a
  graceful, *worded* exit is a first-class pass. Wording is the job.

Policy stays deterministic (whether to send/wait/end is a table). Language stays generative.
That split is the whole architecture in one line.

---

## 6. My three biggest weaknesses, without spin

### W1 — I depend on a third party I do not control, inside a scored 30-45 minute window.

If the provider has an incident during my slot, every composition falls to the
TemplateFloor. My entire score collapses to the thing I spent this document arguing is
insufficient. A template architecture has no such correlated failure mode. And it is not
only outage: rate limits, a 60-second regional latency spike, or a silent model alias
repoint would all land inside the window with no ability to retry the run.

**Mitigation.** (a) The speculative pipeline means most compositions were produced minutes
*before* they are needed, so a 2-3 minute provider blip is invisible — this converts an
availability problem into a *buffer depth* problem, and the buffer is minutes deep.
(b) Two providers, different vendors, different networks; T2 hedges at 8 s, and a circuit
breaker flips the primary after 3 consecutive failures. (c) The angle bank is built during
warmup and cached, so even a total outage during Phase 2 leaves the floor composing from
precomputed judgment rather than from raw fields. (d) Pre-run: pinned model ids asserted at
boot, quota verified, and a synthetic load test at 2× expected rate. (e) The floor is not a
stub — it is a real, tested, ~20-shape composer that I will actually score locally, so I
know my worst case is ~32/50 and not 0.

### W2 — I cannot prove byte-level determinism, only engineer around it.

Temperature 0 is not a proof. My cache makes the *system* deterministic for repeated inputs,
but a cold computation of the same key on a different day may differ. If the real grader
runs a cold-cache determinism probe — or if a human reviewer reads "deterministic" as a
formal property — I lose that argument on the merits, and I will not pretend otherwise.

**Mitigation.** (a) Determinism by construction at the system boundary (§2.3): within the
graded run, identical input ⇒ identical bytes, always. (b) Measure and *report* rather than
assert: the determinism harness publishes byte-identity and fact-invariance rates in the
README and `/v1/metadata`. (c) Collapse the output manifold so divergence is cosmetic: the
ledger fixes the facts, the schema fixes the structure, the validators fix the constraints.
A divergence that changes a comma but not a single `fact_id`, the `cta`, or the
`judgment_move` is not observable by any grader. (d) If a determinism check is confirmed to
exist, I can pin a per-key persisted composition store and warm it pre-run from the 30
canonical test pairs, making those specific inputs exactly reproducible.

### W3 — My variance is higher, and variance is asymmetric here.

A template engine's worst message is bland; mine can be wrong. A single hallucinated
competitor name or invented molecule is the *most-cited* fast-reject in the entire package,
and a judge who sees one may distrust the rest. Meanwhile the cost of my best message over
the template's best message is capped at ~15 points per message, but the cost of a
fabrication is described as "scores lowest" — a cliff, not a slope. I am trading a bounded
upside against an unbounded downside unless the verifier is genuinely airtight.

**Mitigation.** (a) The orphan-numeral scan (§4.3) is a *closed-world* check: anything that
looks like a fact and is not claimed in `facts_used` blocks the send. It fails closed, not
open. (b) The catalog-vs-active-offer distinction is enforced in code, killing the exact
error that cost Cases 3 and 6 their points. (c) The `competitor_opened` recipe explicitly
forbids inventing a name and prefers abstention — I would rather send nothing than name a
competitor that does not exist. (d) Abstention is wired all the way through: the composer
can set `send=false`, the ranker can drop, the tick can return `[]`. The system is designed
so that *the floor of the distribution is silence, not falsehood.* (e) Pre-run, I score all
30 canonical pairs plus ~60 sampled pairs through the local judge and read every body by
hand; anything with a verifier near-miss gets the recipe tightened.

---

## 7. Predicted attacks and rebuttals

### From the determinism-first architect

**Attack D1** — *"Your `compose()` is not deterministic. The contract states it must be.
A content-addressed cache gives you idempotence, not determinism; you have renamed the
problem. On a cold key, a different machine, a different hour, you produce different bytes,
and you know it — you said so in §2.2."*

**Rebuttal.** I concede the formal point completely and it costs me nothing, because the
contract is a *behavioral* contract executed against a live stateful service that must not
restart (testing brief §12). Within the only execution that is ever graded, identical inputs
produce identical bytes — that is the property the clause exists to buy, and I satisfy it by
construction rather than by hoping a decoder is well-behaved. Then the harder question: what
does your formal determinism *buy*? Nothing in either brief awards a point for it. The
reference harness contains no cross-call determinism check (judge-spec §7.10). The two real
risks it guards — anti-repetition (-2) and reproducible debugging — I handle with
suppression keys and V10, which are deterministic Python that I run and you run identically.
So your determinism is a property with a real cost (it forces the composer to be a function
of a finite feature vector, which is exactly what makes template copy read as template copy)
and an unpriced benefit. I will take measured 98% byte-identity with 100% fact-invariance
and a 44/50 ceiling over proven 100% byte-identity with a 34/50 ceiling, every time.

**Attack D2** — *"You have a fat-tail network dependency inside a 30-second hard timeout,
with -1 per timeout, -2 per malformed response, and disqualification after three healthz
failures. You are betting the entire run on a vendor's p99. I am not."*

**Rebuttal.** This is the strongest attack available and it is aimed at an architecture I am
not proposing. **No judge-facing handler in my design awaits an LLM call.** `/v1/tick` is a
dictionary lookup and a sort with a 1.5-second soft deadline and p99 under 120 ms.
`/v1/context` acks in under 25 ms and enqueues. `/v1/healthz` touches three integers on a
route with no shared locks. `/v1/reply` is the only endpoint with an inline call, it has an
8-second internal deadline against the judge's 30, and its *policy* decision (end / wait —
which is what the auto-reply and hostile scenarios actually grade) is made before any model
is consulted. My timeout exposure is architecturally identical to yours; the difference is
what is in the cache when the tick arrives. And when the cache is cold, I degrade to *your
output* — the TemplateFloor is your architecture, running as my exception handler. You
cannot beat me on the floor and I beat you on the ceiling. The only thing you can attack is
whether the buffer stays full, and the math in §3.2 says the pipeline drains 115 triggers in
about two minutes of aggregate work spread across a 30-45 minute window.

### From the ops / score-maximizing architect

**Attack O1** — *"Do the arithmetic. Phase 2 copy is one bucket; adaptation (+25), replay
(+30), and ops (-20) are the other 75 points, and all of them are engineering, not prose.
The ten reference cases score 44-50, which means copy saturates — the marginal rubric point
from a frontier model over a good template is small, while the marginal risk is large. You
are optimizing the saturated dimension."*

**Rebuttal.** The premise is wrong in two places. First, those ten cases are not the field;
they are the *north star*, hand-written by the challenge authors to show the ceiling. The
judge's actual instruction is "Be STRICT — 5 is average, 7+ is good, 9+ is excellent."
A template bot does not score 47; it scores 6-7 per dimension — decent specificity from
slotted numbers, mediocre compulsion, and a `category_fit` that reads as generic because
voice is the hardest thing to slot. Call it 32/50 against 44/50, across ~48 scored messages.
That gap is not marginal; it is the competition. Second, and more decisive: **Phase 4 is top
10 only.** The +30 is not a bucket you can win — it is a bucket you must *qualify* for, and
qualification is Phase 2 copy. Your architecture optimizes a prize it cannot reach. Third,
adaptation (+25) is *literally* "read a compliance item nobody anticipated and say something
intelligent about it" — that is a language task wearing an engineering costume. And on ops:
I am not conceding that surface to you. I build the same suppression taxonomy, the same
schema completeness guard, the same deadline ladder, the same healthz isolation. LLM-first
is a claim about the composer, not an excuse for sloppy plumbing.

**Attack O2** — *"judge-spec §7 documents that the reference judge only sees active offers,
only the first five taboo words, never mechanically applies penalties, and defaults missing
keys to 5. The fallback scorer literally rewards digit density: `min(10, 3 + nums*2)`. The
optimal play is a short, digit-dense, name-first, trigger-echoing template. You are paying a
frontier model to write prose the grader does not read."*

**Rebuttal.** You are proposing to optimize against a tool whose own documentation says it
is "a local, reference judge simulator — not necessarily the exact grading harness." Every
exploit you named is a *documented defect* in the reference implementation, which is
precisely the class of thing that gets fixed before the real run. Building a strategy on
defects you can enumerate is the highest-variance play in this competition, and the failure
mode is total: if penalties are wired up in the real harness — and the rubric text says they
should be — a digit-dense fabricating bot goes to the bottom, not the middle. Meanwhile,
note what survives *even inside* the defective harness: `category_fit`, `merchant_fit`, and
`engagement_compulsion` are all scored by an actual LLM reading actual free text, with no
keyword shortcut available. That is 30 of the 50 points, ungameable by construction. And
I will take the two exploits that are *safe* and *free* — I never reference a non-active
offer (§4.1 rule 10, validator V7), and I enforce all taboo words rather than the visible
five. Taking the defensive half of an exploit while refusing the offensive half is the
correct risk posture when the harness is known to be a proxy.

### The attack I expect from both, pre-empted

**Attack X** — *"Your verifier strangles the very thing you claim to be selling. The 50/50
IPL message's '-12% covers' is not a field in any context. Your orphan-numeral scan blocks
it. Your best case study would fail your own architecture."*

**Rebuttal.** It would not, and the reason is instructive. The restaurants category context
carries a `seasonal_beats` entry stating that Saturday IPL matches underperform weeknights —
that is why the ledger ingests `seasonal_beats` and `trend_signals` as citable atoms (§4.1
sources 9). The *direction* of the claim is grounded. If the precise figure "-12%" is not in
the beat text, V3 fires and the repair pass rewrites it to the grounded form: "Saturday
matches usually pull covers *down*, not up — people watch at home." That loses perhaps half a
specificity point and keeps the entire contrarian judgment, which is where 4 of the 5
dimensions were earned. That is the correct trade, it is made mechanically rather than by
luck, and it is a trade a template engine never gets to make because it never had the
judgment to protect in the first place.

---

## 8. What I would build first (if this design wins the debate)

1. Server skeleton + `ContextStore` + `/healthz` counters + schema-complete action builder.
   *(Ops floor. Nothing else scores if this is wrong.)*
2. `MerchantDossier` + `FactLedger` + `TemplateFloor` + all 14 validators.
   *(This alone is a complete, shippable, ~32/50 bot. It is also my exception handler.)*
3. Speculation queue + `CompositionCache` + the T2 composer + repair loop.
   *(This is the ceiling. Everything above step 2 is upside with a guaranteed floor.)*
4. `/v1/reply` classifier + policy table + ACTION MODE + its validator.
5. Phase 3 diff machinery + freshness bonus.
6. Angle bank (T1), few-shot skeletons, derivation recipes for all 15 placeholder kinds.
7. Determinism harness + local judge sweep over 90 pairs; hand-read every body.

Note the ordering: **the template engine is step 2, not step 7.** I am not arguing against
building it. I am arguing against *stopping* there.

---

# CROSS-EXAMINATION RESPONSE

I verified every finding against source myself before writing this. Three of the four
sharpest points against me are correct, one of my own worked examples was factually wrong,
and the synthesis I now advocate is closer to ARCH-D's architecture than to my own. What
follows is organized as instructed: concessions, holds, synthesis, and the experiments that
should settle what argument cannot.

---

## 1. WHAT I CONCEDE

### C1 — My attack-(X) pre-rebuttal was factually wrong. The IPL case is a retrieval, not a reasoning leap. (Concede fully; this is the biggest single correction.)

I wrote that the IPL "-12%" lives in `seasonal_beats`, and that if the precise figure were
absent my repair pass would hedge it to a qualitative claim. Both halves are wrong. I read
`pkg/dataset/categories/restaurants.json`:

```json
{"id":"d_2026W17_ipl_window","kind":"seasonal",
 "title":"IPL home-match Saturdays underperformed weeknight matches across metros",
 "source":"magicpin order data, Apr 2026",
 "summary":"Saturday IPL matches shift orders to home-watch parties; restaurant covers
            down 12% vs Saturday average. Weeknight matches drive +18% covers.",
 "actionable":"Push match-night combos on Tue/Wed/Thu match dates only"}
```

It is in `digest`, not `seasonal_beats`. The "-12%" is verbatim. The `+18%` weeknight
counterfactual is verbatim. The source citation is verbatim. And the `actionable` field
**literally prescribes the contrarian action** — "Tue/Wed/Thu match dates only."

ARCH-D's §2.6 is right and I was wrong. Case 5's celebrated judgment decomposes to:
`weekday(match) ∈ {Sat,Sun}` → retrieve the digest item whose `actionable` contradicts the
naive play → substitute an existing active offer. That is a three-clause join. D's
Counter-Indication Table executes it on every Saturday match, provably, and can be
unit-tested. My composer executes it when the item survives into attention and the weekday
reasoning doesn't slip — and D's point about the direction of failure is also correct: when
a model slips here it slips toward quoting "-12%" on a *Tuesday* match, which is a
fabrication against the merchant's own category data.

This was my flagship example. It was the first sentence of my mandated stance. I have to
give it up: **the single most-cited piece of evidence for LLM-first in this package is
better explained by a rule engine than by a language model.** I will not try to salvage it
with a weaker version.

What I still think is true, and it is much narrower than what I claimed: D can enumerate
every contrarian case *this dataset supports today*. D concedes in §6.2 that a Phase-3
digest item introducing a new contrarian relationship has no rule and gets cited faithfully
but not argued against. That residual is real, but it is a fraction of +25, not the spine of
the competition, and I overstated it into a thesis.

### C2 — F2: my speculative-gap claim is refuted. The push→availability gap is seconds or less, not minutes.

I asserted the judge pushes a trigger's context before listing it in `available_triggers`
and called the gap "seconds in the simulator and minutes in the live harness." I verified
this myself and it is backwards.

- `_phase2_short` (judge_simulator.py:671-674): pushes 3 triggers in a loop, then
  **immediately** calls `self.client.tick(trigs)` with those same 3 ids. Gap = three HTTP
  round-trips, on the order of **30-100 ms**.
- `_full` (806-818): pushes 50 merchants then 100 triggers, then ticks `tids[0:5]` — the
  *first* ids pushed. Gap ≈ the remaining ~145 pushes, **1-3 s**. And worse: if I return
  `actions: []` on a cold batch, no LLM scoring happens between batches, so the next tick
  fires immediately. Ticks then arrive back-to-back at ~100 ms intervals and my 8 workers at
  ~1.7 compositions/s cover roughly 8 triggers before all 20 batches are done. In the
  reference simulator my architecture emits almost nothing.
- Real harness (testing-brief §4 Phase 2): step 1 pushes contexts "that happened during this
  tick", step 2 calls `/v1/tick`. Same tick. Answer to F2(a) is **yes**, explicitly.

So: **a trigger can and routinely does appear in `available_triggers` on the same tick it is
first pushed, with a sub-second buffer.** My stated mechanism does not work. This is the
finding I was most exposed to and it lands.

My behaviour in that case (F2(b)) is the degraded path already in §3.4: cache miss →
TemplateFloor if `urgency ≥ 4`, else skip. So the **p99 latency claim survives intact** —
`/v1/tick` still returns in ~120 ms because it never blocks on a model, and I still cannot
time out. What does *not* survive is the quality claim on first appearance. Corrected
statement: *on a trigger's first appearance I ship ARCH-D's output or nothing; I reach my
own ceiling only on second appearance.*

Two repairs survive scrutiny, and I present them as repairs, not as a rescue of the original
claim:

**(a) Tick-to-tick, not push-to-tick.** The real harness runs 12 ticks across 30-45 real
minutes — **2.5-3.75 real minutes between ticks**. Triggers persist across ticks: all 75
generated triggers carry `expires_at: 2026-06-30`, far beyond the window. And I am
*send-budget-constrained*, not supply-constrained: ~48 send slots against 115 triggers.
Deferring a trigger by one tick therefore costs approximately nothing, because there is
always another eligible trigger to fill the slot. The buffer I actually need is tick-to-tick
and the harness guarantees it. This is a weaker and true version of what I originally
claimed.

**(b) Placeholder triggers are precomputable *before the trigger exists*.** This one I think
is genuinely strong and I did not see it when drafting. A generated trigger is
`{id, scope, kind, source, merchant_id, customer_id, payload:{placeholder}, urgency,
suppression_key, expires_at}`. The payload carries no content. `urgency` affects ranking,
not wording; `id` and `suppression_key` are metadata. Therefore **for 75 of 100 triggers the
message body is a pure function of (merchant, kind, customer?)** — all of which arrive during
the 15-minute Phase-1 warmup. Pruned by eligibility, ~400 merchant-scoped and ~400
customer-scoped combinations at 16 workers ≈ 4 minutes inside a 900-second window.

The honest caveat, which I will not bury: **this repair works in the real harness and not in
`judge_simulator`**, because `_warmup` pushes only 5 merchants and zero customers, and
`_full` pushes the rest immediately before ticking. The reference simulator is a hostile
environment for my design specifically. Anyone evaluating me locally on `full_evaluation`
will see my worst face.

### C3 — F3: cross-conversation auto-reply. My classifier misses it. (Concede.)

Verified at judge_simulator.py:693: `self.client.reply(f"conv_auto_{i}", mid, auto_msg, i+1)`
for `i in 1..4` — **four distinct `conversation_id`s**, one merchant, identical text,
`turn_number` 2,3,4,5. My §5.1 classifier keys strike state on `conv` (`conv = conversations.
get_or_create(req.conversation_id)`; `strike 1 → ... strike 3 → end`). Each of the four calls
sees a fresh conversation with strike count zero. I emit the strike-1 "flag it for the owner"
send four times. The scenario prints `"Bot never ended after 4 auto-replies"`.

My detection rule (a) — "normalized-text exact match against a previous inbound turn" — was
also scoped per-conversation. So two of my five detection signals were silently
conversation-local.

The fix is a **merchant-global inbound signature ledger**:

```python
sig = sha1(normalize(message))          # casefold, strip punct/emoji/whitespace-runs
ledger[(merchant_id, sig)] += 1         # NOT keyed on conversation_id
if ledger[(merchant_id, sig)] >= 2 or canned_phrase(message): route = AUTO_REPLY
strikes = ledger[(merchant_id, sig)]    # global strike count drives send→wait→end
```

Second occurrence anywhere for this merchant → `wait`; third → `end`. That reaches `end` by
call 3 of 4 and the scenario returns on the `end` branch.

And to answer the question as asked rather than defensively: **no, an LLM does not help
here, and it is mildly harmful.** This is exact-duplicate detection across a state key. A
hash and a counter solve it completely, in microseconds, with no failure mode. An LLM
classifier examining a single turn in isolation cannot even see the duplication — the signal
is *cross-turn identity*, which lives in my state layer, not in the text. If I had routed
this through a model I would have shipped a worse and slower version of a dictionary lookup.
The moderator's deterministic implementation is the correct one and I would adopt it
unchanged.

More uncomfortably: this is the third instance in this cross-examination where the winning
mechanism is a deterministic check over state. That is a pattern, and it is evidence about
the shape of this problem, not an accident.

### C4 — F1: my fact ledger is Tier-B-heavy, and my derivation recipes are worse. (Concede, with a correction that applies to all three of us.)

I tiered my 13 provenance sources against the judge's actual window (judge_simulator.py
:503-531):

| Source | Tier | Note |
|---|---|---|
| 1. `performance.*` | **split** | `views`, `calls`, `ctr` **visible**; `directions`, `leads`, `window_days`, **both `delta_7d` fields** invisible |
| 2. `peer_stats` + derived deltas | **B** | my self-described "most productive fact factory" — entirely invisible |
| 3. `customer_aggregate` | **B** | invisible |
| 4. `subscription` | **B** | invisible |
| 5. `signals[]` | **A** | visible — but empty for 80% of merchants |
| 6. `offers` active | **A** | visible — but empty for 86% of merchants |
| 7. `review_themes` | **B** | invisible |
| 8. `digest` retrieved | **B** | invisible |
| 9. `seasonal_beats`, `trend_signals` | **B** | invisible |
| 10. `offer_catalog` | **B** | invisible |
| 11. `customer.*` | **split** | `identity` visible; `relationship`, `state`, `preferences`, `consent` invisible |
| 12. `trigger.payload` | **A** | visible — but placeholder for 75% |
| 13. `now` + `days_between` derivations | **B** | the judge has no `now` at all |

**Roughly 3 of 13 fully visible, 3 partially.** And the recipes are worse than the ledger:
`renewal_due` is built entirely on `subscription` (Tier B); `research_digest` on `digest` ×
`customer_aggregate` (both Tier B); `perf_dip` leads with `delta_7d` (Tier B).

The sharpest way to state the real constraint, which I had not seen: **for a thin generated
merchant with a placeholder trigger — the modal case, 40/50 merchants × 75/100 triggers —
the judge's entire verifiable numeric window is exactly three numbers: `views`, `calls`,
`ctr`.** Everything else in any message about that merchant is unverifiable from where the
judge sits.

This yields a design rule I now adopt and believe is correct independent of architecture:

> **Derived arithmetic over `{views, calls, ctr}` is the highest-value fact class in the
> entire dataset**, because it is simultaneously specific, judgment-bearing, and
> judge-verifiable. "2,410 views produced 18 calls — 0.7% of the people who looked actually
> picked up the phone" uses three Tier-A numbers and a ratio the judge can check on its own
> fingers, and it *is* an interpretation rather than a readout.

Concrete changes to my design: the ledger gets a `tier` field; **new validator V15 — every
body must cite ≥2 Tier-A facts, and the first merchant-specific fact in the body must be
Tier-A**; every derivation recipe gets a mandatory Tier-A anchor clause. ARCH-S reached the
same rule independently (§3.2) and got there before me; I am adopting S's formulation.

Two counter-considerations I hold rather than concede, stated in §2 below (H3), because the
coordinator offered them and they are real — but they modify the weight of F1, not its
direction.

**The symmetric finding, offered as a shared result rather than a counterattack:** this cuts
against ARCH-D at least as hard. D's §1.4 "thin merchant is a myth" argument rests on ~40
category facts — `peer_stats`, `digest`, `trend_signals`, `seasonal_beats`, `offer_catalog`
— of which **zero** are in the judge's window; only `voice.tone` and the first five
`vocab_taboo` entries are. And all three of D's "canonical joins" (metric × peer benchmark,
cohort × digest, locality × trend signal) are Tier-B on at least one leg. D's 50-fact floor
is a *provenance* floor, not a *verifiability* floor. None of us gets to claim F1 as an
advantage; it is a constraint on the whole field.

### C5 — ARCH-D's structural claim is correct: the scorer has no cross-message window. (Concede, precisely.)

Verified directly. `LLMScorer.score()` (:504-530) interpolates exactly one `body`, one
trigger, one merchant, one category. `_score_and_display` (:833) is invoked per action.
`all_scores` is a flat list and `_final_summary` (:886-893) averages it with integer
division. There is no comparative or cross-message context anywhere in the scoring path.

So the part of my argument that said a template bot "reads templated across twenty sends"
and "lands in the safe middle of the pack" is **structurally unobservable to the scorer**,
and I withdraw it. "Middle of the pack" in particular implies a relative judgment the scorer
never makes — every message is graded absolutely, in isolation. That framing was rhetoric,
not analysis, and D was right to name it.

What survives, and I think it genuinely does: D's finding kills the *inter*-message variety
argument, not the *intra*-message quality argument. The judge reads one body and asks "is
this a generic nudge? would they reply? be STRICT." A well-built template's problem is not
that message 7 resembles message 3 — it is whatever message 7 looks like read alone. That is
an empirical question about a single body, which is exactly why it belongs in experiment T2
(§4) and not in another paragraph of assertion.

### C6 — ARCH-D's intent-transition finding lands, and my defense concedes his general principle.

Verified at :742-748. `qualifying = ["would you","do you","can you tell","what if","how
about"]`; `actioning = ["done","sending","draft","here","confirm","proceed","next"]`; pass
iff `any(actioning) and not any(qualifying)`. *"Would you like me to send the draft?"*
contains `draft` **and** `would you`, so `any(qualifying)` is true and it takes the explicit
`print_fail("Bot is STILL QUALIFYING after commitment")` branch. That sentence is close to
the modal output of a fluent, well-aligned model told to be helpful after a commitment.

My architecture does handle it — §5.2's ACTION MODE forbids exactly those five phrases,
requires an actioning token, and `V_ACTION` rejects and repairs otherwise. But I will not
hide behind that, because of what it concedes: **the thing that makes my reply safe is a
deterministic validator, not the model.** The model is the failure mode here and the Python
is the fix. That is D's thesis operating inside my design, and D is entitled to the point.

The one thing I contest is D's framing that this is "a place where a template is strictly
more reliable than a model." The reliability comes from the *gate*, and the gate is
architecture-independent — I can CI-assert `V_ACTION` against those exact ten strings
forever, exactly as D can CI-assert a template. What the gate does not supply is the
artifact. D's own canonical realization proves the split: *"Done — drafting your patient-ed
WhatsApp now, 90 seconds... Reply CONFIRM and I'll publish to the 124 high-risk adults"* is
excellent and it is a *promise to produce* a draft. Case 6 (49/50) scored where it did
because it contained the actual three-tier price list. So: **D wins that the mechanism must
be deterministic. D does not win that the content must be.**

### C7 — ARCH-S's intervention ranking is broadly right, and item 9 is aimed at me.

I accept S's ordering of items 1-8 essentially as written, including that zero-defect egress
at 3.0 pts/hr outranks everything I care about. I have no rebuttal to the arithmetic of
"convert every would-be -2 into a 0," and my own build order (§8) already put ops first —
S simply priced it, which I did not.

On S's ~75% figure, I checked it and the situation is more interesting than either of us
said. **The count is right; the inference is unresolved.** Arithmetic: ~48 sends × up to 5
turns ⇒ ~150-200 reply turns against ~48 first sends, so replies are ~75-80% of judged
*interactions*. But in the reference harness, reply bodies are **never rubric-scored** —
`_score_and_display` is called from exactly two places, `_phase2_short`:677 and `_full`:829,
both on `/v1/tick` actions. `_auto_reply`, `_intent` and `_hostile` never call the scorer at
all. Replies are **gated by keyword checks, not scored on the 5 dimensions.**

That cuts two ways and I will state both:

- *Against S's stated mechanism*: replies being 75% of interactions does not make them 75%
  of rubric points, and on the only scorer implementation we have it makes them 0%.
- *For S's conclusion anyway*: if replies are gated rather than scored, the gates are
  deterministic keyword predicates, reply timeouts still cost -1 each against a -20 floor,
  and Phase 4's +30 is explicitly "scored on conversation flow." So conversation handlers
  remain high-value — just for ops and Phase-4 reasons rather than Phase-2 rubric reasons.
  S's ranking survives its own faulty premise.

The part that hurts me: if Phase-2 reply bodies are unscored, then **the marginal value of
LLM-quality reply prose is concentrated entirely in Phase 4, which is top-10-only, which
makes it conditional** — the exact structure I used against S. I claimed in §5.3 that "the
tail is where the points are." On the available evidence, in Phase 2 the reply tail earns no
rubric points at all. I concede that my §5 overstated the LLM's value in `/v1/reply`, and
that correct *policy* (Python) dominates good *prose* (model) there by a wide margin.

---

## 2. WHAT I STILL HOLD

### H1 — The composition ceiling is an unmeasured quantity, and every one of us has asserted it.

I claimed template ≈ 32/50 vs LLM ≈ 44/50. **That number is an assumption I invented. I have
no measurement behind it and I should not have stated it as though I did.** D asserts the gap
is small and has no measurement either; S prices copy at 0.6 pts/hr on estimates explicitly
labelled as estimates.

What I hold is not the number but the claim that it is *the* open variable: the entire debate
reduces to whether that gap is ~3 points or ~12, and all three documents argue it instead of
testing it. This is experiment T2 (§4) and it is cheap. I hold my position conditionally and
will abandon it outright if T2 comes back under ~4 points mean delta.

### H2 — Phase 3 (+25) is where LLM-first retains a real, non-rhetorical edge — but it is smaller than I implied.

D concedes it directly (§6.2): a Phase-3 digest item introducing a contrarian relationship
has no rule, and D's generic seasonal/peer counter-indication can cite it faithfully but
cannot argue against it. The injected content is 5 new digest items per category plus
updated performance — content nobody has seen, by design.

But I now weight this lower than I did, for two reasons I have to include. First, most of
the +25 is *citation*, not *argument* — "detect the version bump and cite the new fact"
(S's S6 read, which I think is right), and D's forced-citation machinery does that
deterministically. Second, the new digest items are Tier-B, so per F1 the judge cannot verify
them either. The edge is real and narrow: it is the delta between *citing* a novel compliance
item correctly and *reasoning* about what it implies for this merchant. Worth some points,
not worth the architecture I built around it.

### H3 — F1 is a constraint on fact *ordering*, not a reason to avoid Tier-B facts.

The coordinator offered two counter-considerations and I hold both, having checked them.

- challenge-brief §16 enumerates what the real judge session receives: this brief, **the base
  dataset**, the injections, the bot artifacts, and the rubric. The reference simulator's
  narrow window is an artifact of one implementation, and judge-spec itself says it is "not
  necessarily the exact grading harness."
- Appendix A's gold-standard message — the authors' own stated bar — cites `digest`
  (`trial_n: 2100`, `JIDA Oct 2026 p.14`) and `customer_aggregate` ("your high-risk adult
  patients"). **Both Tier-B.** If Tier-B facts were fatal, the challenge authors' own
  north-star exemplar would score badly in the challenge authors' own simulator. That is a
  reductio on treating the simulator's window as the specification.

Add the verified mechanics: penalties are never mechanically applied (`_parse_response`
:540-564 reads no `penalties` key, and the required JSON schema has no field for one), the
specificity criterion as written to the judge is a *presence* test ("Numbers... Dates/times...
Source citations"), and the fallback scorer is literally `3 + 2×digit_runs`. So an
unverifiable-but-plausible cited fact is most likely a **specificity asset and a merchant-fit
risk**, not a uniform liability.

Hence: ≥2 Tier-A facts as the verifiable spine, Tier-B for citation and judgment on top, and
the rationale naming Tier-B field paths explicitly so a judge with the dataset can follow
them. That is S's rule and I have adopted it. What I decline is the stronger reading of F1 —
"prefer Tier-A, avoid Tier-B" — which would delete the Case-1 shape, the Case-5 shape, and
Appendix A.

### H4 — The request path must not contain a model, and this is now a point of agreement rather than a dispute.

All three architectures independently converged on: no LLM inside `/v1/tick`, deadline
guillotines, fail-closed egress, healthz with no dependencies. D refuses request-time
generation outright; S budgets it; I moved it off-path via speculation. Nobody is defending
inline composition. I note this because my D2 rebuttal was written against an architecture
nobody proposed, and it should be retired rather than re-argued.

---

## 3. THE SYNTHESIS I WOULD ACCEPT

**ARCH-D's composition engine as the guaranteed primary path, with the LLM demoted to an
offline author and a validated, non-load-bearing upgrade ratchet.** This is materially closer
to D's design than to mine, and I think it is better than what I submitted.

```
/v1/context   → ContextStore (S §4.2, versioned, idempotent, crash-safe) → ack <25ms
                └─► warmup precompute: FactPack + Tier-A/B tagging + D's grammar
                    realization for every eligible (merchant, kind, customer?) pair
                    ⇒ a DETERMINISTIC body exists for every plausible send before
                      any trigger arrives.                        [GUARANTEED FLOOR]
                └─► speculative LLM composer over the same pairs   [UPGRADE, optional]
                    accepted into cache ONLY if it passes: fact ledger, V1-V15
                    (incl. V15 ≥2 Tier-A), plagiarism, anti-repetition, taboo (full list)
                    AND an offline critic scores it above the deterministic body.
                    Otherwise the deterministic body stands.

/v1/tick      → eligibility → suppression → S's p̂ ranker → cache read → emit_action()
                serializer, fail-closed. Never blocks. Upgrade if present, floor if not.

/v1/reply     → merchant-GLOBAL signature ledger (F3) → D's state machine for policy
                AND for ACTION-MODE phrasing (C6). LLM confined to D's §5.2 contract:
                classification only, closed enum, 8 tokens, 3.5s, pre-hedged, circuit-broken.
                Optionally: LLM-authored artifact BODY in the engaged/commit lane only,
                behind V_ACTION, behind the deterministic body already being held.

Ops           → S §4 essentially verbatim: healthz isolation, 255-context warmup gate,
                zero-defect egress, deadline budgets, anti-repetition, deployment discipline.
```

The property that makes this the right answer: **the LLM can be deleted from the running
system at any moment without changing its correctness, its latency, or its floor.** It is a
ratchet over a working product, not a dependency of one. That converts my W1 (correlated
provider failure) and W3 (variance asymmetry) from architectural risks into a feature flag,
and it costs me nothing I can defend — because after C1, C2, C5, C6 and C7, what I can
defend is "a validated upgrade path over a deterministic floor," not "an LLM-first
architecture."

Credit where it is due: the floor is D's, the ops layer and the fact-tiering rule are S's,
and what remains mine is the speculative upgrade harness, the `facts_used` / orphan-numeral
grounding contract, and the offline critic that decides whether an upgrade is actually
better. I think those three are worth keeping and I do not think they are worth the name
"LLM-first."

---

## 4. WHAT SHOULD BE SETTLED BY EXPERIMENT, NOT ARGUMENT

Five tests. T2 is the one that matters; the rest are cheap.

**T2 — The composition gap. (Decides the entire debate. Nobody has run it.)**
Build D's engine and my composer over the same 30 canonical `test_pairs.json` pairs. Score
both through `judge_simulator`'s real `LLMScorer` with a live key, N=3 per message to average
judge noise, blind-shuffled so neither variant is scored in a block.
*Measures*: mean total, per-dimension deltas, variance.
*Decision rule, stated in advance so I cannot move it*: mean delta < 4 points ⇒ D's
architecture wins outright and the speculative composer should be cut entirely; 4-8 points ⇒
the upgrade-ratchet synthesis in §3; > 8 points ⇒ my position was right and the LLM should be
promoted toward primary. **I expect 4-8 and I have no evidence for that expectation.**

**T1 — Tier-A vs Tier-B specificity. (Decides how hard F1 should bite.)**
40 messages in matched pairs: variant (a) three Tier-B facts only, variant (b) the same
message with ≥2 Tier-A facts substituted in. Score both.
*Measures*: per-dimension delta, especially whether `merchant_fit` and `specificity` move in
opposite directions — my H3 predicts exactly that (Tier-B helps specificity, hurts
merchant_fit). If both fall, S's rule should be tightened to a hard Tier-A-only floor for the
first two facts; if neither moves, F1 is a non-finding and D's category-fact engine is
unharmed.

**T3 — Speculation warm-rate.** Instrument a full simulated run; log cache-hit vs floor per
action, bucketed by tick index and by trigger first-appearance. *Decides whether the upgrade
path ever actually fires in the real harness cadence.* If warm-rate on first appearance is
near zero and tick-2 warm-rate is near one, my C2(a) repair is validated; if both are low, the
speculative harness is dead weight and should be cut.

**T4 — Aggregation: mean or sum?** Unresolvable from code — the reference uses a mean
(`// n`, :888-893), the real grader is unknown. S's entire restraint policy and my send budget
both hinge on it. This one cannot be tested locally; it should be treated as an explicit
assumption with a hedged policy (S's Θ=42/B=4 is the right shape) and flipped only if the
organizers clarify. I name it because two of three architectures have load-bearing policy
resting on an unresolved question, and that should be visible rather than implicit.

**T5 — Determinism probe.** As specified in §2.4: 30 pairs × 5 repetitions, cache disabled,
reporting byte-identity and fact-invariance separately. Relevant now mainly to size the
upgrade path's variance, since under the §3 synthesis the deterministic floor is
byte-identical by construction.

---

## 5. Scorecard

| # | Point | Verdict |
|---|---|---|
| C1 | IPL "-12%" is in `restaurants.digest` verbatim with an `actionable` field; Case 5 is a join | **Conceded — my flagship example was wrong** |
| C2 | Trigger can appear in `available_triggers` on the same tick it is pushed; buffer is ~0.05-3s | **Conceded — mechanism refuted; repaired to tick-to-tick + warmup precompute of placeholder kinds** |
| C3 | Auto-reply is cross-conversation (4 conv ids, one merchant) | **Conceded — my classifier fails; deterministic global signature ledger is correct and an LLM does not help** |
| C4 | My ledger is ~3/13 Tier-A; recipes worse | **Conceded — adopting S's ≥2 Tier-A rule as V15. Cuts against D symmetrically.** |
| C5 | No cross-message scoring window | **Conceded — withdrawing "reads templated across 20 sends"** |
| C6 | `"would you"` vetoes the intent gate | **Conceded on mechanism (validator, not model, is the fix); contested on content** |
| C7 | S's ranking; replies ~75% of interactions | **Ranking conceded; mechanism corrected — replies are gated, not rubric-scored (:677, :829). Weakens S's premise and my §5 equally.** |
| H1 | 32-vs-44 is an unmeasured assertion | **Held conditionally — abandoned if T2 < 4 points** |
| H2 | Phase-3 novel-item reasoning | **Held, downgraded — mostly citation, and Tier-B anyway** |
| H3 | Tier-B is an ordering constraint, not a prohibition | **Held — Appendix A and brief §16 are the evidence** |
| H4 | No model in the request path | **Not in dispute; my D2 rebuttal retired** |

I came into this round holding that the winning bot is an LLM composer with deterministic
guardrails. I leave it holding that the winning bot is a deterministic composer with a
validated LLM upgrade path, and that whether the upgrade is worth building at all is an
empirical question (T2) that I asserted an answer to without evidence and should not have.
ARCH-D was right about the IPL case, right about the scoring window, and right about the
intent gate. ARCH-S was right about the ranking and reached the fact-tiering rule first.
