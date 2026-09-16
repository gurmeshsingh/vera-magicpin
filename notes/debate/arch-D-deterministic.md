# Architecture D — Determinism-First ("The Composition Engine")

**Author:** ARCHITECT-D
**Stance:** The winning bot makes **zero LLM calls in the `/v1/tick` hot path** and at most one
bounded, non-generative LLM call in `/v1/reply`. Message quality is produced by a compiled
composition engine over the four pushed contexts, not by a model at request time.

---

## 0. Thesis in one page

The contract is a **grounding contract wearing a writing contract's clothes.**

Read the judge prompt (judge-spec §1). It scores five things. Four of them —
specificity, category fit, merchant fit, trigger relevance — are *retrieval and binding*
problems, not prose problems. They are scored on whether specific field values from the
pushed contexts appear, correctly framed, in the body. The fifth, engagement compulsion, is
scored on whether an enumerable set of levers is present: binary CTA, effort cap,
loss aversion, social proof, reciprocity, asking-the-merchant. Every one of those is a
structural property of a message, not an emergent property of a language model.

Five facts about this specific challenge push hard toward determinism:

1. **The contract literally demands it.** challenge-brief §7.1: *"Must be deterministic
   given the same inputs (set temperature=0 if using LLMs)."* Temperature 0 is not
   determinism — it is a low-variance sampler over a non-stationary remote service. The
   only way to satisfy the stated contract as written is to not depend on the service.

2. **The budget is brutal and adversarially shaped.** 30s per `/v1/tick`, up to 20 actions
   (testing-brief §5). Twenty sequential composer calls at a realistic 1.5–3s p50 is
   30–60s — an instant timeout. Twenty *parallel* calls does not save you: the response
   time of a fan-out is the **max** of the members, and the median of the max of 20 draws
   sits near the p95 of a single call (commonly 8–15s on a loaded frontier endpoint),
   before any 429. And the tick is not the only clock: each action spawns a judge sub-LLM
   merchant reply and up to 5 `/v1/reply` turns, each with its own 30s window
   (testing-brief §4 Phase 2). Volume of LLM-composed actions is a *compounding* latency
   liability. The deterministic path composes an action in single-digit milliseconds.

3. **Operational penalties are the largest single controllable block.** Ops is worth
   **−20** (testing-brief §4 Phase 5), and the failure table (§10) prices it: −1 per tick
   timeout, −1 per reply timeout, −2 per malformed, −2 per repeat, **−10 for three
   consecutive healthz failures**. Every one of those is an LLM-dependency failure mode.
   A bot with no provider in the request path cannot time out, cannot get rate-limited,
   cannot emit malformed JSON because the model wrapped its output in prose, and cannot
   drift into a verbatim repeat.

4. **There is very little for a model to reason over.** From the data dictionary:
   **86% of merchants have zero offers, 84% zero conversation history, 80% zero signals,
   86% zero review themes**, and **75% of triggers carry a flat placeholder payload**
   `{"placeholder": true, "metric_or_topic": kind}` with no numbers, dates or entities.
   An LLM handed a placeholder trigger and an empty-offers merchant has exactly two
   options: find the facts elsewhere in the pushed contexts (which is a *join*, and a
   join is what engines do reliably), or invent them (which is the named lowest-scoring
   behavior: *"Bots that hallucinate score lowest"*).

5. **The scored examples are one grammar.** All ten cases, 44–50/50, are the same four
   moves in the same order: name-first hook that states why-now → 2–4 traceable numbers
   with a source → one line of interpretation/judgment → one low-friction ask with an
   effort cap. The 44/50 (Case 4) is not the most templated; it is the one with the
   *fewest numbers*. The judge rewarded density and provenance, not novelty.

**The corollary that decides the whole debate:** the judge sees **one body at a time.**
The scoring prompt (judge-spec §1) interpolates a single action's body, its trigger, its
merchant, its category. There is no cross-message context in the scoring window. "It reads
templated across twenty sends" is a critique a human reviewer can make and the scorer
structurally cannot. Meanwhile *every* dimension the scorer *can* see rewards exactly the
thing a compiled engine is best at: putting the right verifiable field value in the right
rhetorical slot, every time, in 4ms.

I am not arguing that an LLM is useless here. I am arguing that its value is **authoring
time**, not **request time** — and that moving it there is free quality plus a −20 penalty
block converted into a zero.

---

# 1. The Composition Engine

## 1.1 Pipeline

```
/v1/context push
   └─► ContextStore.upsert(scope,id,version)            [idempotent, atomic]
         └─► DeltaLog.record(prev,next)                 [structured diff]
               └─► FactPack.rebuild(merchant|category)  [dirty-marked, lazy]
                     └─► AngleBank.rebuild(merchant)    [precomputed candidates]

/v1/tick
   └─► CandidateSet ← triggers ∩ AngleBank ∩ available_triggers
         └─► Ranker.score()            [pure arithmetic]
               └─► Gates.apply()       [silence rules, suppression, cadence]
                     └─► Composer.realize()  [grammar + slots + FactPack]
                           └─► Verifier.check()  [provenance, taboo, URL, similarity, schema]
                                 └─► actions[]
```

Nothing in that chain performs I/O. The entire tick for 20 candidate merchants is
bounded by a few hundred microseconds of dict lookups and string formatting. The 30s
budget is spent almost entirely unspent — which is the point: it is **held in reserve as
ops headroom**, so a slow container, a GC pause, or a burst of concurrent reply turns
still lands inside the window.

## 1.2 The message grammar

A body is a sequence of **moves**. Each move has a category-scoped set of **realizations**.
Each realization is a template over **slots**, plus a declared set of required and optional
slots.

```
BODY := SALUTE · HOOK · EVIDENCE · [PEER_FRAME] · JUDGMENT · ASK · [CITE]
```

| Move | Job (maps to rubric dimension) | Required slots | Elidable? |
|---|---|---|---|
| `SALUTE` | merchant fit — name-first, no throat-clearing | `{addressee}` | no |
| `HOOK` | trigger relevance — states *why now*, names the event | `{why_now_anchor}` | no |
| `EVIDENCE` | specificity — 2–4 traceable numbers | `{fact_a}`,`{fact_b}` | no |
| `PEER_FRAME` | specificity + social proof lever | `{peer_metric}`,`{peer_gap}` | yes |
| `JUDGMENT` | trigger relevance (the Case-5 differentiator) | `{verdict}`,`{verdict_basis}` | yes |
| `ASK` | engagement compulsion — one binary ask + effort cap | `{ask_verb}`,`{deliverable}`,`{effort_cap}` | no |
| `CITE` | specificity — source citation (caps at 7 without it) | `{source}` | yes, but **mandatory whenever a research/compliance/trend claim is present** |

Grammar invariants enforced by the Verifier, not by authoring discipline:

- **Exactly one `ASK`.** Multi-CTA is a named anti-pattern (brief §11).
- **`ASK` is last.** "Buried call-to-action" is a named anti-pattern.
- **`CITE` fires iff a `digest`/`trend_signals`/`seasonal_beats`-derived claim is bound.**
  Missing citation on a research claim caps the case at 7 (scored-examples §3.1).
- **`SALUTE` binds `owner_first_name` when present.** Generic "Hi" costs 1 point on
  merchant fit (scored-examples §3.3).
- **No `SALUTE` re-introduction after turn 1** in a conversation ("Re-introducing yourself
  after the first message" — brief §11).
- **≥3 provenance-backed numeric facts in the body**, else the composition is rejected and
  the trigger falls through to silence (§2.3, Evidence Floor).

### Realization examples (dentists, merchant-facing, `perf_dip` family)

```
HOOK.dentists.perf_dip.r1  = "{metric_label} down {delta_abs_pct} w/w"
HOOK.dentists.perf_dip.r2  = "{metric_label} slipped {delta_abs_pct} this week"
HOOK.dentists.perf_dip.r3  = "Flagging a {delta_abs_pct} drop in {metric_label}"
HOOK.dentists.perf_dip.r4  = "{delta_abs_pct} off your {metric_label} this week"

EVIDENCE.dentists.above_peer.r1 =
  "your CTR is {ctr_pct} against the {peer_ctr_pct} {peer_scope_label} median and {second_metric_label} are up {second_delta_pct} in the same week"
EVIDENCE.dentists.above_peer.r2 =
  "but {ctr_pct} CTR vs a {peer_ctr_pct} peer median, with {second_metric_label} {second_delta_dir} {second_delta_pct}, says the listing is converting"

JUDGMENT.generic.reach_not_conversion.r1 =
  "so the drop is reach, not conversion"
JUDGMENT.generic.reach_not_conversion.r2 =
  "I wouldn't read that as a listing problem"

ASK.reciprocity_binary.r1 =
  "Want me to put together a {effort_cap} {deliverable}?"
ASK.reciprocity_binary.r2 =
  "Say the word and I'll draft {deliverable} — {effort_cap}."
ASK.reciprocity_binary.r3 =
  "I'll draft {deliverable} ({effort_cap}) — {yes_token}?"
```

Authoring scope: **10 high-frequency trigger families × 5 categories × ~5 realizations per
move × 7 moves**. That is a real but finite authoring job (~250–350 authored strings), and
it is exactly the job an LLM should do — offline, reviewed, frozen, unit-tested. LLM
leverage without LLM runtime risk.

## 1.3 Slot taxonomy

Every slot is a typed resolver with a **source path**, a **fallback chain**, a
**formatter**, and a **provenance tag**. A slot that cannot resolve returns `⊥`; a
realization with any required slot `⊥` is ineligible.

```python
Slot(
  name        = "peer_ctr_pct",
  sources     = ["category.peer_stats.avg_ctr"],
  fallbacks   = [],                       # no invented fallback, ever
  formatter   = pct1,                     # 0.030 -> "3.0%"
  provenance  = "category:{slug}:peer_stats.avg_ctr",
  kind        = NUMERIC,
)
```

**The slot families:**

| Family | Slots | Primary source |
|---|---|---|
| Identity | `addressee`, `biz_name`, `locality`, `city`, `years_open` | `merchant.identity.*` (`established_year` → `2026 - y`) |
| Performance | `views`, `calls`, `directions`, `ctr_pct`, `leads`, `delta_views_pct`, `delta_calls_pct`, `delta_ctr_pct`, `window_days` | `merchant.performance.*` |
| Derived-perf | `ctr_vs_peer_rel`, `calls_per_1k_views`, `lead_conv_pct`, `delta_abs_pct`, `delta_dir` | arithmetic over the two above, **transparently phrased** |
| Peer | `peer_ctr_pct`, `peer_views`, `peer_calls`, `peer_rating`, `peer_reviews`, `peer_photos`, `peer_post_freq_days`, `peer_scope_label`, `peer_retention_pct` | `category.peer_stats.*` with a **per-category key map** (dentists→`retention_6mo_pct`, gyms→`monthly_churn_pct`/`trial_to_paid_pct`, pharmacies→`delivery_share_pct`/`repeat_customer_pct`, restaurants→`retention_30d_pct`, salons→`retention_3mo_pct`) |
| Cohort | `cohort_n`, `cohort_label`, `lapsed_n`, `retention_pct`, `delivery_orders`, `dine_in_orders`, `chronic_rx_n` | `merchant.customer_aggregate.*` — **loose bag**, probed by key presence, never assumed |
| Digest | `digest_title_short`, `digest_stat`, `digest_n`, `digest_source`, `digest_deadline`, `digest_credits`, `digest_actionable` | `category.digest[selected]` |
| Trend | `trend_query`, `trend_delta_yoy`, `trend_age_band`, `trend_skew` | `category.trend_signals[*]` |
| Season | `season_window`, `season_note` | `category.seasonal_beats[*]` matched against `now.month` |
| Offer | `offer_title`, `offer_price`, `offer_started`, `catalog_offer_title` | `merchant.offers[status==active]` → fallback `category.offer_catalog` filtered by `audience` (**never** an expired merchant offer — judge-spec §7.7: expired offers are invisible to the judge and referencing one reads as fabrication) |
| Review | `review_theme`, `review_n`, `review_quote`, `review_sentiment` | `merchant.review_themes[*]` |
| Subscription | `days_remaining`, `days_since_expiry`, `plan`, `sub_status` | `merchant.subscription.*` — **hard branch on `status=="expired"`**, never "renewal upcoming" |
| Trigger | `why_now_anchor`, `trigger_metric`, `trigger_delta`, `trigger_deadline`, `trigger_entity` | `trigger.payload.*` — resolves to `⊥` on placeholder payloads, triggering fact substitution (§2.3) |
| Customer | `cx_name`, `cx_last_visit`, `cx_gap_months`, `cx_visits`, `cx_services`, `cx_state_label`, `cx_slot_pref`, `cx_lang` | `customer.*` |
| Rhetoric | `effort_cap`, `yes_token`, `deliverable`, `verdict`, `verdict_basis` | rule base + authored, **non-numeric** |

**Derived facts must be transparently derived.** `ctr_vs_peer_rel` is never rendered as a
bare number; its realizations are `"{ctr_pct} against the {peer_ctr_pct} median"` — both
operands shown. The judge can verify both from the prompt it receives. A derived number
whose operands are hidden is indistinguishable from a fabricated one, and scored-examples
§2 is explicit: *"Numbers without provenance get scored as fabrication."*

## 1.4 Where specificity actually comes from — and why "thin merchant" is a myth

This is the load-bearing empirical claim of this architecture, so state it precisely.

A **generated ("thin") merchant** — 40 of 50 — carries zero offers, zero history, zero
signals, zero review themes. It still carries:

```
views, calls, directions, ctr, leads, window_days,
delta_7d.views_pct, delta_7d.calls_pct,
customer_aggregate.total_unique_ytd,
subscription.days_remaining | days_since_expiry,
identity.established_year, identity.locality, identity.city
```

= **13 field-level facts**, all numeric or proper-noun, all traceable.

Its **category context** — identical for all 10 merchants in the vertical, always fully
populated, never thin — carries:

```
peer_stats:      9–11 numeric benchmarks
digest:          5 items, each with title + source + summary + actionable,
                 several with trial_n / date / credits / price
trend_signals:   4 items, each with query + delta_yoy + segment_age + skew
seasonal_beats:  3–5 windows with notes
offer_catalog:   8 service@price offers with values and audiences
voice:           11–16 allowed terms, 4–7 taboo terms, salutation templates
```

= **~40 further facts**, of which ~25 are numeric or citable.

So the worst-case merchant in this dataset supplies **50+ provenance-backed facts** to a
composer that knows how to join them. The "thinness" is entirely in the four merchant
arrays that are *optional colour*, not in the spine. Getting 3–5 traceable numbers into
every body is not a stretch goal; it is the floor, and the Evidence Floor gate (§2.3)
enforces it as a hard precondition of sending at all.

The three canonical joins, available for *every* merchant in the dataset with no trigger
payload at all:

1. **Merchant metric × peer benchmark.** `performance.ctr` vs `peer_stats.avg_ctr`
   → two numbers, a gap, and the social-proof lever the brief names as production Vera's
   biggest miss (brief §10, lever #3).
2. **Merchant cohort × category digest.** `customer_aggregate.*` × the digest item whose
   `patient_segment`/`summary` matches → the Case-1 shape ("relevant to *your* high-risk
   adults"), with a real citation.
3. **Merchant locality/category × trend signal or seasonal beat.** `identity.locality` ×
   `trend_signals[*].query` + `delta_yoy` → a local, dated, cited claim.

## 1.5 Fact selection: guaranteeing 3–5 numbers, and the right three

`FactPack(merchant)` is a precomputed list of `Fact` records built at context-push time:

```python
Fact(
  id          = "perf.ctr_vs_peer",
  value       = 0.046,
  rendered    = "4.6%",
  operands    = [("merchant.performance.ctr", 0.046),
                 ("category.peer_stats.avg_ctr", 0.030)],
  provenance  = "merchant:m_011:performance.ctr | category:dentists:peer_stats.avg_ctr",
  kind        = COMPARATIVE,
  salience    = 0.81,          # |z| against peer, clipped
  polarity    = +1,            # above peer
  freshness   = 0,             # ticks since first seen
  origin_ver  = 1,
)
```

At compose time the `FactSelector` picks a **fact triple** under constraints:

```
anchor    : the why-now fact. Must be causally tied to the trigger family.
contrast  : a peer/benchmark or opposing-direction fact. Supplies the JUDGMENT basis.
scope     : a cohort/roster/volume fact. Supplies "how much does this matter to me".
+ effort_cap  (non-numeric but reads as an anchor: "10 minutes", "90 seconds")
+ price       (when an offer is bound: "₹499")
```

Selection is a deterministic argmax over `salience × family_weight × (1 + freshness_bonus)`
with a diversity constraint: no two facts in a triple may share a source path prefix. This
mechanically produces the 3–5-number density that separates the 50/50 cases from the 44/50
case, *and* it produces the right shape: anchor answers "why now", contrast answers "so
what", scope answers "why me".

## 1.6 Variation without randomness

Determinism and monotony are not the same thing. Variation is produced by **deterministic
dispersion**, not sampling.

```python
def surface_index(*coords, salt, modulus):
    h = blake2s(b"|".join(c.encode() for c in coords), key=salt, digest_size=8)
    return int.from_bytes(h.digest(), "big") % modulus
```

Each move draws its realization from an **independent hash coordinate**, so the surface
space is multiplicative, not additive:

```
hook_idx     = surface_index(merchant_id, family, "hook",     salt=S, modulus=|HOOK|)
evid_idx     = surface_index(merchant_id, family, period,"ev", salt=S, modulus=|EVID|)
judg_idx     = surface_index(merchant_id, verdict_rule_id,"jd",salt=S, modulus=|JUDG|)
ask_idx      = surface_index(merchant_id, family, period,"ask",salt=S, modulus=|ASK|)
```

With 5 hooks × 4 evidence frames × 4 judgments × 5 asks that is **400 surface shapes per
(category, family)** before slot content varies — and slot content varies by construction,
because every merchant has different numbers.

Three additional mechanisms:

- **Batch de-similarity.** Within a single tick's action list, after composing all
  candidates, compute pairwise character-trigram Jaccard. Any pair ≥ 0.45 → the
  lower-ranked action re-composes at `idx+1` (deterministic escalation, capped at 4 tries,
  then dropped). Deterministic, because the candidate set and its order are deterministic.
- **Run-level ledger.** A `SurfaceLedger` counts realization usage across the whole test
  window; the selector adds a `−0.3 × uses` penalty so realizations rotate rather than
  clustering on hash collisions. Still a pure function of the (deterministic) event order.
- **Anti-repetition hard guard.** Normalized body hash per `conversation_id`. Collision →
  escalate variant; exhausted → return no action. This makes the −2 anti-repetition
  penalty (testing-brief §10) structurally unreachable.

**The determinism guarantee stated precisely:** identical `/v1/context` history + identical
`/v1/tick` sequence ⇒ byte-identical `actions[]`. Variation exists *across* merchants and
*across* time, never across replays. That is what challenge-brief §7.1 actually asks for,
and a temperature-0 LLM cannot promise it.

## 1.7 Voice, vocabulary, taboo

Compiled per category at the moment the category context is pushed:

```python
VoicePack(
  slug             = "dentists",
  register         = "respectful_collegial",
  salutation_tpls  = ["Dr. {first_name}", "Doc"],
  allowed_terms    = {"fluoride varnish","scaling","caries","occlusion","bruxism",
                      "endodontic","periodontal","implant","aligner","veneer",
                      "OPG","IOPA","RCT","CAD/CAM","zirconia","PFM"},
  taboo_rx         = compile_taboo(voice.vocab_taboo),
  emoji_policy     = EmojiPolicy(merchant_facing=0, customer_facing=1, set="🦷"),
  code_mix_level   = CodeMix.NATURAL,        # gyms => CodeMix.ENGLISH_PRIMARY
)
```

**Vocabulary is not stuffed, it is authored in.** Each category's move realizations are
written using that category's own lexicon and register — `"case-mix"`, `"recall interval"`,
`"aligner"` for dentists; `"covers"`, `"AOV"`, `"table turnover"` for restaurants;
`"footfall"`, `"churn"`, `"trial-to-paid"` for gyms; `"molecule"`, `"Schedule H1"`,
`"MRP"` for pharmacies; `"balayage"`, `"keratin"`, `"slot"` for salons. A post-compose
assertion requires **≥1 allowed-vocab term per merchant-facing body**; failure → next
realization. This is the mechanical answer to scored-examples §3.7 ("Wrong or absent
domain vocabulary signals the bot didn't actually use the CategoryContext.voice").

**Taboo matching is phrase-level with parenthetical stripping.** The raw lists contain
entries like `"FDA-approved (use only when actually applicable)"` and
`"doctor recommended (without disclosure)"`. `compile_taboo` strips the parenthetical,
normalizes whitespace and case, and builds word-boundary phrase regexes:

```
r"\bFDA[- ]approved\b" | r"\bdoctor[- ]recommended\b" | r"\b100% safe\b" | r"\bbest in city\b" | ...
```

Crucially it is **phrase**-level, not token-level. Salons ban `"best in city"`. A merchant
review quote reads *"Priya is the best for balayage"*. A naive token blocklist on `"best"`
destroys a 12-occurrence positive review theme that is one of the strongest merchant-fit
facts available. Phrase matching keeps it. (And when a merchant-supplied string *does* hit
a taboo, the fix is to drop that slot, not the whole message — the taboo belongs to *our*
copy, and quoting a customer is not a claim we made.)

**Emoji policy** is a table on `(send_as, register)`. Merchant-facing operator/clinical
registers: zero. Customer-facing warm registers: at most one, from a per-category map.
This reproduces exactly the pattern in the scored set (emoji in Cases 2/3/8, all
customer-facing; zero in Cases 1/5/6/7/9, all merchant-facing).

**URLs: never.** challenge-brief §5 constraint 4 says URLs are allowed; api-call-examples
F.4 says a URL is a hard fail at −3. The conflict resolves conservatively: a Verifier
regex rejects any body containing a scheme, a bare domain, or a `wa.me`-style handle.
There is no upside that justifies a −3 exposure.

## 1.8 Hindi-English code-mix, deterministically

Code-mixing is where an LLM-first design *sounds* stronger and is actually riskier: awkward
Hinglish, Devanagari where romanized was wanted, mixing inside a clinical claim, or ignoring
the preference entirely (a named anti-pattern, brief §11). The deterministic approach is an
**overlay, not a translation.**

A curated bilingual phrase bank, authored once per category, pairs an English move
realization with a romanized-Hindi equivalent at the **move** level:

```
ASK.reciprocity_binary.r3
  en  : "I'll draft {deliverable} ({effort_cap}) — {yes_token}?"
  hien: "Main {deliverable} draft kar deti hoon — {effort_cap}. {yes_token}?"

SLOTS.slots_offer
  en  : "{n} slots are open for you: {slot_a} or {slot_b}."
  hien: "Apke liye {n} slots ready hain: {slot_a} ya {slot_b}."

REFILL.runout
  en  : "runs out on {date}"
  hien: "{date} ko khatam ho jayengi"

CLOSE.confirm
  en  : "Reply CONFIRM to dispatch, or call if the dose has changed."
  hien: "Reply CONFIRM karke dispatch karwa dijiye, ya dose change ho to bata dijiye."
```

**Four hard rules, enforced by the Verifier:**

1. **Never code-mix a clinical, regulatory, or safety claim.** Molecule names, batch
   numbers, dose limits, compliance deadlines stay in English. (Pharmacies and dentists
   are the regulated categories; garbled Hinglish on a recall is a real-world harm shape
   and a category-fit disaster.)
2. **Never code-mix numerals, currency, or units.** `₹1,420`, `4.6%`, `28 April` render
   identically in both lanes. This also keeps the provenance verifier trivial.
3. **Mix at most N moves**, where N is set by a register ladder:

   | Signal | Lane |
   |---|---|
   | customer `language_pref == "en"`, or category `code_mix == english_primary_some_hindi` (gyms) | N = 0 (english-primary; at most one Hindi interjection allowed for gyms) |
   | `language_pref == "hi-en mix"`, or merchant `languages ∋ "hi"` and category `code_mix == hindi_english_natural` | N = 1 for merchant-facing (the `ASK` only — lowest-risk move), N = 2 for customer-facing (`SLOTS`/`CLOSE`) |
   | `language_pref == "hi"` | Hindi-primary skeleton: all connective moves in romanized Hindi, English retained for facts, molecules, prices |
4. **Romanized Devanagari only.** Matches every scored example and the production
   transcripts in brief §9.

Regional third languages (`mr`,`ta`,`te`,`kn` on generated merchants) are **acknowledged,
not attempted**: the engine never composes in a language it has no authored bank for, and
never claims to. Attempting Kannada from a template bank we didn't write is a worse failure
than not attempting it.

## 1.9 Rationale generation — the free 3 points nobody takes

The FAQ says the rationale is scored (*"did the rationale match the actual output?"*) and
scored-examples §3.10 says mismatch is penalized. Almost every entrant will stub it.

The deterministic engine gets rationale correctness **structurally for free**, because it
already holds the binding record. The rationale is serialized from the actual composition
trace:

```
"Trigger perf_dip (urgency 2, placeholder payload) re-grounded from
 merchant.performance.delta_7d.views_pct = -0.20. Counter-indication R-DEN-03 fired:
 merchant.performance.ctr (0.046) exceeds category.peer_stats.avg_ctr (0.030) and
 delta_7d.calls_pct is +0.16, so the dip is top-of-funnel reach, not listing conversion —
 message reframes rather than prescribing a listing fix. Secondary fact:
 subscription.status = expired, days_since_expiry = 28. Curiosity hook bound to
 category.trend_signals['clear aligners'] (+62% YoY, 28-45) for the merchant's locality.
 Single binary CTA, effort capped at 5 minutes. Suppression perf:m_011:2026-W17."
```

An LLM that writes both the body and the rationale can drift between them. An engine that
writes the rationale *from the binding it actually used* cannot. This is a small, certain,
uncontested scoring surface.

## 1.10 Worked example — THIN merchant

**Inputs** (real dataset records):
`m_011_dr_sameer_dentist_bangalore` — Bright Smile Dental, Dr. Sameer, Indiranagar
Bangalore, languages `[en,hi,kn]`, established 2013. Subscription **expired**, 28 days
since expiry. Performance: views 4,792 (**−20% w/w**), calls 55 (**+16% w/w**),
directions 138, ctr **0.046**, leads 27. `offers: []`, `conversation_history: []`,
`signals: []`, `review_themes: []`, `customer_aggregate: {total_unique_ytd: 1905}`.
Category `dentists`: `peer_stats.avg_ctr 0.030`, scope `metro_solo_practices_2026`;
`trend_signals` includes `clear aligners` +62% YoY, 28–45 band.
Trigger: a **generated** `perf_dip`, urgency 2, payload `{"placeholder": true,
"metric_or_topic": "perf_dip"}`.

**Engine trace:**
```
trigger.payload  -> placeholder; {trigger_metric},{trigger_delta} = ⊥
FactSubstitution -> anchor := perf.delta_views (-0.20)      [merchant.performance.delta_7d.views_pct]
                    contrast := perf.ctr_vs_peer (4.6/3.0)  [above peer, polarity +1]
                    scope   := sub.days_since_expiry (28)   [merchant.subscription]
CounterIndication R-DEN-03 MATCH
   (delta_views < 0) ∧ (ctr > peer_ctr) ∧ (delta_calls > 0)
   -> verdict = "reach_not_conversion"; suppress listing-remediation asks
EvidenceFloor    -> 8 numeric facts bound ≥ 3  PASS
Voice            -> allowed term "aligner" present  PASS
Taboo            -> 0 hits  PASS   URL -> none  PASS
CodeMix          -> merchant.languages ∋ hi, category code_mix = hindi_english_natural
                    -> N=1, ASK move only
```

**Composed action:**
```json
{
  "conversation_id": "conv_m_011_perf_2026W17",
  "merchant_id": "m_011_dr_sameer_dentist_bangalore",
  "customer_id": null,
  "send_as": "vera",
  "trigger_id": "trg_0xx_perf_dip_m_011",
  "template_name": "vera_perf_reframe_v1",
  "template_params": [
    "Dr. Sameer",
    "views down 20% w/w",
    "CTR 4.6% vs 3.0% peer median, calls up 16%",
    "Pro plan lapsed 28 days ago",
    "5-minute restore plan + aligner-demand note"
  ],
  "body": "Dr. Sameer — views down 20% w/w, but I wouldn't read that as a listing problem. Your CTR is 4.6% against the 3.0% metro solo-practice median and calls are up 16% in the same week, so the drop is reach, not conversion. One thing worth flagging separately: your Pro plan lapsed 28 days ago. Want me to put together a 5-minute restore plan plus a short aligner-demand note for Indiranagar — searches are +62% YoY in the 28-45 band? Ek line bas — YES.",
  "cta": "binary_yes_no",
  "suppression_key": "perf:m_011_dr_sameer_dentist_bangalore:2026-W17",
  "rationale": "Trigger perf_dip carried a placeholder payload; re-grounded the why-now from merchant.performance.delta_7d.views_pct (-0.20). Counter-indication R-DEN-03 fired: ctr 0.046 > category.peer_stats.avg_ctr 0.030 and delta_7d.calls_pct +0.16, so the dip is reach, not conversion — reframed instead of prescribing a listing fix. Second fact: subscription.status=expired, days_since_expiry=28. Curiosity hook from category.trend_signals['clear aligners delhi'-equivalent, +0.62 YoY, 28-45]. One binary CTA, 5-minute effort cap. Hindi mix limited to the ASK per merchant.identity.languages ∋ hi and category voice.code_mix=hindi_english_natural."
}
```

**Eight traceable numbers** (20%, 4.6%, 3.0%, 16%, 28, 5-minute, 62%, 28-45), a
counter-indicated verdict, a peer benchmark, correct clinical register, zero emoji, one
binary ask with an effort cap, one Hindi connective in the lowest-risk move — composed in
about four milliseconds from a merchant whose `offers`, `signals`, `review_themes` and
`conversation_history` are all empty and a trigger that said literally nothing.

## 1.11 Worked example — RICH merchant

**Inputs:** `m_003_studio11_salon_hyderabad` — Studio11 Family Salon, Lakshmi, Kapra
Hyderabad, `[en,hi,te]`. Active: `Haircut @ ₹99`, `Hair Spa @ ₹499`. Performance: views
4,980 (+14%), calls 62 (**+20%**), ctr **0.048**, leads 38.
`customer_aggregate: {total_unique_ytd: 1150, lapsed_90d_plus: 220, retention_3mo_pct: 0.62}`.
`review_themes`: `stylist_skill` pos ×12 (quote *"Priya is the best for balayage"*),
`saturday_wait` neg ×2. Category `salons`: `peer_stats.avg_ctr 0.040`,
`retention_3mo_pct 0.55`.
Trigger: `review_theme_emerged`, urgency 2.

**Engine trace:**
```
anchor   := review.saturday_wait (n=2, neg, 30d)
contrast := review.stylist_skill (n=12, pos) -> ratio 6:1
CounterIndication R-SAL-02 MATCH
   (neg_theme.occurrences < 3) ∧ (pos_theme.occurrences ≥ 3 × neg)
   -> verdict = "load_not_service"; suppress staffing/remediation asks
scope    := perf.calls_delta (+0.20) ∧ perf.ctr_vs_peer (4.8 vs 4.0)
offer    := merchant.offers[active] -> "Hair Spa @ ₹499"   (NOT category catalog: real one exists)
Taboo    -> salons ban "best in city"; quote contains "best for balayage" -> phrase regex
            r"\bbest in city\b" does NOT match -> quote retained   PASS
CodeMix  -> N=1, ASK move
```

**Composed body:**
```
Lakshmi — Saturday wait showed up in 2 reviews this month, against 12 on stylist skill
("Priya is the best for balayage"). At 2 in 30 days I wouldn't add staff for it; that
reads as load, not service. You already have Hair Spa @ ₹499 running — pointing it at
Mon-Thu pulls the queue off your busiest slot. Calls are up 20% w/w and your CTR is 4.8%
against the 4.0% metro-salon median, so there's demand to move. Main ek weekday-slot GBP
post draft kar deti hoon — 10 minutes. YES?
```

Eight traceable facts (2, 12, 30 days, ₹499, 20%, 4.8%, 4.0%, 10 minutes), a real active
offer rather than a catalog guess, a genuine contrarian verdict ("don't fix the complaint"),
warm-practical register, service@price not percentage-discount, one binary ask. Note the
retained review quote: a token-level taboo filter would have deleted the single most
merchant-specific string available.

---

# 2. The Decision Layer

## 2.1 Candidate construction

At tick, candidates come from three sources:

1. **Pushed triggers** ∩ `available_triggers` ∩ not-expired ∩ merchant known.
2. **Derived triggers** — conditions the engine detects from merchant state that the judge
   never pushed: `subscription.status == expired` → winback; `identity.verified == false`
   → gbp_unverified; `delta_7d.views_pct ≤ −0.20` → perf_dip; `leads == 0 ∧ calls > 0`
   → conversion gap; `days_remaining ≤ 10` → renewal. These make the bot useful when
   `available_triggers` is thin and are gated to *never* outrank a pushed trigger.
3. **Adaptation candidates** — synthesized on a context version bump (§4.3).

## 2.2 The ranker

```python
W = dict(urgency=3.0, evidence=2.5, fit=2.0, novelty=2.5, freshness=1.0, headroom=1.0)

def score(cand, merchant, category, state, now) -> float:
    # --- URGENCY: normalized, with the seed-vs-generated correction -------------
    u = cand.urgency / 5.0
    if cand.kind in SAFETY_KINDS:                 # supply_alert, regulation_change,
        u = max(u, 0.9)                           # recall/compliance: floor high
    # expires_at is NOT a proxy for urgency (all generated triggers share 2026-06-30)
    # so it is used only as a hard expiry gate, never as a score term.

    # --- EVIDENCE: can we actually ground this? --------------------------------
    facts = FactSelector.bind(cand, merchant, category)
    e = min(len(facts.numeric), 5) / 5.0
    if facts.anchor is None:            return SILENT      # hard gate, see 2.3
    if len(facts.numeric) < 3:          return SILENT
    if facts.anchor.requires_citation and facts.citation is None:
                                        return SILENT

    # --- FIT: does this trigger family make sense for this merchant? -----------
    f = FAMILY_CATEGORY_FIT[cand.kind][category.slug]        # 0..1, authored table
    f *= STATE_FIT[cand.kind](merchant)                      # e.g. renewal_due on an
                                                             # expired sub -> 0.0
    # --- NOVELTY: Phase-3 adaptation lever -------------------------------------
    n = 1.0 if facts.anchor.origin_ver > merchant.baseline_ver else 0.0
    n = max(n, 1.0 if facts.anchor.first_seen_at > TEST_START else 0.0)

    # --- FRESHNESS / SEASON ----------------------------------------------------
    s = 1.0 if SeasonMatcher.in_window(category, now) and cand.uses_season else 0.5

    # --- HEADROOM: is there compulsion room left with this merchant? -----------
    h = 1.0 - 0.34 * state.sends_to(merchant.id)      # decays with contact volume

    raw = (W['urgency']*u + W['evidence']*e + W['fit']*f +
           W['novelty']*n + W['freshness']*s + W['headroom']*h)

    # --- PENALTIES -------------------------------------------------------------
    raw -= 4.0 * state.suppressed(cand.suppression_key)       # effectively fatal
    raw -= 2.0 * state.topic_collision(cand.topic, merchant.id, period(now))
    raw -= 1.5 * state.recent_contact_penalty(merchant.id, now)
    raw -= 6.0 * state.opted_out(merchant.id)                 # fatal
    raw -= 6.0 * (not ConsentGate.allows(cand, customer))     # fatal
    return raw
```

Then:

```python
def select(cands, now, state):
    scored = sorted((score(c,...), c) for c in cands, reverse=True)
    out, per_merchant = [], Counter()
    for sc, c in scored:
        if sc is SILENT or sc < SEND_THRESHOLD:     continue
        if per_merchant[c.merchant_id] >= 1:        continue   # one action per merchant per tick
        if state.window_sends[c.merchant_id] >= PER_MERCHANT_WINDOW_CAP: continue
        if len(out) >= TICK_BUDGET:                 break
        act = Composer.realize(c)
        if act is None:                             continue   # composition failed -> silence
        if not Verifier.ok(act, out):               continue
        out.append(act); per_merchant[c.merchant_id] += 1
    return out
```

Constants, and the reasoning behind them:

| Constant | Value | Why |
|---|---|---|
| `SEND_THRESHOLD` | 5.5 / ~11 max | Roughly: a candidate must clear mid-urgency **and** full evidence **and** decent fit. Tuned offline against the 100-trigger set so ~35–45% of available triggers fire. |
| `TICK_BUDGET` | 8 (cap is 20) | Restraint is explicitly rewarded; also bounds the reply-turn load we must serve in subsequent ticks. |
| `PER_MERCHANT_WINDOW_CAP` | 2 (3 if one is a safety kind) | 12 ticks × 50 merchants; two well-aimed sends per merchant beats five. |
| `RECENT_CONTACT_TICKS` | 3 (15 simulated minutes) | Spacing. |
| `EARLY_RESERVE` | ticks 1–3 use `SEND_THRESHOLD + 1.0` | Phase-3 injections land mid-window and are worth up to **+25**. Do not spend a merchant's slot before the new digest arrives. |

## 2.3 The silence rule — when `actions: []` is the right answer

Five **hard gates**. Any one fires → the candidate is dropped, and if all candidates drop,
the tick returns `{"actions": []}`.

1. **Evidence Floor.** Fewer than 3 provenance-backed numeric facts bindable, or no
   trigger-specific `why_now_anchor`. *This is the gate that turns the 75%-placeholder
   problem into an asset.* Consider `competitor_opened` with a placeholder payload: there
   is no competitor name, no distance, no offer, and nothing anywhere else in the pushed
   contexts from which to recover one. An LLM handed this writes *"a new salon opened
   nearby"* — vague at best, fabricated at worst. The engine returns silence. Same for
   `appointment_tomorrow` with no appointment time and `festival_upcoming` with no festival
   named and no `seasonal_beats` window matching `now`.
2. **Citation Gate.** A research / compliance / trend / supply claim without a resolvable
   `source` field. Uncited research caps the score at 7 and risks a fabrication read; not
   sending scores nothing but costs nothing.
3. **Consent Gate.** Customer-scoped candidate where `consent.scope` is empty, or
   `opted_in_at` is null, or `preferences.channel == "none_recorded"`, or
   `reminder_opt_in == false` for a reminder-family trigger, or `phone_redacted` is null.
   (The walk-in customer `c_015_anonymous_for_m010` is exactly this case — a customer we
   legally cannot message. Messaging her is a merchant-fit and judgment failure that an
   LLM with no consent model will happily commit.)
4. **Suppression / opt-out.** Key already burned this period, or the merchant is under a
   hostility/opt-out suppression (§3).
5. **State Contradiction.** The trigger asserts something the merchant state denies:
   `renewal_due` on `status == "expired"`, `perf_spike` when `delta_7d` is negative,
   `gbp_unverified` when `verified == true`, `trial_followup` on a `churned` customer.
   These are silent-or-reroute: `renewal_due` on an expired subscription reroutes to the
   winback family rather than firing a wrong message.

**Silence is also a positive signal.** A tick that returns `[]` with a one-line
`"rationale"`-style log is cheap, and the brief is unambiguous: *"Restraint is rewarded;
spam is penalized."* Note also that the reference scorer aggregates by **average**
(`_final_summary`, integer division across scored messages), so a marginal send does not
add points — it *dilutes* them.

## 2.4 Suppression-key taxonomy

Format: `<topic>:<scope_id>:<period>`. Legible and decodable (scored-examples §3.25).

| Topic | Scope id | Period | Example |
|---|---|---|---|
| `research` | category slug | ISO week | `research:dentists:2026-W17` |
| `compliance` | merchant id | deadline month | `compliance:m_009:2026-12` |
| `alert` | molecule / alert id | month | `alert:atorvastatin:2026-04` |
| `perf` | merchant id | ISO week | `perf:m_011:2026-W17` |
| `milestone` | merchant id + metric | value bucket | `milestone:m_007:reviews:100` |
| `renewal` | merchant id | days bucket | `renewal:m_005:T-7` |
| `winback` | merchant id | month | `winback:m_011:2026-04` |
| `recall` | customer id | cycle | `recall:c_001_priya:6mo` |
| `refill` | customer id | run-out date | `refill:c_014_sharma:2026-04-28` |
| `appt` | customer id | date | `appt:c_033:2026-04-27` |
| `lapse` | customer id | state | `lapse:c_016_tara:hard` |
| `festival` | merchant id + festival | year | `festival:m_003:diwali:2026` |
| `compete` | merchant id + competitor | once | `compete:m_006:sharmas:once` |
| `ask` | merchant id | ISO week | `ask:m_003:2026-W17` |
| `dormant` | merchant id | fortnight | `dormant:m_018:2026-W17-18` |
| `review` | merchant id + theme | month | `review:m_003:saturday_wait:2026-04` |
| `all` | merchant id | TTL | `all:m_022:30d` (opt-out / hostility) |

Two mechanisms beyond exact-key dedupe:

- **Trigger-supplied keys are honored but normalized.** Generated triggers carry junk keys
  like `research_digest:m_017_dr_rajan_dentist_mumbai:gen_26`, where `gen_26` is an index,
  not a period — so the same topic could fire twice under two different `gen_N` keys. The
  engine records **both** the supplied key and its own canonical key, and suppresses on
  either.
- **Topic-collision matrix.** Firing `perf` for a merchant in week W also blocks
  `milestone` and `dormant` for that merchant that week — they would read as three
  different bots messaging the same person about their numbers. Authored as a small
  symmetric matrix over the 17 topics.

## 2.5 Cadence

- ≤ 1 action per `(merchant_id)` per tick (also a stated API rule: one action per
  `(merchant_id, conversation_id)` per tick).
- ≤ 1 action per merchant per 3 ticks.
- ≤ 2 actions per merchant per window (3 if one is a safety kind).
- Tick budget 8; window budget ≈ 45 across 12 ticks and 50 merchants.
- Ticks 1–3 run an elevated threshold (`EARLY_RESERVE`) to preserve merchant slots for
  Phase-3 injected context.
- Safety kinds (`supply_alert`, `regulation_change`, a compliance deadline inside 45 days)
  **bypass** cadence spacing but not consent or suppression.

## 2.6 Case-5 contrarian judgment without an LLM

This is the attack an LLM-first architect will lead with, so it gets the most precise
answer.

**Look at what Case 5 actually did.** The trigger said "IPL match tonight". The bot said
*skip the match-night promo, Saturday IPL shifts covers −12%*. That −12% is not a reasoning
leap. It is **sitting in the restaurants category digest**:

```json
{"id":"d_2026W17_ipl_window","kind":"seasonal",
 "title":"IPL home-match Saturdays underperformed weeknight matches across metros",
 "summary":"Saturday IPL matches shift orders to home-watch parties; restaurant covers
            down 12% vs Saturday average. Weeknight matches drive +18% covers.",
 "actionable":"Push match-night combos on Tue/Wed/Thu match dates only"}
```

The "judgment" is a **join**: trigger date → weekday predicate → digest item whose
`actionable` field contradicts the naive response → existing active offer as the substitute
action. That is a rule, and a rule engine executes it every single time. An LLM executes it
*probabilistically* — and when it misfires it misfires in the expensive direction, quoting
−12% on a Tuesday match, which is a fabrication against the merchant's own category data.

So: a **Counter-Indication Table**. Each row is `(predicate) → (verdict, basis_ref,
suppressed_asks)`, where `basis_ref` is a pointer to the digest item / seasonal beat / peer
stat that justifies the contrarian call — so the contrarian claim is itself
provenance-backed and citable.

| Rule | Predicate | Verdict | Basis |
|---|---|---|---|
| `R-RES-01` | `kind==ipl_match_today ∧ weekday(match) ∈ {Sat,Sun}` | don't run match-night promo; push existing active offer as delivery-only | `restaurants.digest.d_2026W17_ipl_window` (−12% Sat / +18% weeknight) |
| `R-GYM-01` | `perf_dip ∧ month ∈ Apr–Jun` | expected seasonal lull; pause acquisition spend, redirect to retention | `gyms.digest.d_2026W17_resolution_window` ("double down Sept-Oct") |
| `R-DEN-03` | `delta_views<0 ∧ ctr>peer_ctr ∧ delta_calls>0` | reach problem, not conversion; don't prescribe a listing fix | `dentists.peer_stats.avg_ctr` |
| `R-SAL-02` | `neg_theme.n < 3 ∧ pos_theme.n ≥ 3×neg_theme.n` | don't remediate; reframe as load/capacity | `merchant.review_themes` ratio |
| `R-PHR-01` | `festival_upcoming ∨ seasonal ∧ month ∈ Apr–Jun` | don't push cold/cough; ORS + sunscreen + anti-fungal | `pharmacies.digest.d_2026W17_summer_demand` (cold/cough −60%) |
| `R-SAL-04` | `festival/bridal ∧ month ∈ Apr–May` | it's the *mini*-bridal window (~15% of annual), size the ask accordingly | `salons.digest.d_2026W17_bridal_season_start` |
| `R-ALL-01` | `renewal_due ∧ subscription.status=="expired"` | not a renewal; reroute to winback with `days_since_expiry` | `merchant.subscription` |
| `R-ALL-02` | `perf_spike ∧ leads==0 ∧ calls>0` | the spike isn't the story; the lead-conversion gap is | `merchant.performance` |
| `R-GYM-03` | `milestone_reached ∧ churn>peer_churn` | celebrate briefly, pivot to churn | `gyms.peer_stats.monthly_churn_pct` |
| `R-RES-04` | `review_theme_emerged(delivery_late) ∧ delivery_orders > dine_in_orders` | it's a volume-mix problem; fix packaging/ETA before promoting delivery | `merchant.customer_aggregate` |
| `R-PHR-03` | `chronic_refill ∧ generic price-drop item in digest` | offer the generic switch with the saving quantified | `pharmacies.digest.d_2026W17_generic_metformin` (−22% wholesale, ~₹120/mo) |
| `R-DEN-05` | `research_digest ∧ merchant cohort key absent` | don't claim relevance to a cohort you can't see; frame as category-level | absence check |

Plus one **generic** counter-indication: `SeasonMatcher` compares the sign of the
merchant's `delta_7d` against the category's seasonal expectation for `now.month`; a
negative delta inside a known-down window is always reframed rather than alarmed.

Two honest properties of this design:

- It is **enumerable and auditable** — 25-ish rules over 25 digest items, 25 seasonal
  beats, 20 trend signals. I can prove coverage of every contrarian case this dataset
  supports, and unit-test each one.
- It is **brittle to inputs outside the dataset's digest content.** A Phase-3 digest item
  introducing a *new* contrarian relationship will not have a rule. The mitigation is the
  generic seasonal/peer counter-indication above plus the NOVELTY move (§4.3), which can
  cite a new item faithfully even without a rule for it — it just won't argue against it.
  That is a real limit and it is listed in §6.

---

# 3. `/v1/reply` as an explicit state machine

The whole of Phase 4 (+30, top 10) and a large share of the felt "conversation quality" is
here — and every one of the three replay scenarios is a **classification** problem, not a
generation problem.

## 3.1 States

```
OPENED ──first inbound──► CLASSIFY
CLASSIFY ─► { ENGAGED | QUALIFYING | ACTIONING | BACKOFF | DECLINED | CLOSED }

ENGAGED    : real human reply, topic alive
QUALIFYING : we asked, they haven't committed
ACTIONING  : explicit commitment received — execute, never re-qualify
BACKOFF    : auto-reply / defer — wait with an escalating timer
DECLINED   : opt-out or hostility — one graceful line then CLOSED
CLOSED     : terminal; every further inbound returns action:"end"
```

Per-conversation state carried: `turn_number`, `last_outbound_body_hash`,
`inbound_history[]` (normalized), `autoreply_streak`, `thread_anchor` (the trigger +
the concrete deliverable we offered), `commitment_flag`, `offered_artifacts[]`,
`language_lane`.

## 3.2 The classifier — ordered cascade, all deterministic

Order matters; first match wins.

```python
def classify(msg, conv):
    t = normalize(msg)          # lower, strip punct/emoji, collapse ws, romanize-safe

    # 1 AUTO_REPLY  -- two independent detectors, either suffices
    if any(jaccard_tokens(t, prev) >= 0.90 for prev in conv.inbound_history):
        return AUTO_REPLY                    # brief §12 hint: verbatim repeat == auto-reply
    if AUTOREPLY_RX.search(t):
        return AUTO_REPLY
    if conv.seconds_since_outbound < 45 and not has_question(t) \
       and not mentions_any(t, conv.thread_anchor.entities) and len(t.split()) <= 25:
        return AUTO_REPLY                    # instant, generic, entity-free == canned

    # 2 OPT_OUT / HOSTILE
    if OPTOUT_RX.search(t):   return OPT_OUT
    if HOSTILE_RX.search(t):  return HOSTILE

    # 3 COMMITMENT  (checked BEFORE question-detection: "ok lets do it. whats next?"
    #                contains a question mark but is a commitment)
    if COMMIT_RX.search(t):   return COMMIT

    # 4 OFF_TOPIC
    if OFFTOPIC_RX.search(t) and not mentions_any(t, conv.thread_anchor.entities):
        return OFF_TOPIC

    # 5 DEFER
    if DEFER_RX.search(t):    return DEFER

    # 6 INFO_REQUEST
    if has_question(t) or INFO_RX.search(t):  return INFO_REQUEST

    # 7 fallthrough
    return UNCLEAR
```

Pattern banks (bilingual, romanized-Hindi included — the production transcripts in brief §9
show auto-replies arriving in Hindi):

```
AUTOREPLY_RX : thank you for contacting | thanks for contacting | our team will (respond|get back)
             | we have received your message | this is an automated | auto(-| )?reply
             | out of office | outside (our )?business hours | will revert shortly
             | aapki jaankari ke liye | team tak pahuncha | dhanyavaad .* sampark
             | main ek automated assistant

OPTOUT_RX    : stop (messag|send|texting) | unsubscribe | do ?n[o']?t (message|contact)
             | remove me | opt out | band kar(o|do|dijiye) | mat bhej | mujhe mat

HOSTILE_RX   : useless | spam | nonsense | rubbish | waste of (my )?time | bothering me
             | why are you (bothering|messaging) | bakwas | pareshan

COMMIT_RX    : ^(ok|okay|yes|yeah|yup|sure|done|haan|ji|theek hai|thik hai)\b
             | lets? do it | go ahead | please (do|send|proceed) | send it | do it
             | start karo | kar do | chalo | i'?m in | count me in | proceed | confirm

OFFTOPIC_RX  : gst | income tax | itr | loan | legal notice | rent | electricity bill
             | hiring | visa | insurance claim

DEFER_RX     : later | busy | next week | tomorrow | baad me(in)? | abhi nahi | call me
```

Every bank is a frozen list with a unit test per replay scenario. The three canonical
judge messages —
*"Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly."*,
*"Ok lets do it. Whats next?"*, *"Stop messaging me. This is useless spam."* —
are regression fixtures.

## 3.3 Transitions and outputs

| From | Class | Action | Body / field | Rationale content |
|---|---|---|---|---|
| any | `AUTO_REPLY` streak 1 | `send` | one line that flags it to the human and restates the binary ask, **no re-introduction** | "Detected auto-reply; single owner-flag prompt." |
| any | `AUTO_REPLY` streak 2 | `wait` | `wait_seconds: 86400` | "Same auto-reply twice; owner not at phone." |
| any | `AUTO_REPLY` streak ≥3 | `end` | — | "Third consecutive auto-reply, zero engagement signal." |
| any | `OPT_OUT` | `end` | — | "Explicit opt-out; writing suppression `all:<m>:30d`." |
| any | `HOSTILE` (no explicit opt-out) | `send` then CLOSED | one-line apology containing *"won't message again"* + a restart path | "Frustration explicit; one acknowledgment then close." |
| `QUALIFYING`/`ENGAGED` | `COMMIT` | `send` (→ `ACTIONING`) | **execution language only** | "Explicit commitment; switching from qualification to execution." |
| any | `OFF_TOPIC` | `send` | decline in one clause + re-anchor to `thread_anchor` in the next | "Out of scope declined; thread re-anchored." |
| any | `DEFER` | `wait` (1800 / 14400 / 86400 by turn) | — | "Merchant asked for time." |
| any | `INFO_REQUEST` | `send` | answer **only from bound facts**; unknown → say so, offer the adjacent thing we do have | "Answered from context; declined to speculate." |
| any | `UNCLEAR` | `send` (≤ turn 3) else `wait` | acknowledge + restate the concrete deliverable + binary ask | "Ambiguous reply; re-offered the concrete next step." |
| `CLOSED` | anything | `end` | — | "Conversation closed." |

**The auto-reply ladder, and one honest wrinkle.** The official good-path
(api-call-examples, Phase 4 replay) is *send-flag → wait(24h) → end*. The reference
`judge_simulator._auto_reply` is stricter: it prints a pass only for `end`, tolerates
`wait`, and treats anything else as "bot kept talking". Our first-turn flag-send is
therefore *documented-good* but *simulator-imperfect*. I follow the documented good path —
Phase 4 is LLM-scored on conversation flow, not by that function, and that function returns
`True` unconditionally regardless (judge-spec §7.2). It is a one-constant switch
(`AUTOREPLY_FLAG_SEND`) if we decide otherwise.

## 3.4 The intent transition, and why determinism wins outright here

`judge_simulator._intent` checks the reply body against two literal substring lists:

```
qualifying = ["would you", "do you", "can you tell", "what if", "how about"]
actioning  = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
PASS iff  any(actioning) and not any(qualifying)
```

A deterministic ACTIONING template can be **unit-tested against those exact strings** and
guaranteed to pass, forever. An LLM asked to "switch to action mode" writes
*"Great — would you like me to send the draft now?"* with meaningful probability, and that
is an instant FAIL on both halves of the predicate. This is the single cleanest example in
the whole challenge of a place where a template is strictly more reliable than a model, and
it is worth real points in the phase that only the top 10 reach.

Canonical ACTIONING realization (dentists, post-commitment):

> "Done — drafting your patient-ed WhatsApp now, 90 seconds. Sending the GBP post draft
> next. Reply CONFIRM and I'll publish to the 124 high-risk adults on your roster."

Contains `done`, `draft`, `sending`, `next`, `confirm`; contains none of the five
qualifying phrases; carries three traceable facts and a binary CTA. Asserted in CI.

## 3.5 Language lane in replies

The conversation's `language_lane` is fixed at the first outbound but **re-evaluated per
inbound**: if the merchant's reply is ≥30% romanized-Hindi tokens (a frozen function-word
list: `hai, hain, kar, karo, nahi, aap, mera, kya, thik, theek, ji, bhi, se, ko, me`),
the lane upgrades. Downgrade never happens mid-conversation. This answers brief §12 item 4
("merchant might switch from English to Hindi mid-conversation") with a token-ratio test
instead of a model call.

---

# 4. State, versioning, and the Phase-3 adaptation story

## 4.1 The store

```python
ContextStore:
  key      : (scope, context_id)
  value    : Record(version, payload, received_at, prev_payload, deltas[])
  semantics: version <= current  -> {"accepted": false, "reason": "stale_version",
                                     "current_version": v}     # matches the spec exactly
             version >  current  -> atomic swap, prev retained, delta computed
```

Single-writer lock per key; the swap is a pointer assignment, so a concurrent `/v1/tick`
never observes a half-applied context. All state in-process (no restarts during the test,
per the brief), with an append-only JSONL write-ahead log to disk purely for post-mortem —
never read back in the hot path.

`/v1/healthz` reports **real** counts from the store, split by scope, because warmup gates
on `contexts_loaded` reflecting all 255 base contexts and **three consecutive healthz
failures = disqualification (−10)**. `healthz` therefore does no work beyond reading four
integers maintained incrementally, holds no lock, and is served on a path that cannot be
blocked by tick processing.

## 4.2 The delta log

On every version bump, a structured diff:

```python
ContextDelta(
  context_id, scope, from_v, to_v, at,
  added_ids     = {"digest": ["d_2026W17_dci_radiograph_NEW"], "offers": [], ...},
  removed_ids   = {...},
  numeric_moves = {"performance.views": (2410, 2580, +0.0705),
                   "performance.ctr":   (0.021, 0.026, +0.238)},
  salience      = 0.71,
)
```

Facts created from newly-added items inherit `origin_ver = to_v` and
`first_seen_at = now`. This is the **only** thing the NOVELTY move and the ranker's novelty
term key off — no heuristics about "what looks new".

## 4.3 Adaptation: citing a NEW digest item after a version bump

Phase 3 injects 5 new digest items per category, updated performance on 10 merchants, 15
new triggers, and 5 mid-test customer contexts followed by a `recall_due` trigger two
minutes later. It is worth **up to +25** (max +5 per dimension) — the largest single
non-copy block on the board.

The mechanism, end to end:

1. `POST /v1/context {scope:"category", context_id:"dentists", version:2}` arrives.
2. Delta computed: `added_ids.digest = ["d_2026W17_dci_radiograph_NEW"]`.
3. **Fan-out to affected merchants:** all 10 `dentists` merchants are marked
   `adaptation_dirty`. Their FactPacks gain the new item's facts
   (`digest_title_short`, `digest_source`, `digest_deadline = 2026-12-15`, the
   `1.5 → 1.0 mSv` pair) with `origin_ver = 2`, `first_seen_at = now`.
4. **Synthesized adaptation candidates.** We do not wait for the judge to push a matching
   trigger. For each affected merchant not recently contacted, a candidate
   `ctx_update:<merchant>:<digest_id>` is created, family = the digest item's `kind`
   (`compliance` here), urgency derived from the item (`compliance` with a dated deadline
   → 4; `research` → 2; `alert` → 5).
5. **The ranker's novelty term (+2.5)** pushes these candidates to the top of the next
   tick, ahead of stale base triggers.
6. **The digest selector prefers the newest item** whenever a digest-bearing move binds —
   so even a *base* trigger composed after the bump cites the new item.
7. **The NOVELTY move fires**, gated strictly on `first_seen_at > TEST_START`:

   ```
   NOVELTY.r1 = "Just landed on the {source} side —"
   NOVELTY.r2 = "New this week:"
   NOVELTY.r3 = "This dropped after we last spoke —"
   ```

   Never fires for base-dataset items. "New" is a factual claim and it is provenanced like
   any other.
8. **Suppression key includes the digest id** (`compliance:m_001:2026-12` +
   `research:dentists:<digest_id>`), so a new item is cited once, not on every subsequent
   tick.

Resulting body shape for the injected DCI item:

> "Dr. Meera — new this week on the compliance side: DCI has revised the IOPA dose ceiling
> from 1.5 to 1.0 mSv, effective 15 Dec. E-speed film clears the new limit; D-speed
> doesn't, and digital RVG is unaffected. If your setup is D-speed that's an equipment
> decision with about seven months of runway. Want me to draft the SOP line and an audit
> checklist — 10 minutes? — DCI circular 2026-11-04"

Five traceable facts, a citation, a dated deadline, a conditional that shows we read the
summary rather than the headline, one binary ask. Composed deterministically, seconds after
the version bump.

**Performance bumps** work the same way: `numeric_moves` with `|Δ| ≥ 0.15` synthesize a
`perf_move` candidate whose anchor fact is the *delta between versions* — a number that
literally did not exist before the injection and therefore cannot be faked by a stale
composer. Citing "your views moved from 2,410 to 2,580 since we last looked" is the most
legible possible proof of adaptation.

**Mid-test customer + recall_due:** on a customer push we immediately build the customer
FactPack, evaluate the Consent Gate, and derive the language lane. When the recall trigger
lands two minutes later, everything is warm and the action composes in the same tick with
`send_as: "merchant_on_behalf"`, a first-touch `template_name`/`template_params`, and the
customer's own `language_pref` lane.

---

# 5. Where an LLM is warranted — stated honestly

I will not pretend the number is zero everywhere. It is zero in `/v1/tick`. Here is the
full accounting.

## 5.1 Conceded: build-time, not request-time

The entire authored surface — ~300 move realizations across 5 categories, the bilingual
phrase bank, the counter-indication rules, the pattern banks — should be **drafted by an
LLM offline**, then human-reviewed, frozen into source, and unit-tested. This is real LLM
leverage; it simply happens before the test window, where latency is free, failure is
recoverable, and output is inspectable. Anyone who says this architecture "doesn't use an
LLM" has mistaken *when* for *whether*.

## 5.2 Conceded: one bounded call in `/v1/reply`, classification only

The `UNCLEAR` bucket is my genuine coverage hole: a free-text merchant reply that matches
no pattern. Here I concede **one** LLM call, under strict conditions:

```
purpose     : CLASSIFICATION ONLY. Input: the inbound message + the 5-line thread anchor.
              Output: one token from a closed enum
              {COMMIT, INFO_REQUEST, OFF_TOPIC, DEFER, OPT_OUT, HOSTILE, AUTO_REPLY, UNCLEAR}
max_tokens  : 8
temperature : 0
timeout     : 3.5s hard
never       : generates any text that reaches the merchant
fallback    : the deterministic UNCLEAR reply is composed FIRST and held; the LLM call
              can only upgrade the classification, never block the response
circuit     : 2 failures or timeouts in the window -> breaker opens for the remainder;
              all subsequent UNCLEARs take the deterministic path silently
concurrency : 1 (replies are serialized per conversation; at most ~1 in flight)
```

Why this is defensible where hot-path composition is not: the output is a single enum
member, so it is **verifiable** (reject anything outside the enum), **bounded** (8 tokens,
sub-second), **rare** (only the fallthrough bucket), **non-generative** (a wrong label
routes us to a different good template; a wrong *generation* puts a hallucinated number in
front of a judge), and **pre-hedged** (the deterministic answer already exists before the
call is made, so a timeout costs nothing but the 3.5s, well inside 30s).

## 5.3 Conceded: an offline critic in the dev loop

An LLM critic that scores our own generated corpus (200+ bodies across the family ×
category × thin/rich matrix) against the rubric, producing an authoring backlog. Runs in
CI, never in the live service, disabled at submission.

## 5.4 Refused

- LLM composition of any `body` returned by `/v1/tick`.
- LLM composition of any `body` returned by `/v1/reply`.
- LLM-generated `rationale` (it must be serialized from the binding trace, or the
  rationale/output-match check is a coin flip).
- LLM selection of the trigger to fire (a scored ranker is inspectable and tunable; a model
  is neither).

---

# 6. My three biggest weaknesses

Stated plainly. No spin.

## 6.1 There is a prose ceiling, and I do not know exactly where it is

The engine's best message is as good as the best sentence I authored for that
(category, family, move) cell. A frontier model occasionally produces a turn of phrase I
would not have written — a sharper metaphor, a better-judged aside — and across 45 sends
some fraction of those land as genuinely more compelling. My distribution is tighter: a
higher floor and a lower ceiling. If the judge's `engagement_compulsion` scoring rewards
the tail, I lose the tail. There is also a real **plagiarism-similarity exposure**: my
grammar was reverse-engineered from the ten case studies, and the closing note in
case-studies.md says near-duplicates of case-study body text are penalized.

**Mitigation.** (a) A hard n-gram guard: any candidate body sharing a 5-gram with any of
the ten case-study bodies is rejected and re-composed — the case-study corpus ships as a
blocklist. (b) Authored realizations are deliberately written *away* from case-study
phrasing (no "Quick heads-up", no "Worth a look", no "— no commitment, no auto-charge").
(c) The batch de-similarity constraint (trigram Jaccard < 0.45) applies across the run, not
just the tick. (d) I accept the ceiling consciously: the judge prompt scores one body in
isolation against five concrete criteria, four of which are mechanical. I am trading a thin
slice of the top decile for the entire −20 penalty block and a guaranteed floor on the
other four dimensions.

## 6.2 Unmodeled inputs degrade to silence, and silence is only free in one endpoint

Anything I did not anticipate — a trigger kind outside the 26, a Phase-3 payload with a new
shape, a merchant reply my cascade misreads — has no handler. In `/v1/tick` that costs me
an opportunity but nothing else (silence is rewarded). In `/v1/reply` it is visible: a
canned line that misses the merchant's actual point is worse than an LLM's fluent
improvisation, and Phase 4 scores conversation flow specifically. Related: my
counter-indication table only knows the contrarian relationships present in the *base*
digest; a Phase-3 item introducing a new one gets cited faithfully but not *argued from*.

**Mitigation.** (a) A **kind-agnostic backstop family**: every unrecognized trigger routes
to a composer that needs only merchant + category (the metric × peer × digest join from
§1.4), so an unknown kind still produces a dense, cited, correctly-voiced message whenever
the Evidence Floor clears — the engine never fails *because* it doesn't recognize a kind.
(b) The `UNCLEAR` reply template is built to be genuinely good, not a placeholder:
acknowledge, restate the one concrete deliverable already on the table, ask a binary
question. (c) The §5.2 classifier concession exists precisely to shrink this hole.
(d) The generic seasonal/peer counter-indication (§2.6) gives *some* contrarian capability
over items I have never seen.

## 6.3 The quality is bought with authoring hours, and that bill comes due before submission

This architecture front-loads all its cost. Roughly 250–350 authored strings, 25
counter-indication rules, 6 pattern banks, a bilingual phrase bank, and a coverage matrix —
all before the service is worth deploying. An LLM-first bot is *demonstrably working* in an
afternoon and improves smoothly with prompt iteration. Mine has a long flat stretch where
it produces nothing good, and if I run out of time the categories I authored last will be
visibly thinner — and I cannot paper over that at runtime. The failure mode is also
asymmetric: a half-authored deterministic engine is worse than a half-prompted LLM bot.

**Mitigation.** (a) **Tiered shipping.** Tier 0 is the backstop family alone (one composer,
five category voice packs) — it is complete and scoring on day one, and every later tier is
purely additive. A missed tier degrades to Tier 0, never to nothing. (b) **Prioritize by
trigger frequency, not category** — all five categories carry exactly 10 merchants, so
none can be deprioritized; instead author the 10 families that cover ~90% of the trigger
set (`perf_dip`, `perf_spike`, `research_digest`, `milestone_reached`, `dormant_with_vera`,
`review_theme_emerged`, `competitor_opened`, `festival_upcoming`, `renewal_due`,
`curious_ask_due`) before the ten seed-only one-offs. (c) **LLM-assisted authoring with
human review** — this is the §5.1 concession doing real work, and it compresses the
authoring bill by most of an order of magnitude. (d) **A CI coverage matrix** that emits
200+ sample bodies across family × category × thin/rich and runs the local judge simulator
over them, so thin cells are visible as numbers rather than discovered at grading.

---

# 7. Expected attacks and rebuttals

## 7.1 From the LLM-first architect

### Attack A1 — "Your copy will read as machine-assembled. You cap at 7–8 on engagement compulsion; I hit 10."

**Rebuttal.** Three parts.

*The scorer cannot see what you are describing.* judge-spec §1 shows the full user prompt:
one body, one trigger, one merchant, one category, per call. There is no cross-message
window. "Templated across twenty sends" is a critique available to a human reading the
transcript bundle and structurally unavailable to the scorer that assigns the 0–10s.

*The evidence in the scored set points the other way.* All ten cases share one grammar. The
lowest score in the set, 44/50, is Case 4 — and the judge's stated reason is not
"formulaic", it is *"could be sharper with a guess"* and *"could reference recent service
mix"*. It lost points for **fact poverty**, the exact failure mode a FactPack with an
Evidence Floor cannot commit. Case 7 lost its compulsion point for an **unquantified
action clause** ("save it for Sept-Oct") — again mechanical, again guarded.

*Compulsion is an enumerable checklist, and I pass all of it every time.* Brief §10 lists
eight levers. My worst message carries five (specificity, social proof via peer stat,
reciprocity via "I'll draft it", effort cap, single binary CTA). Your median message
carries two or three, because nothing in your prompt *forces* the others. You will beat me
on some tail of messages. I will beat you on the mean, and the reference aggregation is a
**mean**.

### Attack A2 — "Case 5 is the whole game and you can't hard-code judgment. You'll fire the literal trigger and lose the single highest-signal differentiator."

**Rebuttal.** Case 5's judgment is a lookup, and I can show you the row. The −12% is
verbatim in `restaurants.digest.d_2026W17_ipl_window`, together with the +18% weeknight
figure and the `actionable` field that literally says *"Push match-night combos on
Tue/Wed/Thu match dates only."* The bot's "contrarian insight" is: read the trigger date,
test the weekday, retrieve the digest item, follow its `actionable`. That is a three-clause
join. A rule engine executes it on every Saturday match, forever. Your model executes it
when the digest item survives into attention and the weekday reasoning doesn't slip —
and when it slips, it slips *toward quoting the −12% on a Tuesday*, which is a fabrication
against the merchant's own category data and the named lowest-scoring behavior.

I will go further: **I can enumerate every contrarian case this dataset supports.** There
are 25 digest items, ~20 seasonal beats, ~20 trend signals, and 5 peer-stat blocks. I have
read all of them and written rules over them. You are sampling from the same finite set
probabilistically and calling the variance "judgment". My honest concession is §6.2 — I
cannot argue against a *Phase-3* item I have never seen. But neither reliably can you, and
I at least cite it correctly.

## 7.2 From the ops / score-maximizing architect

### Attack B1 — "Restraint is you leaving points on the floor. The cap is 20 actions per tick over 12 ticks. Your evidence floor and cadence caps throw away most of the board."

**Rebuttal.** Four counters, one concession.

*The aggregation is an average, not a sum.* `_final_summary` computes per-dimension means
across all scored messages (judge-spec §2, integer division across n). A marginal
placeholder-trigger send scoring 30/50 does not add 30 points; it **drags the mean down**.
Under an average, restraint is not a moral position, it is arithmetic.

*Volume is an operational-penalty generator.* Every action spawns a judge sub-LLM merchant
reply and up to 5 `/v1/reply` turns (testing-brief §4 Phase 2). Twenty actions per tick is
twenty live conversations whose reply turns arrive concurrently, each with its own 30s
budget and each contributing −1 on timeout. The action count is not the cost; the
**conversation fan-out** is.

*Volume is also a repetition generator.* −2 per verbatim repeat in a conversation, and the
more you send the same merchant, the harder the anti-repetition guard has to work.

*The brief prices this directly.* "Restraint is rewarded; spam is penalized" appears in the
FAQ, the API examples, and the design doctrine. The empty-actions response is not tolerated,
it is **praised**.

*Concession:* if the real grader sums rather than averages, my cadence caps are three
integers (`TICK_BUDGET`, `PER_MERCHANT_WINDOW_CAP`, `SEND_THRESHOLD`) and I will raise
them without touching a line of the composer — which is itself an argument for this
architecture, since the policy is a config surface rather than a prompt rewrite. I will
**not** relax the Evidence Floor, because sending an ungrounded message is the one move
that risks the fabrication read, and that is scored as a floor violation, not a
missed opportunity.

### Attack B2 — "Your differentiation is Phases 3 and 4, which are behavioral. You've poured your budget into a copy engine an LLM gives you for free, and under-built the parts that actually separate the field."

**Rebuttal.** I agree with the premise entirely, and it is the strongest argument *for*
this architecture rather than against it.

Roughly a third of the achievable score — the +25 adaptation bonus, the +30 replay, the
−20 ops block — is not message copy. A determinism-first design is precisely the one that
can afford to spend everything there: my `/v1/tick` consumes ~4ms of a 30,000ms budget, so
**the entire latency budget and the entire operational-risk surface stay free** for the
delta log, the adaptation fan-out, the reply state machine, and healthz reliability. An
LLM-first bot spends both its latency and its failure modes on copy — the part the judge
scores most generously and most subjectively.

*Concession, concretely:* I commit to a build order that makes this real, and I will be
judged on it —

1. **Ops floor**: five endpoints, exact schemas, idempotent versioned store, real healthz
   counts, action-schema validator, URL guard, anti-repetition guard. (Converts −20 to ~0.)
2. **Reply FSM**: classifier cascade + all three replay scenarios as regression fixtures.
   (Targets +30.)
3. **Delta log + adaptation fan-out + NOVELTY move.** (Targets +25.)
4. **Decision layer**: ranker, gates, suppression taxonomy, counter-indication table.
5. **Composition depth**: tiered authoring, Tier 0 backstop first.

The composition engine is deliberately last and deliberately tiered, because Tier 0 already
clears the Evidence Floor and the voice packs. If I run out of time, the thing that ships
thin is the thing the judge scores most forgivingly — and the thing that ships complete is
the block worth −20 to +55.

---

## Appendix — response-schema hardening (the cheapest points on the board)

Every returned action passes a validator before it leaves the process. api-call-examples
F.2 prices a missing required field at **action scored 0, −2 penalty**.

```
required: conversation_id, merchant_id, customer_id (may be null), send_as, trigger_id,
          body (non-empty), cta, suppression_key, rationale
first-touch also: template_name, template_params[]
assert send_as == "merchant_on_behalf" iff customer_id is not None
assert cta ∈ {binary_yes_no, binary_confirm_cancel, multi_choice_slot, open_ended, none}
assert no URL / scheme / bare domain in body
assert body hash unseen within conversation_id
assert ≥3 numeric tokens in body, each ∈ FactPack.rendered_set   # provenance closure
assert 0 taboo-phrase hits
assert ≥1 allowed-vocab term (merchant-facing)
assert emoji count within policy
assert no 5-gram shared with the case-study corpus
on any failure: recompose at variant idx+1 (≤4 tries), else DROP the action entirely
```

Dropping an action costs one opportunity. Returning a malformed one costs −2 and a zero.
The asymmetry is the whole design in miniature: **this architecture is built to never be
wrong, and is willing to be silent to keep that promise.**

---
---

# CROSS-EXAMINATION RESPONSE

I have read `arch-L-llm-first.md` and `arch-S-score-max.md` in full, and re-verified F1, F2
and F3 against `judge_simulator.py` myself rather than taking them on report. Two of the
three findings damage my document materially. I am going to say so before I say anything
else, because the parts of my original thesis that survive are stronger without the parts
that don't.

**Summary of my position after cross-examination:** my composition engine gets better under
scrutiny; my *architecture* does not. ARCH-L's speculative topology is simply correct and I
was wrong to build the request path the way I did. The synthesis I would ship is L's
topology with my composer as its floor and S's policy layer on top — and I will argue that
none of the three documents as written is the right answer.

---

## 1. WHAT I CONCEDE

### C1 — F1 is real, it lands on my load-bearing claim, and my thin-merchant example fails it

Verified at `judge_simulator.py:503-531`. The per-action scoring prompt passes exactly:
category `slug`, `voice.tone`, `vocab_taboo[:5]`; merchant `identity.{name, owner_first_name,
locality, languages}`, `performance.{views, calls, ctr}`, `signals[]`, offers filtered to
`status == "active"`; trigger `kind`/`payload`/`urgency`; `customer.identity`. It excludes
`digest`, `peer_stats`, `seasonal_beats`, `trend_signals`, `customer_aggregate`,
`conversation_history`, `review_themes`, `subscription`, `delta_7d`, `directions`, `leads`,
`window_days`, `city`, `established_year`, `verified`, and every non-active offer.

Now score my own §1.10 thin-merchant body against that window:

| Fact in my body | Source | Visible to the reference judge? |
|---|---|---|
| views down **20%** w/w | `performance.delta_7d.views_pct` | **NO** |
| CTR **4.6%** | `performance.ctr` | YES |
| **3.0%** peer median | `category.peer_stats.avg_ctr` | **NO** |
| calls up **16%** | `performance.delta_7d.calls_pct` | **NO** |
| Pro plan lapsed **28 days** | `subscription.days_since_expiry` | **NO** |
| **5-minute** effort cap | rhetorical | n/a |
| aligner searches **+62% YoY** | `category.trend_signals` | **NO** |
| **28-45** band | `category.trend_signals` | **NO** |

**One of seven factual claims is checkable by the reference judge.** Six read as
potentially-fabricated to a scorer instructed "Be STRICT" with an explicit −2 for
"fabricating data not in context". I built an Evidence Floor to defeat exactly that failure
mode and then filled it with facts the grader cannot see. That is a serious error and ARCH-S
caught it in his §3.2 while I did not. I concede the point to him without qualification.

My claim that "the worst merchant supplies 50+ provenance-backed facts" is still *true* —
but the correct number for the **reference-judge-visible** set is much smaller, and I should
have stated both. For a generated thin merchant the Tier-A numeric set is exactly
**`views`, `calls`, `ctr`** — three numbers — plus proper nouns (`name`, `owner_first_name`,
`locality`), an empty `signals[]`, an empty active-offer list, and a placeholder trigger
payload. That is the honest floor.

### C1a — What I do NOT concede about F1, and the reconciliation

The counter-consideration is strong and I want it on the record precisely, because it is the
reason the answer is *tiering* rather than *abandonment*:

- challenge-brief §16 states the real judge session receives **this brief, the full base
  dataset, the injections, and the bot artifacts.** A judge holding `dataset/categories/*.json`
  can verify a peer stat or a digest citation directly.
- **Dispositive evidence from the pack itself:** Case 1 scored **10/10 on merchant fit**
  with the judge's verbatim reason *"'your high-risk adult patients' derived from her
  customer_aggregate"*. `customer_aggregate` is in F1's excluded set. The judging that
  produced the scored examples therefore **saw a wider window than `judge_simulator.py`
  passes.** Case 1 also scored 10/10 specificity on `trial_n: 2100` and `"JIDA Oct 2026,
  p.14"` — both from `category.digest`, also excluded. The challenge authors' own
  gold-standard 50/50 message is built almost entirely from Tier-B facts.
- judge-spec's own framing: the simulator "is not necessarily the exact grading harness."

So F1 describes a *narrower* harness than the one that produced the exemplars. The correct
response is not to abandon Tier-B facts — that would mean abandoning the shape of every
50/50 case in the pack — but to make Tier-B facts **legible as sourced** and never let them
carry the message alone.

### C1b — The concrete design changes F1 forces (three of them)

**(i) The Evidence Floor becomes two-part.** I adopt ARCH-S's tiering wholesale:

```
EvidenceFloor:
   tier_a_numeric ≥ 2        # from {views, calls, ctr} or a derivation over them
   total_provenanced ≥ 3
   every Tier-B fact carries an in-body attribution token
```

**(ii) `EVIDENCE` leads Tier-A; `PEER_FRAME` and `CITE` carry mandatory attribution.**
In my original grammar `PEER_FRAME` was elidable and `peer_scope_label` was optional. Both
change. A peer stat must always render as *"against the 3.0% median for metro solo
practices"* — naming `peer_stats.scope` is what converts an unverifiable number into an
attributed one. This is exactly the mechanism that earned Case 1 its 10/10 specificity:
`"JIDA Oct 2026 p.14"` is not checkable in the judge's window either, but it is *citable*,
and the judge scored the citation, not the lookup. **Attribution substitutes for
visibility.** My `CITE` move already did this for digest items; I am extending the same
discipline to every Tier-B family.

**(iii) Derived Tier-A facts are a richer seam than I used, with one trap.** `views`,
`calls` and `ctr` are all visible, so any derivation over them is *fully* checkable —
"55 calls off 4,792 views, about one call per 87 views" is arithmetic the judge can redo
from its own prompt. But the trap is sharp: **`ctr` is not `calls/views`.** For m_011,
`calls/views = 1.15%` while `ctr = 4.6%`. A composer that asserts "4,792 views and 55 calls
puts your CTR at 4.6%" hands the judge a computation that fails, which reads as fabrication
*because the judge can check it*. Visible operands cut both ways. My `Slot` resolver gets a
`semantic_relation` guard: a derivation may only be emitted when the relation between its
operands is real, and a CI test asserts every derivation against the 50 merchant records.

### C1c — The corrected thin-merchant example

Replacing §1.10's body. Same merchant, same trigger, same engine, Tier-A-first:

> Dr. Sameer — 4,792 views and 55 calls last month, roughly one call for every 87 views,
> with your listing CTR at 4.6% against the 3.0% median for metro solo practices. Discovery
> is converting for you; reach is the constraint, not the listing. Separately worth
> flagging: your Pro plan lapsed 28 days ago. Want me to put together a 5-minute restore
> plan plus a short aligner-demand note for Indiranagar? Ek line bas — YES.

| Fact | Tier | Judge-visible |
|---|---|---|
| 4,792 views | A | yes |
| 55 calls | A | yes |
| ~1 call per 87 views | A (derived, both operands visible, relation valid) | yes |
| 4.6% CTR | A | yes |
| 3.0% median **for metro solo practices** | B, attributed via `peer_stats.scope` | no, but sourced |
| 28 days lapsed | B, merchant's own account | no |
| 5-minute cap | rhetorical | n/a |

Four Tier-A numerics, one attributed Tier-B, one account fact, one effort cap. The
counter-indication verdict (`R-DEN-03`, reach-not-conversion) survives intact and is now
argued from visible numbers rather than invisible deltas — which makes it *more* legible as
judgment, not less. This is a strictly better message than the one I originally wrote, and I
would not have written it without F1.

### C2 — F2 holds. My pillars 2 and 3 lose most of their force, and I say so plainly.

Verified. `_full` (`judge_simulator.py:807-810`) pushes **all 50 merchants and all 100
triggers** before the first tick, then ticks in batches of 5 — an enormous speculation
window. testing-brief §4 Phase 2 orders each tick as "1. Judge POSTs any new/updated
contexts… 2. Judge calls POST /v1/tick". The push genuinely precedes the listing, by
construction, at every level of the harness.

So **yes — my remaining objection to ARCH-L's topology reduces to (a) correlated provider
failure and (b) unprovable byte-identity.** I will not pretend otherwise. And I will further
concede that (b) is worth very little: my own document already noted the reference harness
contains no cross-call determinism check, and ARCH-L's §2.5 is correct that no scoring
mechanism in either brief rewards determinism directly. Determinism is a contract-compliance
property and a debugging property. It is not a scoring property. I over-sold it.

I hold two residual objections, both narrower than what I originally wrote:

**(c) The cache-miss path is asymmetric in a way L's own code shows.** His tick handler
reads `if c is None: floor.compose() if trg.urgency >= 4 else continue`. The urgency
distribution is 1→31, 2→32, 3→26, 4→10, 5→1. **90% of triggers are urgency ≤ 3 and are
silently dropped on a cold cache**, not floored. In `_phase2_short` (three triggers pushed,
tick immediately) and on any tightly-injected trigger, that is a systematic skip of the
first opportunity. It is bounded — `available_triggers` persists across ticks and his budget
is 3-5/tick anyway, so the trigger fires one tick later at a cost of ~0 — but it means the
buffer-depth argument is doing real work and should be measured, not assumed (see T3).

**(d) `/v1/reply` is the one path that cannot be speculated, and it carries the most judged
volume.** ARCH-S's A3 is right and I under-weighted it badly: every emitted action spawns a
judge-driven merchant-reply loop of up to 5 turns, so the large majority of judged
interactions in Phase 2 are reply turns, not first sends. ARCH-L puts an inline 8s LLM call
in exactly that path. Combined with ARCH-S's A2 — the reference client's reply timeout is
**15s** (`judge_simulator.py:430`) and api-call-examples publishes **10s** — an 8s internal
deadline under burst concurrency is the one place L's "structurally identical timeout
exposure" claim actually fails. I credit L for making the policy decision (end/wait) before
any model call, which removes the three replay scenarios from the LLM path entirely. The
exposure is on engaged-conversation `send` turns only. It is real but it is not fatal.

### C3 — F3 is correct, none of us caught it, and the moderator's fix is right

Verified at `judge_simulator.py:691-699`:

```python
for i in range(1, 5):
    data, err, _ = self.client.reply(f"conv_auto_{i}", mid, auto_msg, i + 1)
```

Four calls, four **distinct** `conversation_id`s (`conv_auto_1..4`), the same `merchant_id`,
the same canned text, `turn_number` 2,3,4,5. My §3.1 FSM carries `autoreply_streak` on the
**conversation** object. Under this scenario every conversation is brand new, every streak
is 1, my ladder emits the flag-send four times, and the harness prints *"Bot never ended
after 4 auto-replies."* My design fails this scenario outright. Conceded.

**I confirm the merchant-global signature approach**, with three refinements I would want in
the implementation:

1. **Key on `(merchant_id, signature)` where `signature = sha1(normalize(message))`**, and
   normalize aggressively: lowercase, strip punctuation/emoji/whitespace, strip a leading
   business-name span (auto-replies embed the merchant's own name, so
   `"Thank you for contacting Dr. Meera's Dental Clinic!"` and
   `"Thank you for contacting us!"` must collapse to the same signature). Without the
   name-strip, the live harness's per-merchant canned text and the simulator's generic one
   are different signatures.
2. **Take the max of both counters**, never replace one with the other:
   `streak = max(conv.autoreply_streak, global_sig_count[(merchant_id, sig)])`.
   Per-conversation still matters for the live replay where the four repeats may well share
   one `conversation_id`; merchant-global catches the simulator's fan-out. Neither subsumes
   the other, so union them.
3. **Add the phantom-conversation tell as a third, independent detector.** A `/v1/reply`
   arriving with a `conversation_id` we have never opened *and* `turn_number ≥ 2` means
   there is no outbound of ours to reply to. That is exactly the shape of `conv_auto_2..4`.
   It should not on its own force `end`, but it is strong corroborating evidence and it also
   prevents the more basic bug of crashing or treating a synthetic replay as a cold start.

With the union counter my existing ladder lands correctly: call 1 → `send` (flag, harness
warns), call 2 → `wait 86400` (harness prints success), call 3 → `end` (harness prints
success and returns immediately). I keep the flag-send at strike 1 because it is the
documented good path in api-call-examples and Phase 4 is LLM-scored on flow, not by this
function — but F3 means the ladder now actually *reaches* `end`, which it previously never
did. That is the difference between passing and failing the scenario, and I would not have
found it.

### C4 — My "one body at a time" claim was too broad. Narrowing it.

This is the claim ARCH-L's entire quality argument depends on being wrong, so I will state
the evidence precisely and then state its limits precisely.

**The evidence, verified.** `LLMScorer.score()` at `judge_simulator.py:499-531` builds the
prompt per-action. `_score_and_display` is invoked once per action
(`judge_simulator.py:676-677, 828-829`). The prompt interpolates one `body`, one `cta`, one
`send_as`, and the four contexts. **No prior bodies, no conversation history, no sibling
actions are passed.** For the 5-dimension rubric scorer as implemented, cross-message
sameness is not in the input.

**The limits, which I did not state and should have — four of them.**

1. This is the reference harness, explicitly not necessarily the grader.
2. **Phase 4 is scored "on conversation flow"** across 5 turns. That is a multi-message
   window by definition, and templated sameness is fully observable there.
3. The **−2 anti-repetition penalty** proves the harness tracks bodies across turns within a
   conversation. A mechanism that compares bodies exists.
4. **The point I missed entirely, and which ARCH-S makes in his §4.6:** the judge invokes a
   sub-LLM *playing the merchant*, which reads my message and replies in character. A
   merchant who has received four structurally identical messages replies with
   disengagement or irritation — and *that reply is what I am then scored on*. The
   merchant-simulator is a de facto cross-message observer even though the rubric scorer is
   not. This is a real transmission channel from "reads templated" to lost points and my
   original framing had no answer to it.

**Corrected claim:** templated sameness is invisible to the per-action rubric scorer and
visible to (i) the Phase 4 flow scorer, (ii) the merchant-playing sub-LLM whose replies I am
scored on, and (iii) any human qualitative report (testing-brief §13 promises a
`final_report.md` with "judge's qualitative feedback"). My batch de-similarity constraint and
400-surface variation space were designed for a threat I claimed didn't exist; they turn out
to be load-bearing after all. I'd now raise the de-similarity budget to cover
**merchant-scoped history**, matching ARCH-S's 5-gram guard, not just within-tick pairs.

### C5 — I used 30s as the binding deadline throughout. That was sloppy.

ARCH-S's A2 is correct and I adopt it. `BotClient` sets tick **15s**, reply **15s**, context
**10s**, healthz **5s** (`judge_simulator.py:413-430`), and api-call-examples publishes
tick 10s / reply 10s / healthz 2s. Two independent documents state something tighter than
testing-brief §5's 30s. Designing to 8s is never wrong; designing to 30s can be fatal. My
document's repeated "30s budget" framing overstated my own headroom advantage — though it
also means my ~4ms tick is *more* advantaged relative to an inline composer, not less.

### C6 — ARCH-L's containment argument is structurally valid

If his floor genuinely is my output, then on quality he weakly dominates and the debate
reduces to correlated-failure probability. I concede the *form* of the argument is sound.
My answer to its *content* is in §2.3 below.

---

## 2. WHAT I STILL HOLD

### H1 — L's floor is not my output, and his own document says so

He specifies `TemplateFloor` as *"roughly 20 hand-written shapes keyed by
(trigger_kind_family, scope, has_customer)"* and self-scores it *"30-35/50 — which is
precisely why I refuse to make it the primary path."*

That is not my architecture. It is a 20-shape stub. Mine is ~250-350 authored realizations
across 5 categories × 7 moves, a 12-row counter-indication table with basis references, a
bilingual overlay with four safety rules, Tier-A/Tier-B fact discipline, a
`semantic_relation` guard on derivations, phrase-level taboo compilation, a 400-surface
variation space, and batch de-similarity. **He has assumed my ceiling equals his floor by
building the cheap version of it and then measuring that.** The containment claim is only
true if he pays my authoring bill — and his own build order (TemplateFloor at step 2 of 7,
ahead of speculation, the reply path, Phase 3, the angle bank, the recipes, and the
determinism harness) shows he will not. If he did, he would inherit my W3 schedule risk,
which is the precise thing his architecture is meant to avoid.

This is a falsifiable disagreement, not a rhetorical one. See T1.

### H2 — His floor is sampled adversarially, not uniformly

`TemplateFloor` fires on exactly three conditions: two failed repair passes, a cache miss on
an urgency≥4 trigger, or provider outage. Conditions 1 and 3 are *correlated with stress*,
and condition 2 is the tightest-timing case. His floor is therefore not a uniformly-drawn
32/50 — it is 32/50 **conditioned on the inputs that already defeated a frontier model twice
and on the moments when the system is least healthy.** "When cold I degrade to your output"
silently assumes floor quality is input-independent. It is not. My engine's output
distribution is unconditioned; his floor's is conditioned on the hardest tail.

### H3 — The intent-transition argument survives completely

`judge_simulator.py:741-747`: `if any(actioning) and not any(qualifying) → PASS`, against
two literal substring lists. A deterministic ACTION-MODE template can be CI-asserted against
those exact fourteen strings and guaranteed to pass, permanently. ARCH-L's answer (§5.2) is
to add `V_ACTION`, a validator that rejects any candidate containing a qualifying phrase,
repairs once, and **falls to a deterministic action-mode template if it fails twice.** That
is my mechanism, adopted. He is right that the LLM supplies the *artifact* (Case 6's tiered
price list is where the qualitative points are) and I concede that a template cannot emit
the draft. But the *guarantee* is mine and he uses it. Neither of us should pretend the
keyword grader is beaten by prose.

### H4 — Rationale must be assembled, not generated

All three documents independently converged on this (my §1.9, S's §3.1, L's §1.6 note). I
hold it as the strongest form: the rationale is serialized from the binding record, so
rationale/body mismatch is structurally impossible rather than validated-after-the-fact.
L generates it in the same call as the body and then validates consistency (V9) — that is
weaker, because a consistency check can only catch contradictions it can parse, whereas
assembly cannot produce one.

### H5 — The Evidence Floor survives F1, re-typed

Conceded in C1b that its threshold must change. I hold the gate itself. `competitor_opened`
with a placeholder payload has no competitor name, distance, offer, or date anywhere in any
pushed context, and F1 makes this *worse*, not better: the judge sees the literal string
`{"placeholder": true, "metric_or_topic": "competitor_opened"}` in its prompt and can tell
there was nothing to work from. Silence is correct. Notably ARCH-L's own derivation recipe
for that kind says *"NEVER invent one… If that is also thin, set send=false"* and ARCH-S's
gate is `F_A ≥ 2 ∧ F_total ≥ 3`. **All three architectures independently arrived at
abstention on ungrounded triggers.** That is the most robust conclusion in this entire
debate and it should be treated as settled.

### H6 — Where I actually differ from ARCH-S: less than either of us implied, and in one specific place

Honest accounting. We agree on: restraint and its derivation from reply throughput;
suppression taxonomy (near-identical `topic:scope:period`); fail-closed single-egress
validation; never emitting URLs; assembled rationale; structural-diff adaptation with a hard
citation post-condition; the consent gate on the walk-in customer; `send_as` correctness;
healthz isolation; single-replica state discipline. He is *better* than me on A2 (deadlines),
A3 (reply volume), and fact tiering, and I have adopted all three above.

The one place we genuinely diverge is **latency posture, and here I think S has the weakest
position of the three of us.** His §4.3 composes "up to 4 actions **in parallel**, each with
its own 3.5s per-call deadline" *inside* `/v1/tick`. That is an inline LLM call on a
judge-facing path — the exact thing ARCH-L moved off the path and I eliminated. S neither
eliminates the call nor speculates it. Under his own A2 (tick budget 10s, not 30s), four
parallel frontier calls with a 3.5s deadline plus verification plus rationale assembly
inside a 6s internal budget is the tightest timing in any of the three documents, and it is
paid for with a guillotine that drops work. He is right about almost everything except the
one thing his own opponents both solved.

Our second difference is definitional rather than substantive: he prices "composer copy
artistry" at 0.6 pts/hr and caps it at ~6 hours. That estimate is correct for *prompt*
artistry. It does not price *authored realizations*, because in his architecture the copy is
produced by a model and the hours buy prompt iteration, whereas in mine the hours **are** the
product. We are not disagreeing about value per hour; we are disagreeing about what an hour
buys. His Tier-3 bank (80 templates × 3 paraphrases = 240 surfaces) is a thinner version of
my engine, and his own W1 and D1 rebuttal concede it produces "visible sameness" that his own
5-gram guard would reject. That is the cost of pricing the work at 0.6 pts/hr.

---

## 3. THE SYNTHESIS I WOULD ACCEPT

**Not my architecture. I would ship ARCH-L's topology with my composer as its floor and
ARCH-S's policy layer on top.** Concretely:

**Layer 0 — Request path (ARCH-L, §3.1).** No judge-facing handler ever awaits an LLM.
`/v1/context` acks and enqueues; `/v1/tick` is a cache read plus a ranked sort;
`/v1/healthz` touches four atomic integers on a lock-free route. This is strictly better
than what I proposed and strictly better than S's inline-parallel compose. I was wrong here
and F2 is why.

**Layer 1 — Deterministic composer as the *primary* speculative path (mine, in full).**
At speculation time the deterministic engine composes **first and always**, synchronously,
in ~4ms — the full engine, not a 20-shape stub. Every `CompositionKey` therefore has a
valid, verified, on-voice, Tier-A-anchored body the instant the trigger is stored. Provider
outage becomes *invisible* rather than *degrading*, and the cache-miss-drop asymmetry in
H(c) disappears: there is never a miss.

**Layer 2 — LLM as a challenger that must win on measurable grounds (ARCH-L's composer,
gated).** The T2 composition runs speculatively in parallel and **replaces** the
deterministic body only if it passes every validator *and* a deterministic comparator:

```
accept_llm_body  ⟺  all validators pass
                  ∧ tier_a_fact_count ≥ deterministic.tier_a_fact_count
                  ∧ total_fact_count  ≥ deterministic.total_fact_count
                  ∧ zero orphan numerals
                  ∧ judgment_move.type ∈ {reframe, contrarian_override, derive_from_thin_payload}
                  ∧ 5-gram Jaccard vs case-study corpus < 0.18
                  ∧ 5-gram Jaccard vs merchant history < 0.55
```

This is the only formulation under which "strictly upside with a bounded downside" is
actually true, because the comparison is against a real floor rather than against nothing.
It also resolves my H1/H2 objection structurally: the floor is no longer sampled
adversarially, because it is always computed.

**Layer 3 — Policy (ARCH-S, nearly verbatim).** His Θ/`B_t` restraint derived from reply
throughput rather than taste; his zero-defect `emit_action()` egress; his `state.jsonl`
crash-safety and single-replica discipline; his A2 deadline ladder (8s, not 30s); his fact
tiering; his adaptation freshness queue with lexicographic `(has_uncited_fresh_fact, urgency,
p̂)` ranking.

**Layer 4 — Reply (mine, corrected by F3).** Policy decided before any model call; the FSM
with the union auto-reply counter and the phantom-conversation detector; a deterministic
body pre-staged before any LLM phrasing attempt, so an 8s deadline costs nothing.

**Determinism** then comes from L's content-addressed cache *plus* my deterministic body as
the tiebreak: within-run replay is byte-identical by construction, and a cold-key recompute
that diverges falls back to a body that never diverges.

Why I would accept this over my own document: F2 showed my latency argument was mostly
recovering a cost I had imposed on myself, and C4 showed my "unobservable sameness" argument
was too broad. What survives of my position is that the deterministic composer is worth far
more than either opponent prices it — and the synthesis lets me prove that claim empirically
rather than win it rhetorically, because Layer 2's comparator logs exactly how often the LLM
actually beats the floor.

---

## 4. WHERE A TEST, NOT AN ARGUMENT, SHOULD DECIDE

Five. The first two are decisive; I would run them before writing another line of design.

### T1 — The composer bake-off (settles the entire L-vs-D axis)

Both of us are asserting numbers. L claims templates score 32/50 and his composer 44/50.
I claim my engine is well above his 20-shape stub. **Neither of us has measured anything.**

*Protocol.* Build both composers over one shared `FactLedger`. Generate bodies for the 30
canonical `test_pairs.json` entries plus 30 stratified thin-merchant pairs (placeholder
payload, empty offers/signals/history). Score with `full_evaluation` against a real judge
LLM. **Three independent scoring runs** to separate judge variance from composer difference,
reporting per-dimension means with standard errors.

*Pre-registered decision rule*, so neither side can move the goalposts after seeing results:
- gap ≤ 3 points → the LLM's ceiling does not justify its correlated-failure risk; ship the
  deterministic composer as primary with no challenger.
- 3 < gap ≤ 6 → ship the synthesis in §3; the comparator earns its complexity.
- gap > 6 → my architecture loses on the merits and I say so. L's containment argument is
  vindicated and the deterministic engine is demoted to a genuine floor.

This is the test I most want run, including if it goes against me.

### T2 — The fact-tiering delta (settles F1)

Score the **same** body twice: once through the reference narrow prompt
(`judge_simulator.py:503-531` verbatim), once through a prompt additionally carrying
`digest`, `peer_stats`, `customer_aggregate`, `seasonal_beats`, `delta_7d`. Use ~40 bodies
spanning Tier-A-heavy and Tier-B-heavy compositions.

The delta is the true cost of a Tier-B fact. If it is large, tiering is mandatory and my
original grammar was badly wrong. If it is near zero — which Case 1's 10/10 on a
`customer_aggregate`-derived claim suggests — then attributed Tier-B facts are scored on
their *attribution* and the F1 exclusion is a red herring. A secondary cut: compare
*attributed* Tier-B facts ("the 3.0% median for metro solo practices") against *bare* ones
("the 3.0% peer median") under the narrow prompt, which tests my C1b(ii) claim that
attribution substitutes for visibility.

### T3 — The speculation-gap distribution (settles F2's residual)

Instrument a bot that logs, per trigger, `(context_push_ts → first appearance in
available_triggers)`. Run `_full`, `_phase2_short`, and a scripted mimic of the live Phase 2
per-tick injection. Report the gap distribution.

If p50 < 5s for freshly-injected triggers, ARCH-L's buffer argument fails precisely where
Phase 3's +25 lives, his urgency≤3 cache-miss drop bites on exactly the injected contexts
that matter most, and Layer 1 of the synthesis is not a nicety but a requirement. If p50 is
minutes, his design stands on its own and my Layer 1 is insurance.

### T4 — Cold-cache fact invariance, not byte identity (settles the determinism question honestly)

Run L's own `determinism_probe`: 30 pairs × 5 cold runs, cache disabled. Report byte-identity
**and** fact-invariance separately. His §2.4 predicts 96-99% byte-identity and 100%
fact-invariance.

The number that matters is the second one. If fact-invariance is 100%, his determinism
concession is genuinely cosmetic and I should stop pressing it — a moved comma is not
observable by any grader. If fact-invariance is below 100%, the composer is choosing
*different facts* across runs, which is quality variance wearing a determinism costume, and
my objection is live. I will accept whichever number comes back.

### T5 — Does templated sameness actually cost flow points? (settles C4)

The only test that reaches the channel I conceded in C4(4). Drive 20 conversations to the
same merchant-playing LLM, 5 turns each: 10 seeded with deterministic bodies, 10 with
LLM-composed bodies, matched on merchant and trigger family. Measure simulated-merchant
engagement (reply length, `intent_*` engagement tags, hostility/disengagement rate) and
score the resulting transcripts on flow.

If deterministic outreach provokes measurably worse merchant replies, ARCH-S's §4.6 concern
is real, my variation machinery is under-built, and L's quality argument gains a transmission
channel it currently only asserts. If not, "reads templated" is confined to the qualitative
report and is worth far less than L prices it.

---

## 5. Closing statement

My composition engine is better than either opponent priced it, and it got better under
cross-examination: F1 forced a Tier-A-anchored evidence spine, an attribution mandate on
every Tier-B fact, and a `semantic_relation` guard that caught a real fabrication bug in my
own worked example. F3 fixed a scenario my FSM failed outright.

My *architecture* did not survive as well. F2 is correct: composition belongs off the request
path, and once it is, the latency and ops arguments that carried a third of my thesis mostly
evaporate. C4 concedes that templated sameness has a real transmission channel through the
merchant-playing sub-LLM that I claimed did not exist.

So the honest conclusion is that I was right about the composer and wrong about where to put
it. The strongest bot on this board is not any of the three documents. It is L's topology,
my composer as the always-computed floor, S's policy layer, and a comparator between layers
1 and 2 that turns the central disagreement of this debate into a logged metric instead of
an argument — which is what T1 exists to settle.
