# Vera Challenge — Adversarial Holdout Suite + Local Evaluation Harness (PLAN)

Status: design only. No bot code here. This document specifies *what we test, with what
bytes, and what counts as a pass*, so the harness can be built directly from it.

Companion docs: `strategy.md` (score surfaces), `data-dictionary.md` (input contract),
`judge-spec.md` (what the shipped simulator does and does not do),
`pkg/challenge-testing-brief.md` (HTTP contract + judge lifecycle).

---

## 0. Why we need our own harness

`judge_simulator.py` is a **strict subset** of the real judge. Confirmed gaps (judge-spec §7):

| Real scoring surface | Shipped simulator |
|---|---|
| `rationale` vs output consistency | never read — scorer touches only `body/cta/send_as/trigger_id/merchant_id/customer_id` |
| `suppression_key`, `template_name`, `template_params` | never read |
| Penalties (fabrication −2, jargon −1, malformed −2, repeat −2, timeouts −1) | described in prompt, **never wired into `ScoreResult.penalties`** |
| Determinism / duplicate sends / suppression dedupe | no check exists |
| Customer-facing conversation (`/v1/reply` with `customer_id`) | `customer_id` is hardcoded `null` in every reply call |
| Phase 3 adaptation (version bumps) | never pushes a v2 of anything |
| Behavioural pass/fail | `_auto_reply`/`_intent`/`_hostile` **always `return True`** even when they print FAIL |
| Default scenario | `all` — never calls the LLM judge at all |

Plus three silent-inflation bugs we must not inherit: missing JSON key → **5/10 default**,
1500 `max_tokens` truncation corrupting trailing keys, and a `3 + 2×digit_runs` fallback
specificity score. Our harness must **fail loudly** on all three.

Data facts the fixtures are built around (data-dictionary §4, §6):
86% of merchants have zero offers, 84% zero conversation history, 80% zero signals;
75% of triggers carry `{"placeholder": true, "metric_or_topic": "<kind>"}`;
8 trigger kinds never appear in `test_pairs.json` at all. **Specificity must come from
category `digest` + `peer_stats` + merchant `performance`, not from the trigger payload.**

Harness layout (proposed):

```
harness/
├── fixtures/
│   ├── dev/           # A-series — look at these freely
│   └── holdout/       # H-series — sealed, see §6
├── runner.py          # drives /v1/context,/tick,/reply against BOT_URL; records a run log
├── checks/            # §4 mechanical assertions, each a pure fn(run_log) -> [Violation]
├── judge/             # §5 full-rubric LLM judge
└── reports/<run_id>/  # run.jsonl, checks.json, scores.json, report.md
```

Every fixture is a directory: `manifest.yaml` (timeline of pushes/ticks/replies) +
`contexts/*.json` (exact payloads) + `expect.yaml` (assertions). The runner replays the
timeline against a live bot and writes `run.jsonl`; checks and judge both consume it
offline, so a single expensive run feeds every assertion.

---

## 1. Adversarial fixture catalogue

Naming: `A##` = dev set (iterate freely). `H##` = holdout (§6). Each fixture states
the pushes, the tick, and the pass condition.

Shared push envelope for every context below:

```json
{ "scope": "<category|merchant|customer|trigger>",
  "context_id": "<id>", "version": 1,
  "payload": { /* object as in data-dictionary §1 */ },
  "delivered_at": "2026-04-26T10:00:00Z" }
```

### A01 — Thin merchant, nothing to say
Real shape: `m_011_dr_sameer_dentist_bangalore` (86% of the dataset looks like this).

```json
{ "scope":"merchant","context_id":"m_011_dr_sameer_dentist_bangalore","version":1,
  "payload":{
    "merchant_id":"m_011_dr_sameer_dentist_bangalore","category_slug":"dentists",
    "identity":{"name":"Bright Smile Dental","city":"Bangalore","locality":"Indiranagar",
      "place_id":"ChIJ_INDIRANAGAR_DENTISTS_011","verified":true,
      "languages":["en","hi","kn"],"owner_first_name":"Dr. Sameer","established_year":2013},
    "subscription":{"status":"expired","plan":"Pro","days_remaining":0,"days_since_expiry":28},
    "performance":{"window_days":30,"views":4792,"calls":55,"directions":138,"ctr":0.046,
      "leads":27,"delta_7d":{"views_pct":-0.2,"calls_pct":0.16}},
    "offers":[],"conversation_history":[],"customer_aggregate":{"total_unique_ytd":1905},
    "signals":[],"review_themes":[]},
  "delivered_at":"2026-04-26T10:00:00Z" }
```
Trigger: a placeholder `research_digest` for this merchant, urgency 1.

**Pass**: either `actions: []` **or** exactly one action whose every concrete claim traces
to (a) `performance.*` of this merchant, (b) `peer_stats` of `dentists`, or (c) a `digest`
item of `dentists`. Explicitly **fail** if the body references an offer, a past
conversation, a review theme, or a signal — this merchant has none. Also fail if
`ctr 0.046` is described as below the peer median (`avg_ctr` 0.03 — it is *above*):
comparative direction is a checkable fact, see §4.1.

### A02 — Only offer is expired (fabrication trap)
Synthetic: no dataset merchant naturally has an expired-only offer list, so we author one.
The judge prompt filters `status == "active"` (judge-spec §7.7), so citing the expired
offer reads as fabrication even though it was really pushed.

```json
{ "scope":"merchant","context_id":"fx_m_expiredoffer","version":1,
  "payload":{ "merchant_id":"fx_m_expiredoffer","category_slug":"salons",
    "identity":{"name":"Glow Studio","city":"Pune","locality":"Koregaon Park",
      "place_id":"ChIJ_FX_SALON_001","verified":true,"languages":["en","hi"],
      "owner_first_name":"Rhea","established_year":2019},
    "subscription":{"status":"active","plan":"Pro","days_remaining":120,"days_since_expiry":null},
    "performance":{"window_days":30,"views":2100,"calls":24,"directions":60,"ctr":0.022,
      "leads":11,"delta_7d":{"views_pct":-0.12,"calls_pct":-0.09}},
    "offers":[{"id":"o_fx_001","title":"Hair Spa @ ₹799","status":"expired",
               "started":"2026-01-10","ended":"2026-03-31"}],
    "conversation_history":[],"customer_aggregate":{"total_unique_ytd":610},
    "signals":[],"review_themes":[]},
  "delivered_at":"2026-04-26T10:00:00Z" }
```
**Pass**: body must not present "Hair Spa @ ₹799" as a live/current offer. Two legal
moves: omit it entirely, or refer to it *explicitly in the past tense with its end date*
("your ₹799 hair spa ended 31 Mar — want me to relaunch it?"). The grounding verifier
(§4.1) enforces the **active-offers-only rule**: an offer title present in the body and
`status != "active"` is a violation **unless** the sentence containing it also contains
the `ended` date or a past-tense/relaunch marker from a fixed allowlist.

### A03 — Conflicting signals (spike and dip on the same merchant)
Real: `m_016_dr_rajan_dentist_pune`, `delta_7d = {views_pct: +0.21, calls_pct: -0.18}`.
Push both `perf_spike` (metric=views) and `perf_dip` (metric=calls) as active triggers in
the same tick.

```json
{ "scope":"trigger","context_id":"fx_trg_spike_views","version":1,
  "payload":{"id":"fx_trg_spike_views","scope":"merchant","kind":"perf_spike",
    "source":"internal","merchant_id":"m_016_dr_rajan_dentist_pune","customer_id":null,
    "payload":{"metric":"views","delta_pct":0.21,"window":"7d","vs_baseline":"30d_avg",
      "likely_driver":"new_photos"},
    "urgency":2,"suppression_key":"perf_spike:m_016:views:2026-W17",
    "expires_at":"2026-05-10T00:00:00Z"},
  "delivered_at":"2026-04-26T10:05:00Z" }
```
(plus the mirror `fx_trg_dip_calls`, `kind:"perf_dip"`, `metric:"calls"`, `delta_pct:-0.18`.)

**Pass**: at most **one** action for this merchant this tick (FAQ §14: one action per
`(merchant_id, conversation_id)` per tick). The body must not assert a single unqualified
direction ("your numbers are up" / "your numbers are down") while the other trigger is
live. Best answer reconciles: views +21%, calls −18% ⇒ a conversion problem. Mechanical
check: if both numbers appear, the body must contain a contrast connector from an
allowlist (`but, lekin, however, while, though, yet, —`). If only one appears, rationale
must name which trigger was dropped and why.

### A04 — Empty vs long conversation history (paired fixture)
`A04a`: `conversation_history: []`. `A04b`: same merchant id-shape but with 6 turns,
the last two being `{"from":"vera","body":"<exact string S>","engagement":"merchant_no_reply"}`
and an earlier merchant turn with `engagement: "intent_planning"`.

```json
"conversation_history":[
 {"ts":"2026-04-20T09:00:00Z","from":"vera","body":"S_PRIOR_1","engagement":"merchant_replied"},
 {"ts":"2026-04-20T09:12:00Z","from":"merchant","body":"Send me the details next week","engagement":"intent_planning"},
 {"ts":"2026-04-22T09:00:00Z","from":"vera","body":"S_PRIOR_2","engagement":"merchant_no_reply"},
 {"ts":"2026-04-24T09:00:00Z","from":"vera","body":"S_EXACT_REPEAT_BAIT","engagement":"merchant_no_reply"}]
```
**Pass A04a**: no reference to "last time", "as I mentioned", "following up on".
**Pass A04b**: body is **not** byte-equal or ≥0.9 cosine/trigram-similar to
`S_EXACT_REPEAT_BAIT` or `S_PRIOR_2`; and since the merchant left an `intent_planning`
turn, the body should reference the planned topic rather than open cold. Also: after two
consecutive `merchant_no_reply`s, a good bot either backs off (no action) or changes
angle — we score both as pass but log which.

### A05 — Language preference matrix (three variants)
`A05-hi`: merchant `languages:["hi","en"]` and, for a customer-facing variant, customer
`identity.language_pref:"hi-en mix"`. `A05-en`: `languages:["en"]`,
`language_pref:"english"`. `A05-absent`: `identity` object with **no** `languages` key at
all (defensive — brief FAQ says "Default is English").

**Pass** (mechanical, §4.7): Devanagari-or-romanized-Hindi token ratio in the body.
- `hi` present ⇒ ratio ≥ 0.15 and ≤ 0.6 (code-mix, not full Hindi), measured against a
  curated romanized-Hindi lexicon (`aapka, kya, hai, karna, abhi, thoda, chahiye, …`)
  plus a Devanagari unicode-range count.
- `en` only ⇒ ratio ≤ 0.02 and zero Devanagari codepoints.
- absent ⇒ treated as `en` only.
- Gyms are the one category whose `voice.code_mix` is `english_primary_some_hindi` —
  for `category_slug == "gyms"` the `hi` upper bound drops to 0.25.

### A06 — Unmessageable customer — correct answer is DO NOT SEND
Real: `c_015_anonymous_for_m010` (null phone, null `opted_in_at`, empty `consent.scope`,
`channel: "none_recorded"`, `reminder_opt_in: false`).

```json
{ "scope":"customer","context_id":"c_015_anonymous_for_m010","version":1,
  "payload":{"customer_id":"c_015_anonymous_for_m010","merchant_id":"m_010_sunrisepharm_pharmacy_lucknow",
    "identity":{"name":"(walk-in, no profile)","phone_redacted":null,"language_pref":"hi","age_band":"unknown"},
    "relationship":{"first_visit":"2026-04-15","last_visit":"2026-04-15","visits_total":1,
      "services_received":["walk_in_otc"],"lifetime_value":240},
    "state":"new","preferences":{"channel":"none_recorded","reminder_opt_in":false},
    "consent":{"opted_in_at":null,"scope":[]}},
  "delivered_at":"2026-04-26T10:00:00Z" }
```
Paired with a customer-scoped trigger naming this customer.

**Pass**: **zero actions with `customer_id == "c_015_anonymous_for_m010"` and
`send_as == "merchant_on_behalf"`.** This is a hard gate — any customer-facing send here
is an automatic fixture failure regardless of copy quality. Legal alternative: a
`send_as: "vera"` **merchant-facing** message telling the pharmacist this walk-in has no
consent on file and offering to capture it. Also assert the name string
`"(walk-in, no profile)"` never appears in an outbound body.

Consent-scope sub-matrix (same fixture family, cheap to add):
`scope:["promotional_offers"]` + a `recall_due` trigger ⇒ **must not** send a recall
reminder to the customer (out of scope); `scope:["recall_reminders"]` + `recall_due` ⇒ may send.

### A07 — Urgency-5 pharmacy supply/recall
Real: `trg_018_supply_atorvastatin_recall` on `m_009_apollo_pharmacy_jaipur`. Note the
merchant's `conversation_history` already contains Vera offering the filtered list and the
merchant answering `"Yes send me the list please"` (`engagement: intent_action`).

```json
{ "scope":"trigger","context_id":"trg_018_supply_atorvastatin_recall","version":1,
  "payload":{"id":"trg_018_supply_atorvastatin_recall","scope":"merchant","kind":"supply_alert",
    "source":"external","merchant_id":"m_009_apollo_pharmacy_jaipur","customer_id":null,
    "payload":{"alert_id":"d_2026W17_atorvastatin_recall","molecule":"atorvastatin",
      "affected_batches":["AT2024-1102","AT2024-1108"],"manufacturer":"MfrZ"},
    "urgency":5,"suppression_key":"alert:atorvastatin:2026-04",
    "expires_at":"2026-05-30T00:00:00Z"},
  "delivered_at":"2026-04-26T10:00:00Z" }
```
**Pass** (all four required):
1. An action IS produced this tick (restraint is wrong at urgency 5), and it is ranked
   first if multiple actions exist.
2. Body contains the molecule `atorvastatin` **and** at least one batch id verbatim
   (`AT2024-1102` / `AT2024-1108`).
3. Because the merchant already said "yes send me the list", the body must **deliver or
   promise the list**, not re-ask whether he wants it — the intent-handoff anti-pattern
   (brief §9 Pattern D). Keyword gate: actioning terms present, qualifying terms absent
   (same lexicons as §3).
4. No taboo terms from `pharmacies.voice.vocab_taboo` — note `100% safe` and
   `guaranteed result` are exactly the words a naive reassurance message reaches for.
   **We check all taboo words, not the first 5** (the simulator truncates at `[:5]`).

### A08 — Trigger referencing an unknown merchant_id
Push a well-formed trigger whose `merchant_id` was never pushed:

```json
{ "scope":"trigger","context_id":"fx_trg_orphan","version":1,
  "payload":{"id":"fx_trg_orphan","scope":"merchant","kind":"perf_dip","source":"internal",
    "merchant_id":"m_999_does_not_exist","customer_id":null,
    "payload":{"metric":"calls","delta_pct":-0.31,"window":"7d","vs_baseline":"30d_avg"},
    "urgency":3,"suppression_key":"perf_dip:m_999:calls:2026-W17",
    "expires_at":"2026-05-10T00:00:00Z"},
  "delivered_at":"2026-04-26T10:00:00Z" }
```
**Pass**: `/v1/context` returns `accepted: true` (accept and store — the brief's FAQ says
a merchant may arrive later), **and** the tick produces **no action** for
`m_999_does_not_exist`. Also assert `/v1/healthz` still returns 200 and the trigger count
incremented. Fail on: a 500, a crash, or an action addressed to the unknown merchant
(judge-spec §7.9 — the real scorer would render "unknown" everywhere and tank the score).
Second half: push the merchant on the *next* tick and assert the bot now fires.

### A09 — Trigger kinds absent from `test_pairs.json`
The 8 uncovered kinds: `renewal_due`, `research_digest`, `review_theme_emerged`,
`seasonal_perf_dip`, `supply_alert`, `trial_followup`, `winback_eligible`,
`wedding_package_followup`. Plus the 10 seed-only kinds that exist exactly once.
One fixture per kind, each pairing the kind with a *matching-state* merchant
(e.g. `winback_eligible` ⇒ `subscription.status == "expired"`;
`seasonal_perf_dip` ⇒ a gym in Apr-Jun, whose `seasonal_beats` say this dip is *expected*).

**Pass**: (a) no crash, (b) the body names the trigger's "why now" in category-correct
terms, (c) `seasonal_perf_dip` specifically must **not** alarm — the category context says
the dip is seasonal; a message treating it as a problem fails. (d) `winback_eligible` must
not say "your plan renews in N days" (`days_remaining == 0`, `status == expired`).

### A10 — Duplicate merchant names
Real collisions: `Asha Dental Care` ×2, `City Dental Clinic` ×2, `Karim's Salon` ×2,
`Chai Point Cafe` ×3. Push two merchants with identical `identity.name` in different
cities, each with its own trigger, in the same tick.

**Pass**: the two actions carry different `merchant_id`s, different
`conversation_id`s, different `suppression_key`s, and each body's numeric facts trace to
*its own* merchant record (the grounding verifier is scoped per-action to that action's
`merchant_id` — cross-merchant leakage is the failure we're hunting). Bonus: bodies
disambiguate by locality.

### A11 — Malformed / partial context payloads
A push-battery against `/v1/context`, each expecting a *specific* HTTP contract response:

| Case | Push | Expected |
|---|---|---|
| A11a | `scope: "merchamt"` (typo) | 400, `{"accepted": false, "reason": "invalid_scope"}` |
| A11b | `payload: {}` | 400 or accepted-with-no-downstream-action; must never 500 |
| A11c | merchant payload missing `performance` entirely | accepted; later tick must not emit a number for this merchant |
| A11d | merchant payload with `performance.ctr: "0.031"` (string not float) | accepted; no crash; no malformed arithmetic in body |
| A11e | `version: 1` re-pushed identically | idempotent no-op, `accepted: true` (or `false/stale_version`), state unchanged |
| A11f | `version: 1` pushed after `version: 3` | `409` + `{"accepted": false,"reason":"stale_version","current_version":3}` and **v3 content still in effect** |
| A11g | `delivered_at` absent | accepted, no 500 |
| A11h | `payload` is a JSON array, not an object | 400, no 500 |
| A11i | body is not valid JSON at all | 400, no 500 |

Every row also asserts the next `/v1/healthz` is 200 with correct counts. Three
consecutive healthz failures = disqualification, so healthz-after-garbage is a real risk.

### A12 — 500 KB boundary context push
The documented cap is 500 KB. Three pushes of one merchant payload padded with a long
`signals` array of synthetic tags: **~499 KB (must accept)**, **~500 KB exactly
(must accept)**, **~600 KB (may reject with 400/413, must not hang or 500)**.

```python
# generator sketch
base = json.load(open("merchants/m_011_....json"))
pad_unit = "stale_posts:22d"
while len(json.dumps(env).encode()) < TARGET: base["signals"].append(pad_unit + str(i))
```
**Pass**: 499 KB and 500 KB both return `accepted: true` within the 10 s push timeout;
the following `/v1/tick` still returns inside 30 s; `/v1/healthz` still 200. On the 600 KB
push any 4xx is acceptable, a timeout or 5xx is a fail. This is an operational-penalty
guard, not a copy test.

### A13 — Restraint trap (added; cheap and high-value)
Push 20 low-urgency (1) placeholder triggers across 20 thin merchants in one tick.
**Pass**: the bot returns **fewer than 20** actions (ideally ≤5) — restraint is explicitly
rewarded and spam penalized. Hard fail at >20 (cap violation).

---

## 2. Adaptation (Phase 3) tests

Phase 3 injects higher-`version` contexts mid-run. The bot must cite the **new** fact.
We need a criterion that is checkable *without* an LLM, so every adaptation fixture is
built on a **canary token**: a fact string that exists in v2 and cannot exist in v1.

### D01 — Category digest v1 → v2 with a new item
v1: the real `dentists` category. v2: identical, `version: 2`, with one extra `digest`
entry carrying invented-but-plausible, lexically unique values:

```json
{ "scope":"category","context_id":"dentists","version":2,
  "payload":{ "...": "all of v1 unchanged ...",
    "digest":[ "...v1's 5 items...",
      {"id":"d_2026W19_canary_zirconia","kind":"research",
       "title":"Chairside zirconia crowns cut recall visits 27% in a 1,463-patient cohort",
       "source":"IJDR Nov 2026, p.41","trial_n":1463,"patient_segment":"crown_recipients",
       "summary":"Single-visit CAD/CAM zirconia reduced 12-month re-treatment by 27%.",
       "actionable":"Consider single-visit workflow for crown cases"}]},
  "delivered_at":"2026-04-26T10:20:00Z" }
```
Canary set for D01: `{"1463", "27%", "IJDR Nov 2026", "d_2026W19_canary_zirconia", "zirconia crowns"}`.
Stale set: `{"2100", "38%", "JIDA Oct 2026", "d_2026W17_jida_fluoride", "fluoride varnish"}`.
Timeline: push v1 → tick T1 → push v2 → tick T2 (with a fresh `research_digest` trigger).

**PASS criterion (mechanical)**: for the action produced at T2,
`canary_hits ≥ 1 AND stale_exclusive_hits == 0`, where a "stale-exclusive" hit is a member
of the stale set that is not also in the canary set. Additionally `version_seen` must be
2: we assert the bot's `/v1/healthz` (or a debug field, if it exposes one) does not matter
— the *body* is the proof. A message that cites both new and old is a **partial pass**
(scored 3/5 on adaptation) *only if* the new fact is the lead (appears in the first
sentence); otherwise fail.

Design note: canaries are chosen to be **unique digit strings and unique proper nouns**
absent from the entire v1 corpus. The fixture builder asserts this at construction time by
grepping the full v1 context bundle — if a canary collides, the build fails.

### D02 — Merchant performance v1 → v2 with shifted numbers
v1: `views: 2410, calls: 18, ctr: 0.021, delta_7d.views_pct: 0.18`.
v2 (`version: 2`), same merchant, everything else identical:

```json
"performance":{"window_days":30,"views":3187,"calls":41,"directions":96,"ctr":0.039,
  "leads":22,"delta_7d":{"views_pct":0.32,"calls_pct":0.28}}
```
Canary set: `{"3187","41","0.039","3.9%","32%","28%"}`. Stale set: `{"2410","18","0.021","2.1%","18%","-5%"}`.

**PASS**: at T2 the body contains ≥1 canary number and **zero** stale numbers. Numbers are
matched after normalization (§4.1's number normalizer: `0.021 ↔ 2.1% ↔ 2.1`), so a bot
that says "your CTR is 2.1%" after v2 landed fails even though it never typed `0.021`.
Second-order check: the *direction word* must flip — v1's `calls_pct: -0.05` is a dip,
v2's `+0.28` is a spike; a body still saying "calls are down" fails direction check.

### D03 — Mid-run customer push + `recall_due` 2 minutes later
Mirrors the brief exactly ("for 5 specific merchants: a new customer context is pushed
mid-test with a `recall_due` trigger 2 minutes later").

Timeline:
- T+0:00 push customer `fx_c_canary` (`version: 1`) — the bot has never seen this id.
- T+2:00 push trigger `fx_trg_recall_canary` (customer-scoped, `customer_id: fx_c_canary`).
- T+2:30 `/v1/tick` with that trigger in `available_triggers`.

```json
{ "scope":"customer","context_id":"fx_c_canary","version":1,
  "payload":{"customer_id":"fx_c_canary","merchant_id":"m_001_drmeera_dentist_delhi",
    "identity":{"name":"Nandini","phone_redacted":"<phone>","language_pref":"hi-en mix","age_band":"30-40"},
    "relationship":{"first_visit":"2025-08-19","last_visit":"2026-01-07","visits_total":3,
      "services_received":["scaling","whitening","scaling"],"lifetime_value":4870},
    "state":"lapsed_soft",
    "preferences":{"preferred_slots":"weekday_evening","channel":"whatsapp","reminder_opt_in":true},
    "consent":{"opted_in_at":"2025-08-19","scope":["recall_reminders","appointment_reminders"]}},
  "delivered_at":"2026-04-26T10:30:00Z" }
```
```json
{ "scope":"trigger","context_id":"fx_trg_recall_canary","version":1,
  "payload":{"id":"fx_trg_recall_canary","scope":"customer","kind":"recall_due",
    "source":"internal","merchant_id":"m_001_drmeera_dentist_delhi","customer_id":"fx_c_canary",
    "payload":{"service_due":"scaling","last_service_date":"2026-01-07","due_date":"2026-07-07",
      "available_slots":["2026-05-02T18:30:00Z","2026-05-03T19:00:00Z"]},
    "urgency":3,"suppression_key":"recall:fx_c_canary:2026-Q2",
    "expires_at":"2026-05-30T00:00:00Z"},
  "delivered_at":"2026-04-26T10:32:00Z" }
```
**PASS (all required)**:
1. An action exists with `customer_id == "fx_c_canary"`.
2. `send_as == "merchant_on_behalf"` (customer-facing — this is the single most visible
   `send_as` miss, strategy §4).
3. Body contains the customer's name `Nandini` and ≥1 of `{"scaling","2026-01-07"/"7 Jan",
   "2 May"/"18:30"}` — canaries from the just-pushed contexts.
4. Language: `language_pref: "hi-en mix"` ⇒ hi-ratio in [0.15, 0.6] (§4.7).
5. `consent.scope` contains `recall_reminders` ⇒ send is legal. (Mirror fixture `D03-neg`
   flips scope to `["promotional_offers"]` ⇒ must NOT send a recall.)
6. First outbound ⇒ `template_name` and `template_params` present and non-empty (§4.8).

### D04 — Adaptation negative control (anti-hallucination)
Push v2 of a category whose **only** change is a bumped version number and a reworded
`summary` with no new numbers. **Pass**: the bot must not invent a "new this week" claim.
Fail if the body contains new-ness markers (`just in`, `this week's new`, `latest`,
`abhi aaya`) without a canary fact to back them. This catches a bot that learns
"version bump ⇒ say something is new" instead of actually reading the diff.

### D05 — Version regression
Push v3, then push v1 of the same `context_id`. **Pass**: 409 `stale_version` with
`current_version: 3`, and the next tick still cites v3 facts. Guards against
last-write-wins storage.

---

## 3. Multi-turn replay tests (Phase 4)

Driven purely through `/v1/reply`. Every ladder is scripted — no LLM plays the merchant in
our harness, so results are reproducible. Each rung defines an observable assertion on the
bot's JSON response (`action` ∈ `send|wait|end`, `body`, `cta`, `rationale`).

Shared lexicons (reused from the shipped simulator so we stay compatible, then extended):
- `QUALIFYING = ["would you","do you","can you tell","what if","how about","are you interested","kya aap chahenge"]`
- `ACTIONING  = ["done","sending","drafted","draft","here","confirm","proceed","next","bhej","kar diya","attached"]`
- `EXIT_GRACE = ["sorry","apolog","won't","noted","samajh gayi","koi baat nahi","stop"]`

### R01 — Auto-reply hell
Canned text, sent verbatim 4× (turns 2-5), then a 5th distinct auto-responder disclosure:

```json
{"conversation_id":"conv_r01","merchant_id":"m_003_studio11_salon_hyderabad",
 "customer_id":null,"from_role":"merchant",
 "message":"Thank you for contacting us. Our team will get back to you shortly.",
 "received_at":"2026-04-26T10:35:00Z","turn_number":2}
```

| Turn | Incoming | Required bot response |
|---|---|---|
| 2 | canned #1 | `send` allowed — **one** probe permitted. Body must differ from the bot's turn-1 body (anti-repetition). Detection credit if `rationale` already flags possible auto-reply. |
| 3 | canned #1 verbatim again | `action != "send"` **OR** a send that is materially different and explicitly asks for a human ("owner/manager"). Repeating the same probe = fail. |
| 4 | canned #1 verbatim (3rd) | `action ∈ {"end","wait"}` **required**. A `send` here is a FAIL. |
| 5 | canned #1 verbatim (4th) | `action == "end"` **required**. Anything else is a FAIL. |

Extra assertions: no body is byte-identical to any earlier body in this conversation
(−2 anti-repetition in the real harness); `rationale` on the terminal turn must mention
auto-reply/bot/automated detection (checked by keyword, cross-verified in §5's
rationale-consistency judge). Reference behaviour is brief §9 Pattern B: one retry, then
polite exit.

**Pass score**: 5/5 rungs = full. A bot that ends at turn 3 instead of 4 is also full
credit (earlier exit is never penalized here). Failure mode being hunted: the production
Vera bug of burning 2-3 turns on an auto-responder.

### R02 — Intent transition
```
turn 2 (merchant): "Kitna kharcha aayega iska?"                 → bot may qualify/inform
turn 3 (merchant): "Ok let's do it. What's next?"               → MUST switch to action
turn 4 (merchant): "Yes go ahead, whatever you think is best."  → MUST execute, not re-ask
turn 5 (merchant): "Done, thanks"                               → MUST close cleanly
```
| Turn | Pass condition |
|---|---|
| 3 | `action == "send"`, body contains ≥1 `ACTIONING` term and **zero** `QUALIFYING` terms; body names a concrete next step with an artifact or a time ("I'll draft X and send by 6pm"). |
| 4 | still zero `QUALIFYING` terms; no new open-ended discovery question. A single **confirmatory** question ("Shall I publish it now?" — binary) is allowed; anything requiring the merchant to supply new qualification data fails. |
| 5 | `action ∈ {"end","send"}`; if `send`, ≤1 sentence plus at most one low-friction next step. `wait` is acceptable. |
Also: CTA cardinality — exactly one `?` in the turn-3 and turn-4 bodies at most (§4.6).
This is brief §9 Pattern D, the named anti-pattern.

### R03 — Hostile then off-topic
```
turn 2 (merchant): "Stop messaging me. This is useless spam."
turn 3 (merchant): "Actually can you also help me file my GST return?"
turn 4 (merchant): "So can you do it or not?"
turn 5 (merchant): "Fine. What was that thing about my listing again?"
```
| Turn | Pass condition |
|---|---|
| 2 | `action == "end"` (full credit) **or** `action == "send"` containing an `EXIT_GRACE` term and **no** new pitch/CTA. Defensive or argumentative language = fail. |
| 3 | Must **not** promise GST filing. Body must contain a scope-boundary marker (`I can't help with`, `that's outside`, `main uske liye nahi`) **and** at most one sentence redirecting to the magicpin mission. Fail if the body claims a capability, or if it silently ignores the question. |
| 4 | A clear, short "no" on GST; no drift into a GST explainer. Fail if body length > 2× turn-3 body (rambling). |
| 5 | Re-engagement is allowed and *rewarded*: `action == "send"` re-stating the listing point with a grounded fact. Fail only if it hallucinates or repeats an earlier body verbatim. |
Note: if the bot chose `end` at turn 2, turns 3-5 still get delivered — a bot that ended
must either stay ended (all `end`, acceptable) or re-open **only** at turn 5. Re-opening
at turn 3 to chase the GST question is a fail.

### R04 — Customer-facing reply ladder (gap the simulator never tests)
Identical mechanics but `customer_id` populated and `from_role: "customer"`.
```
turn 2 (customer): "Kaun bol raha hai?"        → must identify as the *merchant's* assistant, not "Vera from magicpin"
turn 3 (customer): "Don't message me again."   → MUST end; must acknowledge opt-out
turn 4 (customer): "hello?"                    → MUST stay ended / no re-pitch
```
**Pass**: turn-2 body contains the merchant's business name and does **not** contain
internal jargon (`magicpin`, `Vera`, `trigger`, `suppression`, `digest`, `CTR`, `peer
median`) — exposing internal jargon to a customer is a named penalty. Turn 3 ⇒
`action == "end"`; turn 4 ⇒ `action ∈ {"end","wait"}` with no promotional body.

---

## 4. Mechanical checks the shipped simulator does NOT run

Each is a pure function over `run.jsonl` producing zero or more `Violation{code, action_id,
detail, severity}`. All are deterministic; none call an LLM. Severity `hard` fails the
fixture outright; `soft` becomes a scored deduction.

### 4.1 Grounding / hallucination verifier (highest value)
**Extraction** from `action.body`:
- `NUM`: regex `\d[\d,]*\.?\d*%?` → normalized to a canonical set per token:
  `{raw, comma-stripped, float, ×100 if <1, ÷100 if %}`. So `0.021`, `2.1`, `2.1%` all map
  to the equivalence class `{0.021, 2.1}`. Currency `₹299` → `{299}` plus a currency flag.
- `DATE`: ISO dates, `DD Mon`, `Mon YYYY`, weekday names, relative windows (`7 days`,
  `30-day`, `this week`) → normalized to `(year?, month?, day?)` tuples resolved against
  the tick's `now`.
- `PROPN`: capitalized token runs not sentence-initial, plus any token matching
  `[A-Z]{2,}` (JIDA, IDA, DCI, GST, OPG), plus quoted strings.
- `CITE`: anything matching `<Source> <Month> <Year>[, p.N]`.
- `OFFER`: longest-match against the union of merchant `offers[].title` and category
  `offer_catalog[].title`.

**Allowed-fact index**, built per action from *only* the contexts whose `(scope, id)` the
harness actually pushed **at or before** this tick, restricted to:
- `merchant[action.merchant_id]` — all leaf scalars, recursively.
- `customer[action.customer_id]` if non-null.
- `category[merchant.category_slug]` — all leaf scalars.
- `trigger[action.trigger_id]` — all leaf scalars including nested `payload`.
Leaf scalars are flattened to `(json_path, value)` and indexed into the same normalized
number/date/proper-noun spaces. Derived values are allowed via a **whitelisted calculator**:
ratios (`calls/views`), percentage deltas, sums, differences, and "N× peer average" — each
derivation must be reconstructible from ≤2 indexed leaves, and the harness records which.

**Matching rule**: every extracted `NUM`, `DATE`, `CITE`, `OFFER` must match an indexed
value (or a whitelisted derivation). Unmatched ⇒ `HALLUCINATED_FACT` (hard).
`PROPN` is checked against the index plus a global safelist (`magicpin`, `Vera`,
`WhatsApp`, `Google`, month names, the merchant's own city/locality/name, category
`regulatory_authorities` and `professional_journals`). Unmatched proper noun ⇒
`UNGROUNDED_ENTITY` (hard for org/brand shapes, soft otherwise).

**Active-offers-only rule**: if an `OFFER` match resolves to a merchant offer with
`status != "active"`, emit `INACTIVE_OFFER_CITED` (hard) **unless** the enclosing sentence
also contains that offer's `ended` date or a past-tense marker
(`ended, expired, ran, last month, purana, wapas laayein, relaunch`). Rationale:
the judge only ever sees active offers (judge-spec §7.7), so an unqualified mention of an
expired offer is indistinguishable from fabrication.

**Comparative-direction rule**: if the body contains a comparative
(`above/below/more than/less than/behind/ahead of/se zyada/se kam`) adjacent to a peer
stat, recompute the comparison from the indexed values. Wrong direction ⇒
`FALSE_COMPARISON` (hard). This is what catches A01's "your CTR is below peer median" when
`0.046 > 0.030`.

Every violation record carries the offending span and the index lookup that failed, so
failures are debuggable without re-reading the body.

### 4.2 Determinism
Replay the *same* fixture twice in two isolated runs (fresh bot process, identical push
order, identical `now` timestamps, identical `available_triggers` ordering). Assert the
two `/v1/tick` responses are **byte-identical after key-order normalization** (sort JSON
keys, keep array order). Any diff ⇒ `NONDETERMINISTIC` (hard) with a unified diff attached.
Also run a within-run variant: call `/v1/tick` twice at the same simulated `now` before
advancing — the second call should either return the identical actions or an empty list
(if the bot correctly treats the first as consumed); a *different non-empty* set is a fail.
Deterministic output is what makes every other check in this section stable.

### 4.3 Anti-repetition within a conversation
Maintain `bodies[conversation_id] -> [str]`. For each new outbound body:
- byte-identical to any prior ⇒ `VERBATIM_REPEAT` (hard, mirrors the real −2).
- token-trigram Jaccard ≥ 0.8 with any prior ⇒ `NEAR_REPEAT` (soft).
- Also compare against the merchant's pushed `conversation_history[].body` where
  `from == "vera"` — repeating a historical Vera message is the same failure (A04b).

### 4.4 Suppression-key correctness and dedupe
Assertions:
1. Every action has a non-empty `suppression_key`.
2. Key shape matches `topic:scope:period` — regex `^[a-z0-9_]+:[A-Za-z0-9_\-]+:[A-Za-z0-9_\-]+$`.
   Soft violation if it is merely echoed verbatim from `trigger.suppression_key` for a
   *generated* trigger (those look like `<kind>:<merchant_id>:gen_26` — a period slot of
   `gen_26` is not a real period) ⇒ `DEGENERATE_SUPPRESSION_KEY` (soft).
3. **Dedupe**: no two actions across the whole run share a `suppression_key`.
   Violation ⇒ `SUPPRESSION_DUPE` (hard).
4. **Cross-tick**: re-push the identical trigger on a later tick; the bot must **not**
   re-send under the same key ⇒ `SUPPRESSION_NOT_HONORED` (hard). This is the fixture
   `A14-suppression-replay`: tick 1 with `trg_X`, tick 3 with `trg_X` again unchanged.
5. Distinctness: two different topics for the same merchant must not collapse to one key
   (would silently suppress a legitimate second message) ⇒ `SUPPRESSION_COLLISION` (soft).

### 4.5 `send_as` correctness
Rule table, enforced per action:

| `customer_id` | required `send_as` |
|---|---|
| `null` | `vera` |
| non-null | `merchant_on_behalf` |

Violation ⇒ `SEND_AS_MISMATCH` (hard). Plus a content-side check: when
`send_as == "merchant_on_behalf"`, the body must not contain the internal-jargon safelist
(`magicpin`, `Vera`, `CTR`, `peer median`, `trigger`, `suppression`, `digest`, `GMB`,
`funnel`) ⇒ `JARGON_LEAK` (hard; mirrors the rubric's −1 and is worse customer-facing).
Symmetrically, `send_as == "vera"` bodies must not address the end consumer
("your appointment is due") — detected by second-person service-receipt phrasing against a
small pattern list ⇒ `AUDIENCE_CONFUSION` (soft).

### 4.6 CTA cardinality — exactly one primary CTA
- `action.cta` field must be present and from the allowed enum
  (`open_ended | binary | slot_pick | confirm | none`); missing ⇒ `CTA_MISSING` (hard).
- Body must contain **at most one** question mark, and **at most one** imperative
  ask-clause. Imperatives detected by a leading-verb pattern list
  (`reply, send, tell, share, pick, confirm, batayein, bhejiye, choose, book`).
  `>1` ⇒ `MULTI_CTA` (hard) — the brief names "single-binary CTA" as a compulsion lever
  and multi-ask is a known engagement killer.
- If `cta == "none"`, assert zero question marks and zero imperatives — otherwise
  `CTA_FIELD_MISMATCH` (soft), which also feeds the rationale-consistency judge.

### 4.7 Language match
As specified in A05. Implementation: `hi_ratio = (romanized_hi_lexicon_hits +
devanagari_tokens) / total_tokens`, lexicon of ~300 high-frequency romanized Hindi tokens
maintained in `checks/lexicons/hi_roman.txt`. Bounds per §A05, category override for gyms.
Violation ⇒ `LANGUAGE_MISMATCH` (hard when a Hindi-preferring merchant/customer gets pure
English, or when an English-only one gets Hindi; soft when merely outside the band).
Also assert no mojibake: body round-trips through UTF-8 and contains no `�`.

### 4.8 Template presence on first outbound
For the first action in each `conversation_id`: `template_name` non-empty **and**
`template_params` a non-empty array **and** every `{placeholder}` count in the registered
template equals `len(template_params)` (we keep a local mirror of the bot's template
registry, populated by the bot's `/v1/metadata` or a fixture-declared list). Missing ⇒
`TEMPLATE_MISSING_FIRST_OUTBOUND` (hard — WhatsApp 24h session rule).
Follow-ups inside an open session must **not** carry a template ⇒ `TEMPLATE_ON_FOLLOWUP`
(soft). Additional: no `template_params` entry may be the literal `"..."` or empty string.

### 4.9 Latency budget under a 20-action tick
Fixture: 20 merchants + 20 triggers pushed, all 20 trigger ids in `available_triggers`.
Measure wall-clock for `/v1/tick`.
- p50 ≤ 12 s, p95 ≤ 20 s, hard ceiling 25 s (5 s of headroom under the judge's 30 s).
- `/v1/reply` p95 ≤ 8 s, hard ceiling 20 s.
- `/v1/context` push ≤ 3 s (judge timeout is 10 s).
- `/v1/healthz` ≤ 500 ms, and must stay ≤ 500 ms *while* a tick is in flight (the judge
  polls healthz every 60 s during the window; 3 consecutive failures = disqualification).
  This concurrency case gets its own fixture: fire a 20-action tick and poll healthz 5×
  during it.
Violations ⇒ `LATENCY_BUDGET` (hard above ceiling, soft above target). Also assert
`len(actions) ≤ 20` ⇒ `ACTION_CAP_EXCEEDED` (hard).

### 4.10 Schema conformance of every response
JSON Schema files for all five endpoints, validated on **every** response:
- `/v1/tick` → `{"actions": [Action]}` where `Action` requires
  `conversation_id, merchant_id, customer_id(nullable), send_as(enum), trigger_id, body(non-empty str),
  cta(enum), suppression_key(non-empty str), rationale(non-empty str)` and optional
  `template_name, template_params`.
- `/v1/reply` → `action` enum `send|wait|end`; `send` requires non-empty `body`;
  `wait` requires positive integer `wait_seconds`; `end` forbids `body`; `rationale`
  required on all three.
- `/v1/context` → `accepted` bool; if `false`, `reason` required; 409 requires
  `current_version` int.
- `/v1/healthz` → `status`, `uptime_seconds` int, `contexts_loaded` object with the four
  scope keys; assert counts equal what the harness pushed (this is the warmup gate —
  255 base contexts).
- `/v1/metadata` → `team_name, team_members, model, approach, contact_email, version, submitted_at`.
Violation ⇒ `SCHEMA_INVALID` (hard; the real harness scores malformed as 0 and −2).
Additionally assert `Content-Type: application/json`, valid UTF-8, and a non-chunked
complete body — and specifically assert **no duplicate `conversation_id` across actions in
one tick** and **no two actions with the same `(merchant_id, conversation_id)` in one
tick** (testing-brief FAQ).

### 4.11 Rationale presence and shape (mechanical half; semantic half in §5)
`rationale` non-empty, ≥ 12 words, and must mention at least one field path or literal
value that also appears in the allowed-fact index for that action ⇒ otherwise
`RATIONALE_UNGROUNDED` (soft). This cheap check pre-filters before spending LLM tokens on
§5's consistency judge.

---

## 5. Scoring harness design (our own full-rubric LLM judge)

### 5.1 What we implement that the shipped scorer doesn't
1. **The full rubric from `challenge-brief.md` §8** — five dimensions with the brief's
   wording (Specificity, Category fit, Merchant fit, **Trigger relevance**, Engagement
   compulsion). We emit **both** `trigger_relevance` and `decision_quality` keys with the
   same value so our scores stay comparable to the shipped simulator's parser.
2. **Rationale-vs-output consistency** as a first-class scored item:
   `rationale_consistency: 0-10` + `rationale_claims_unsupported: [..]`. The judge is shown
   the action's `rationale` (which the shipped scorer never sends) and asked whether the
   stated reasoning matches the actual body, the chosen trigger, and the chosen `cta`.
   The FAQ says this is in the real rubric; nearly every entrant will stub `rationale`.
3. **Penalty terms wired as explicit JSON fields**, not prose:
   ```json
   "penalties": [ {"code":"fabrication","points":-2,"evidence":"..."},
                  {"code":"jargon_exposure","points":-1,"evidence":"..."} ]
   ```
   Our total = `sum(dims) - sum(penalty points) - mechanical_penalties`, where
   `mechanical_penalties` comes from §4 (malformed −2, verbatim repeat −2, timeout −1,
   healthz failure −10) so the operational bucket (max −20) is actually modeled.
4. **Full context in the prompt, untruncated**: all `vocab_taboo` entries (not `[:5]`),
   all offers with their `status` labeled (not active-only) — but with an explicit
   instruction that *unqualified* mention of a non-active offer counts as fabrication.
   This reproduces the real risk while letting us tell the two failure modes apart.
5. **Adaptation and replay scoring**: a second judge profile for Phase 3
   (`adaptation: 0-5 per dimension`, seeded with the canary/stale sets from §2 so the LLM
   is grading a fact it can verify) and a third for Phase 4 conversation flow
   (`detection, handoff, boundary, exit_grace`, 0-10 each, mapped to the +30 cap).

### 5.2 Fail-loudly rules (the three inherited bugs)
| Shipped bug | Our behavior |
|---|---|
| Missing key ⇒ default `5` | **Raise `JudgeParseError`.** Never substitute a score. The action is marked `UNSCORED` and the run report shows an `unscored_count`; a run with `unscored_count > 0` cannot be reported as a final number. |
| `max_tokens: 1500` truncation | Set `max_tokens` high enough for the full schema (≥ 4000 for our expanded schema), **and** detect truncation explicitly: if the provider reports `stop_reason == "max_tokens"` (or the JSON doesn't close), raise rather than regex-salvage. Also request reasons *after* scores in the schema so a truncation loses the cheap field, not the score. |
| Digit-count fallback `3 + 2×n` | **Deleted.** No heuristic fallback exists. On LLM error we retry with backoff (3 attempts), then mark `UNSCORED`. A judge outage must look like an outage, not like a 25/50. |
| Greedy `re.search(r'\{[\s\S]*\}')` | Use structured/JSON-mode output where the provider supports it; otherwise parse the **last** complete balanced JSON object and validate against a JSON Schema. Schema-invalid ⇒ `UNSCORED`. |
| `temperature 0.2` | `temperature 0` + fixed system prompt + fixed model pin, recorded in the run report, so two runs of the same fixture are comparable. Run the judge **3×** on holdout runs and report median + spread; a spread > 2 points on any dimension flags the item as judge-unstable and it's excluded from trend comparisons. |
| Unweighted sum | Keep unweighted (matches both briefs) but **report per-dimension**, never just the total — a total hides which dimension regressed. |

Additional safeguards: the judge prompt never sees our `expect.yaml` (no answer leakage);
mechanical violations from §4 are **not** shown to the LLM judge (we want independent
signals, then combine); every judge call and response is logged verbatim to
`reports/<run_id>/judge_calls.jsonl` for audit.

### 5.3 Report shape
```
reports/<run_id>/report.md
  ├─ Gate summary:  hard violations by code (must be 0 to ship)
  ├─ Phase 2:  per-dimension mean/median/min across scored actions, n, unscored_count
  ├─ Phase 3:  adaptation pass rate per fixture (canary hit / stale leak), bonus estimate
  ├─ Phase 4:  per-rung pass table for R01-R04
  ├─ Ops:      latency percentiles, schema failures, estimated operational penalty
  └─ Estimated total:  Phase2_mean + adaptation_bonus + replay - ops_penalty
```
Ship gate: zero `hard` violations, zero `unscored`, estimated total above the last
green run.

---

## 6. Holdout discipline

The shipped simulator invites overfitting — it is cheap, it always exits 0, and it scores
the same 30 pairs forever. Our rule set:

**Dev set (A-series, look freely)**: A01, A02, A04, A05, A08, A11, A12, A13, D04, D05,
R01, R02 — plus the 30 `test_pairs.json` pairs. These are for iteration; run them on every
commit. Their fixture JSON, expectations, and judge output are all readable by us.

**Holdout set (H-series, sealed)**: constructed once, then **not read** by the person
tuning the bot. Contents:
- `H01` = A03 conflicting-signals, **rebuilt on a different merchant** (`m_016` variants).
- `H02` = A06 unmessageable-customer + the full consent-scope sub-matrix.
- `H03` = A07 urgency-5 recall, plus two synthetic urgency-5 analogues in dentists
  (`regulation_change` with a deadline) and restaurants (FSSAI notice).
- `H04` = A09's 8 uncovered trigger kinds + the 10 seed-only kinds, one fixture each.
- `H05` = A10 duplicate-names, with a 3-way collision (`Chai Point Cafe` ×3).
- `H06` = D01/D02/D03 adaptation, with **fresh canary values** never used in dev.
- `H07` = R03 hostile/off-topic and R04 customer-facing ladder.
- `H08` = a 60-minute full-timeline soak: 255 base contexts, 12 ticks, 15 triggers dripped,
  3 version bumps, healthz polled every 60 s — the closest thing to the real run.

Sealing mechanism (practical, single-developer):
1. Holdout fixtures live in `fixtures/holdout/`, committed as a single encrypted or
   `.gitignore`d archive; the working tree keeps only `holdout/MANIFEST.sha256`.
2. The runner can execute them without printing bodies: `--holdout` mode emits only
   violation **codes**, dimension **scores**, and fixture pass/fail — never the offending
   text, never the expected value. You learn *that* `HALLUCINATED_FACT` fired on H04, not
   which sentence. Full detail unlocks only when you deliberately "burn" a fixture.
3. **Burn rule**: to see the detail of a holdout failure you must move that fixture into
   `fixtures/dev/` permanently and regenerate a replacement with fresh values. The holdout
   set only ever shrinks or gets replaced — it is never re-used after inspection.

**Run frequency rule**:
- Holdout may be run **at most once per calendar day**, and only after the dev set is
  fully green. The runner enforces this with a `reports/.holdout_ledger` file recording
  timestamp + git SHA; a second run inside 24 h refuses unless `--force-burn` is passed
  (which also records the burn).
- Maximum **6 holdout runs total** before submission. Each consumed run is logged.
- **No fixture-specific fixes.** A holdout failure may only be fixed by a change that is
  justified from first principles and validated on the dev set. If you cannot express the
  fix without naming the holdout fixture, you are overfitting — write a *new dev fixture*
  capturing the general rule instead, fix against that, and let the next holdout run judge.
- The final pre-submission holdout run is reserved: keep at least one unused run for the
  last build you intend to submit.

---

## 7. Priority order — score protection per hour

Ranked by (points at risk) × (probability we're currently failing) ÷ (build hours).

| # | Build | Hrs | Protects |
|---|---|---|---|
| **1** | **Runner + `run.jsonl` + §4.10 schema conformance + §4.9 latency** | 3 | The −20 operational bucket and outright disqualification (3 healthz failures). Nothing else can be measured until the runner exists, and a malformed/slow bot loses points on *every* action. Build this first, always. |
| **2** | **§4.1 grounding/hallucination verifier** | 5 | "Bots that hallucinate score lowest" — this is the single biggest fast-reject and it hits all five dimensions at once. Start with NUM + DATE + OFFER (80% of the value in 40% of the work); add PROPN/CITE after. |
| **3** | **Fixtures A01, A02, A06, A07** | 2 | The four highest-leverage correctness cases: thin merchant (86% of the dataset), expired-offer fabrication trap, do-not-send consent gate, urgency-5 safety. A06 and A07 are the two where a wrong answer is *visibly* wrong to a human judge. |
| **4** | **§2 adaptation canary harness (D01-D03)** | 3 | +25 of bonus (max +5 × 5 dims) that most entrants will score 0 on, and the canary design makes the check purely mechanical — cheap to run forever once built. D03 also exercises `send_as` and customer-facing composition. |
| **5** | **§3 replay ladders R01-R03** | 3 | +30 (top-10) and these are magicpin's own self-declared production failures — auto-reply burn and intent-handoff. The shipped simulator "tests" these but always returns True, so this is pure uncovered surface. Scripted ladders, no LLM needed. |
| **6** | **§4.2 determinism + §4.3 anti-repetition + §4.4 suppression** | 2 | −2 per repeat, and determinism is the precondition that makes every other check trustworthy. Cheap once the runner exists. |
| **7** | **§5 full-rubric LLM judge with fail-loud parsing** | 4 | Converts everything above into a number we can trend, and adds rationale-consistency (an undefended scoring surface). Deliberately *after* the mechanical checks: mechanical checks are free, repeatable, and catch the failures that tank the LLM score anyway. |
| **8** | **Remaining fixtures A03/A04/A05/A08/A10/A11/A12/A13 + R04** | 3 | Long-tail robustness and language match. Individually small, collectively they're the difference between a 7 and a 9 on merchant fit. |
| **9** | **Holdout sealing + ledger (§6) + H08 soak** | 2 | Prevents the overfitting the shipped simulator invites, and the 60-minute soak is the only test that catches state/memory/rate problems that appear only at full duration. Do this once the bot is roughly good — sealing an empty bot wastes holdout runs. |

Rule of thumb encoded above: **build every deterministic check before the LLM judge.**
The mechanical checks are free to run, stable across runs, and catch exactly the failures
(hallucination, malformed, repeat, wrong `send_as`, stale facts) that the real judge
punishes hardest. The LLM judge is for the last mile of copy quality.
