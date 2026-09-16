# ARCHITECT-S — Score-Maximizing / Operations-First Architecture

**Stance**: The published scoring function is the specification. Optimize against it explicitly and
legitimately — no judge prompt-injection, no parser-bug exploitation, no plagiarism of the case
studies. Every point claimed here is a point the bot genuinely earns.

**Thesis in one paragraph**: My two opponents are arguing about the composer. The composer is at
most 48% of the achievable score, it is the most expensive surface to improve, and its marginal
returns are logarithmic. Total achievable = per-message rubric (mean 0–50) + adaptation bonus (+25)
+ replay (+30, top-10 only) − operational penalties (up to −20). That's a 105-point ceiling with a
20-point sink, and **55 of those 105 points plus the entire 20-point sink live outside the copy**.
Reliability, restraint, rationale fidelity, correct `send_as`, suppression hygiene and *provable*
adaptation are where the marginal point is cheapest — by roughly 3–5× on a points-per-hour basis.

---

## 0. Assumptions, stated up front

These are load-bearing. If one is wrong, say so in cross-examination and I will re-derive.

| # | Assumption | Basis | Consequence if wrong |
|---|---|---|---|
| A1 | Phase 2 rubric is aggregated as a **mean across scored actions**, not a sum | `judge_simulator.py:_final_summary` averages per-dimension with `// n`; testing-brief §4 Phase 5 says "aggregates" without a formula; §13 promises a "per-message scorecard" and a single "aggregated score" | If it's a sum, restraint is costly. §2 shows the hedge; the loss is bounded at ~4 points. |
| A2 | The binding latency constraint is **not** the 30 s in testing-brief §5, but the reference client's timeouts: tick 15 s, reply 15 s, context 10 s, healthz 5 s (`judge_simulator.py:413–430`), and the api-call-examples "latency budget" table (tick 10 s, reply 10 s, healthz 2 s) | Two independent documents both state something tighter than 30 s | Designing to 8 s is never wrong; designing to 30 s can be fatal. Asymmetric — always take the tight number. |
| A3 | Phase 2 spawns the merchant-reply sub-LLM loop for **every** emitted action (up to 5 turns), per testing-brief §4 Phase 2 step 4 | Explicit in the brief | Conversation-handling quality is scored in Phase 2, not only Phase 4. This is central to §6. |
| A4 | Real-time window is 30–45 min for 12 simulated ticks → **~2.5–3.75 min of wall clock per tick**, judge rate limit 10 rps | testing-brief §4, §5 | Sets a hard throughput ceiling on conversations (§2). |
| A5 | The official judge sees the full dataset, but its per-action prompt window is narrower than the pushed context (`judge_simulator.py:504–530` shows only category slug/voice/first-5-taboos, merchant identity/performance/signals/**active offers only**, trigger kind/payload/urgency, customer identity) | Reference simulator | Drives "fact tiering" in §3.2. If the official judge sees everything, fact tiering costs nothing — it is still a free hedge. |
| A6 | Operational penalties are per-event and cumulative to a −20 floor (−10 healthz offline, −1/timeout, −2/malformed, −2/repeat, −3/URL) | testing-brief §10, api-call-examples F.1–F.5 | With ~200 judged interactions, even a 2% defect rate burns 40% of the penalty budget. Justifies fail-closed. |
| A7 | Every merchant context carries `performance` and every category carries `peer_stats`/`digest` (100% presence), while **75% of triggers carry a placeholder payload** and 86% of merchants have zero offers/history/signals | data-dictionary §1, §6 | The trigger is usually *not* the source of facts. Merchant performance + category knowledge must be. |

---

## 1. A written model of the score

### 1.1 Enumerated point sources and sinks

**SOURCES**

| ID | Source | Max | Realistic range for a competent bot | Notes |
|---|---|---|---|---|
| S1 | Specificity (0–10, mean) | 10 | 5 → 9.5 | Driven almost entirely by count of provenanced hard facts. Empirically: 1 fact → 8, 3+ facts → 10 (scored-examples §2). Lowest-scoring case in the whole pack (44/50) is the one with one soft anchor. |
| S2 | Category fit (0–10) | 10 | 6 → 9.5 | Voice tokens + taboo avoidance + register-by-scope + emoji discipline. Deterministic to a large extent. |
| S3 | Merchant fit (0–10) | 10 | 5 → 9.5 | Owner first name (generic "Hi" = −1), a merchant-specific derived number, language-pref honoring (wrong = −2 on customer-facing). |
| S4 | Decision quality / trigger relevance (0–10) | 10 | 6 → 10 | Name the trigger explicitly as the why-now. Judge parser accepts `decision_quality` or `trigger_relevance` for the same slot (`judge_simulator.py:555`). |
| S5 | Engagement compulsion (0–10) | 10 | 5 → 9 | Single binary low-friction CTA + quantified effort/risk bound + reciprocity. Ceiling is 9 unless every merchant-specific claim is provenance-checkable (scored-examples §2 pattern). |
| S6 | Adaptation bonus | **+25** | 0 → 25 | +5 per dimension for incorporating post-submission context. Binary-ish in practice: you either detect the version bump and cite the new fact or you don't. |
| S7 | Replay (top 10 only) | **+30** | 0 → 30 | Three scenarios: auto-reply hell, intent transition, hostile/off-topic. Scored "on conversation flow only". |

Rubric subtotal 50; grand total 105.

**SINKS**

| ID | Sink | Cost | Exposure |
|---|---|---|---|
| P1 | healthz offline (3 consecutive failures) | **−10 + disqualified for the slot** | Catastrophic. Also fails the 255-context warmup gate → no score at all. |
| P2 | `/v1/tick` timeout | −1 each | 12 ticks → up to −12 |
| P3 | `/v1/reply` timeout | −1 each | ~200 turns → unbounded until the −20 floor |
| P4 | Malformed JSON / missing required field / empty body | −2 each, action scored 0 | ~50 actions → up to −20 on its own |
| P5 | Verbatim repeat in a conversation | −2 each | Highest with templated composers |
| P6 | URL in body | −3 each | Meta-policy hard fail. Note: challenge-brief §5 constraint 4 says URLs are *allowed*; api-call-examples F.4 says −3 each. **Conflict resolved conservatively: never emit a URL.** Cost of compliance is zero; cost of being wrong is −3/action. |

Penalty floor −20. Practical read: **P1 is existential, P4 is the biggest recurring drain, and P2/P3 are the ones that scale with your own ambition.**

### 1.2 Interventions ranked by points per hour

Estimates assume one engineer, and "Δ" is expected marginal score against a baseline that is the
reference skeleton in testing-brief §7 plus a single competent LLM composer prompt.

| Rank | Intervention | Hours | Δ points (expected) | pts/hr | Rationale |
|---|---|---:|---:|---:|---|
| 1 | **Zero-defect egress**: one `emit_action()` serializer, required-field validation, fail-closed drop, top-level try/except returning `{"actions":[]}` | 4 | +12 | **3.0** | Converts every would-be −2 into a 0. At a plausible 5% defect rate over 50 actions that's 5 malformeds = −10, plus removes tail risk of a 500 cascading into healthz. |
| 2 | **Replay/conversation handlers** (auto-reply, intent transition, hostile, off-topic redirect) | 5 | +14 | **2.8** | +30 × P(top-10) ≈ +18 at P≈0.6, *plus* it directly scores in Phase 2 (A3) where ~150 of ~200 judged turns are replies, not first sends. This is the intervention most under-weighted by both opponents. |
| 3 | **Healthz + warmup + crash-safe state + deployment discipline** | 5 | +13 | **2.6** | Avoids P1. Expected value = P(warmup failure without this work) × (entire score). I estimate 25–40% of entrants fail warmup or a healthz poll (sleeping free-tier dynos, multi-replica state split, healthz that touches the LLM). |
| 4 | **Adaptation engine** (version diff → new-fact queue → forced citation → rationale that names the version bump) | 8 | +20 | **2.5** | Of the +25 available. Most entrants will store the new version and never notice it changed. |
| 5 | **Restraint + suppression + per-merchant budget** | 3 | +7 | **2.3** | Under A1 this protects the mean directly; under sum-aggregation it is roughly neutral (see §2.4). Also removes P5 exposure entirely. |
| 6 | **send_as / language-pref / consent correctness** | 2 | +4.5 | **2.25** | Wrong `send_as` on the 5 mid-test customer contexts is a visible, categorical miss. Wrong language on a `hi` merchant is a named anti-pattern; scored-examples calls uniform customer treatment the single largest named penalty (−2 on customer fit). |
| 7 | **Grounding verifier** (every number/date/proper-noun traceable to a pushed field) | 5 | +8 | **1.6** | "Bots that hallucinate score lowest." Lifts S1 and S3 by ~2 each and removes the fabrication cap. |
| 8 | **Rationale generator + body-consistency check** | 2 | +3 | **1.5** | Judge cross-checks; mismatch = penalty; good rationales buy generous edge-case reads. Nearly everyone stubs this. |
| 9 | **Composer copy quality beyond the mechanical rules** (prompt engineering, few-shot, per-kind variants, judgment/contrarian moves) | 15 | +9 | **0.6** | This is the thing both opponents want to spend all their time on. It is genuinely the lowest-yield hour in the project *after* the mechanical rules in §3.1 are in place. |

**Read the table.** Items 1–8 total 34 hours for ~+81 expected points. Item 9 alone is 15 hours for
+9. That is the whole argument. I am not saying copy doesn't matter — I am saying the first ~6 hours
of copy work (the mechanical rules) captures most of it, and hours 7–21 of copy work are the most
expensive points on the board.

---

## 2. The restraint policy

### 2.1 The decision rule

For each candidate (merchant, trigger, customer?) at tick *t*, compute a predicted rubric score
`p̂ ∈ [0,50]` from deterministic features available **before** composing. Send iff:

```
SEND  ⟺  p̂ ≥ Θ
       ∧ F_A ≥ 2                        (≥2 judge-visible "Tier-A" facts, §3.2)
       ∧ F_total ≥ 3                    (≥3 provenanced facts total)
       ∧ grounding_verifier(body) == PASS
       ∧ suppression_key ∉ used_keys
       ∧ merchant ∉ opted_out
       ∧ merchant_sends_this_tick == 0
       ∧ merchant_conversations_total < 2
       ∧ tick_action_count < B_t
```

with `Θ = 42` and `B_t = 4` (see §2.3, §2.4 for the derivation of both).

Under mean-aggregation the theoretically correct rule is **send iff p̂ > current running mean**.
That is self-referential and unstable early in the run, so I fix Θ at 42 — which is the observed
mean of the scored-example pack's *worst* cases (44, 47, 48) minus a safety margin, i.e. the level
below which a message is measurably dragging the average down.

### 2.2 `p̂` — the predicted-score model (deterministic, no LLM)

Grounded directly in the scored-example deltas:

```
p̂ = 30                                          # floor for a well-formed, on-voice, on-trigger send
   + 4  if F_total ≥ 3                           # the single strongest observed correlate
   + 2  if F_total ≥ 4
   + 2  if trigger.payload is NOT placeholder     # 25% of triggers
   + 2  if a derived/computed number is available # "22 of your 240", "196 days to"
   + 2  if merchant has ≥1 active offer OR category offer_catalog match is exact
   + 2  if a category-voice vocab token is applicable
   + 2  if the merchant has non-empty signals / review_themes / conversation_history
   + 1  if urgency ≥ 3
   + 1  if customer-facing AND language_pref is explicit
   − 4  if the only available facts are generic performance scalars already used this run
   − 6  if the trigger is a placeholder-payload low-urgency kind AND the merchant is "thin"
```

Calibration sanity check against the pack: Case 1 (rich digest + customer_aggregate + citation)
→ 30+4+2+2+2+2+2+2 = 46 → send. Case 4 (curious_ask, one soft anchor, thin) → 30+2+2 = 34 → **would
not send under Θ=42**, and Case 4 is indeed the lowest-scored case in the pack at 44/50. The model is
intentionally pessimistic; it rejects the real 44 as well as would-be 30s. Under mean-aggregation
rejecting a 44 when your mean is 46 is correct.

The dominant real-world driver is A7: with 75% placeholder payloads and 86% of merchants having
empty offers/signals/history, a large fraction of (trigger, merchant) pairs genuinely cannot clear
F_total ≥ 3 from trigger data alone. They clear it from **merchant performance (always present) +
category peer_stats (always present) + category digest/seasonal_beats (always present)**. So the
gate is passable almost everywhere — but it forces the composer to go get real facts rather than
paraphrase a placeholder trigger back at the merchant. That is the restraint gate's actual job.

### 2.3 How many sends per tick — the throughput derivation

This is not a taste question; it's a capacity question, and it is the part both opponents skip.

- 12 ticks over 30–45 min wall clock → **150–225 s of real time per tick** (A4).
- Every emitted action spawns a judge-side merchant-reply loop of up to **5 turns** (A3). Each turn
  is a `/v1/reply` call I must answer inside ~8 s (A2).
- Judge rate limit is 10 rps, but the judge is also calling an LLM to play the merchant, so real
  reply arrival is far slower — call it one reply round-trip per conversation per ~20–30 s.
- With `B_t = 4` sends/tick: 48 conversations × ~4 turns ≈ **192 reply calls** over the window ≈
  **4–6 replies/min sustained**, with bursts. Comfortable at 2 s/reply, tight at 6 s/reply.
- With `B_t = 20` (the cap): 240 conversations × 4 turns ≈ 960 reply calls in the same window ≈
  **21–32 replies/min**. At a 2 s reply path that is 1 s of headroom per call with zero burst
  tolerance, and at any LLM in the reply path it is a guaranteed timeout cascade (P3 at −1 each,
  hitting the −20 floor inside three ticks).

**Therefore `B_t = 4`, global soft cap ~48 conversations, hard cap 6 in any single tick.** Not
because restraint is virtuous, but because 20 is not physically serviceable and the overflow is
paid in −1s.

Per-merchant: **1 action per merchant per tick** (FAQ mandates ≤1 per `(merchant_id,
conversation_id)` per tick anyway) and **≤2 conversations per merchant across the whole run**. With
50 merchants that is a 100-conversation ceiling; I use ~48 of it, which also spreads coverage across
all 5 categories and both scopes — important for the mean, since the judge scores category fit
against 5 different voices and I want none of them systematically weak.

### 2.4 Quantifying the unsent-message tradeoff

Let `m` = running mean, `n` = messages sent so far, `p̂` = predicted score of a candidate.

- **Under mean-aggregation (A1)**: sending changes the mean by `(p̂ − m)/(n+1)`. At m=46, n=30, a
  p̂=34 send costs −0.39 points of final rubric score. Sending ten such costs ~−3.4. An unsent
  message costs exactly 0. Restraint strictly dominates for any `p̂ < m`.
- **Under sum-aggregation (A1 false)**: an unsent message costs `p̂` — so restraint looks expensive.
  But the loss is bounded by throughput, not by policy: I can serve at most ~50–60 conversations
  regardless (§2.3). Going from Θ=42 to Θ=0 would add maybe 8–12 extra sends before hitting the
  capacity wall, at an average ~34/50 each, **while adding ~40 extra reply turns** that push me into
  P3 timeout territory. Net expected gain ≈ +4 points, net expected penalty risk ≈ −6 to −12.
- **Asymmetry is the whole argument**: restraint costs at most ~4 points if I'm wrong about A1, and
  saves 5–10 points plus the entire P3/P5 exposure if I'm right. Take the hedge.

The one place I deliberately *break* restraint: a merchant whose context just version-bumped with
an uncited new fact (§5). That send is worth up to +25 of adaptation bonus, which dominates any
plausible rubric-mean cost. Adaptation candidates bypass Θ and get priority over urgency ranking.

---

## 3. Rationale engineering

The FAQ: *"it's included in the scoring rubric ('did the rationale match the actual output?').
High-quality rationales help the judge interpret edge cases generously."* Cross-case pattern #9:
*"judge cross-checks rationale against the message; mismatch = penalty."*

Two distinct jobs: (a) **don't contradict the body**, (b) **give the judge the evidence it needs to
score each dimension high without having to infer it.** (b) is the underused one. The rationale is
the only free-text channel where I can say "this number came from `performance.views`" — which is
exactly what the judge is otherwise guessing at when it decides whether a claim is fabricated.

### 3.1 The rationale is generated from the fact ledger, not by the LLM

The composer does not write the rationale prose freely. The pipeline is:

1. **Fact selection happens first.** The planner picks 3–4 facts and records a `FactLedger`:
   `[{token: "2,410 views", path: "merchant.performance.views", tier: "A"},
     {token: "3.0% peer CTR", path: "category.peer_stats.avg_ctr", tier: "B"}, ...]`
2. The composer is told to use exactly these facts.
3. The **grounding verifier** re-reads the emitted body, extracts every number, date, price,
   proper noun and source string, and requires each to match a ledger entry (exact or
   format-normalized: `0.021 → "2.1%"`, `2410 → "2,410"`). Any unmatched token → regenerate once →
   then fall to the deterministic template path. This is fail-closed.
4. The **rationale is assembled from the verified ledger** by a deterministic template:

```
"{trigger_kind} fired for {merchant_short} (urgency {u}); why-now stated explicitly in line 1.
 Facts used: {views} (merchant.performance.views, 30d), {ctr} vs {peer_ctr}
 (category.peer_stats.avg_ctr, {peer_scope}), {digest_title} ({digest_source}).
 Voice: {tone}/{register} per category.voice; taboo list checked ({n} terms).
 Language: {lang_decision} per identity.languages={langs}.
 send_as={send_as} because scope={scope}. CTA={cta} — single binary ask, effort bounded at {effort}.
 Suppression: {key}. Not sent to {n_suppressed} other candidates this tick (below fact floor)."
```

This guarantees rationale/body consistency **by construction** — the rationale can only cite facts
the verifier already confirmed are in the body. It cannot drift, because it isn't independently
generated.

5. **Final consistency assertion** before emit: every `{token}` named in the rationale must appear
   (normalized) in the body, and `send_as`/`cta`/`suppression_key` in the rationale must equal the
   action's actual fields. Mismatch → drop the action rather than emit an inconsistent pair.

The last clause of the template — naming what was *not* sent — is the restraint policy made legible
to the judge. It converts an invisible decision into visible evidence of judgment, which is
precisely what the "decision quality" dimension is asking about.

### 3.2 Fact tiering (A5)

The judge's per-action prompt window (reference implementation) contains: category slug, voice tone,
first 5 taboos; merchant name, owner, locality, languages, views/calls/ctr, signals, **active offers
only**; trigger kind, payload, urgency; customer identity. It does **not** contain `peer_stats`,
`digest`, `seasonal_beats`, `customer_aggregate`, or expired offers.

- **Tier-A facts** = present in that window. Directly checkable by the judge as non-fabricated.
- **Tier-B facts** = in pushed context but outside the window (digest items, peer stats, aggregates).

Rule: **≥2 Tier-A facts per message**, Tier-B facts allowed and encouraged as the third/fourth but
never as the only evidence. Corollary rule: **never cite an expired/inactive offer** — it is real
merchant data, but `judge_simulator.py:517` filters it out of the judge's view, so citing it reads
as fabrication. That's a legitimate, non-exploitative adaptation: I am choosing, among equally true
facts, the ones the grader can verify. The rationale names the field path for Tier-B facts precisely
so the judge can extend the same benefit of the doubt.

---

## 4. Operational hardening

### 4.1 Healthz — the 255-context warmup gate

```
GET /v1/healthz  →  {"status":"ok","uptime_seconds":N,
                     "contexts_loaded":{"category":5,"merchant":50,"customer":200,"trigger":0}}
```

Non-negotiable properties:

1. **Zero dependencies.** No LLM call, no disk read, no lock acquisition, no iteration over the
   context map. Counts are maintained as four atomic integers updated on accept. Target p99 < 5 ms
   against a 5 s (possibly 2 s) client timeout.
2. **All four keys always present**, including `trigger: 0` pre-window. The warmup gate checks
   `contexts_loaded` reflects all 255 base contexts; a missing key or a key that only appears once
   non-zero is a plausible failure mode.
3. **Counts are of distinct `context_id` per scope**, not of pushes. Re-pushes and version bumps
   must not inflate them past 50/200/5.
4. **Returns 200 under every degradation mode.** If the LLM provider is down, if the circuit breaker
   is open, if a worker thread died — healthz still says ok, because healthz failure is −10 and
   disqualification while a degraded composer is at worst a few rubric points.
5. Served by the same process that holds the state (single replica — see 4.7), so the count is
   always the truth about what that process can actually compose from.

### 4.2 `/v1/context` — idempotent, versioned, fast, crash-safe

- Store: `(scope, context_id) → {version, payload, received_at, prev_payload, diff}`.
- **Higher version** → replace atomically, compute diff (§5), `{"accepted": true, ...}`.
- **Equal version** → **`accepted: true`, no-op.** This is a deliberate call. The spec says "re-posting
  the same version is a no-op" (testing-brief §2.1) and separately shows a 409 with
  `accepted: false` for "you already have a higher version". The reference warmup gate scores a push
  PASS iff `accepted` is truthy (`judge_simulator.py:643`). Returning `accepted:false` on an
  identical re-push would manufacture a warmup FAIL out of correct idempotent behavior. So:
  equal → `accepted:true` (idempotent ack); **strictly lower → `accepted:false, reason:"stale_version",
  current_version:N` with HTTP 200**, not 409, because a non-2xx on a retry path is exactly the kind
  of thing that gets counted as an operational failure by a harness I can't inspect.
- **Handler does no work.** Validate, store, increment counter, ack — target p99 < 30 ms against a
  10 s budget. 255 pushes at 10 rps takes ≥25.5 s of wall clock; any per-push LLM precompute inside
  the handler blows the budget on the first call.
- **Precompute is enqueued, not inline.** A bounded background worker pool (4 threads) builds the
  per-merchant "angle bank" — resolved category voice tokens, taboo set, peer-stat comparisons,
  candidate fact ledger, candidate offers, language decision — during the 60 s settle and the
  T-15 min warmup window. By T0 every merchant has a warm plan.
- **Crash-safe**: every accepted push is appended to `state.jsonl` (fsync batched every 250 ms)
  before the ack. On boot, rehydrate in < 2 s. A supervisor-restarted process therefore comes back
  with correct `contexts_loaded` and does not fail the next healthz poll. This is the single highest-
  leverage 45 minutes of work in the whole build: it converts "process died" from a −10-and-
  disqualified into a two-second blip.

### 4.3 Deadline budgets

Derived from A2, with the tightest published number taken as binding:

| Endpoint | Client timeout (tightest published) | My internal deadline | Hard abort |
|---|---|---|---|
| `/v1/healthz` | 2 s | 5 ms | n/a |
| `/v1/metadata` | 2 s | 5 ms (static dict) | n/a |
| `/v1/context` | 5 s | 30 ms | 500 ms |
| `/v1/tick` | 10 s | **6 s** | 8 s |
| `/v1/reply` | 10 s | **4 s** | 6 s |

Inside `/v1/tick` (6 s budget):
- 0–200 ms: candidate enumeration, suppression filter, `p̂` scoring, ranking, truncate to `B_t`.
- 200 ms–4.5 s: compose up to 4 actions **in parallel**, each with its own 3.5 s per-call deadline
  and a single retry only if the first attempt returns fast (< 1.5 s).
- 4.5–5.5 s: grounding verify, rationale assemble, consistency assert, egress validate.
- 5.5 s: **deadline guillotine** — whatever is verified goes out; whatever isn't is dropped. Never
  extended, never awaited.

Never 20 sequential LLM calls. Never an unbounded `await`. Every outbound LLM call carries an
explicit socket + total timeout and is wrapped in the breaker.

### 4.4 Circuit breaker and graceful degradation

Three tiers, and the bot must always be able to reach tier 3:

- **Tier 1 — LLM composer** (temperature 0, seeded). Normal path.
- **Tier 2 — LLM composer, reduced** (shorter prompt, no few-shot, 2 s deadline). Entered when p95
  latency > 3 s over the last 10 calls.
- **Tier 3 — deterministic slot-fill templates** from the precomputed angle bank. Per (category ×
  trigger-family × scope) — roughly 5 × 8 × 2 = 80 template variants, each with 3 paraphrase
  variants to defeat cross-conversation sameness. **Guaranteed to contain the ledger facts, pass the
  verifier, and never emit a URL or taboo term.**

Breaker: 3 consecutive failures OR 5 failures in 60 s OR p95 > 6 s → **open for 60 s**, all traffic
to tier 3. Half-open probes with a single request. Independent breakers per endpoint class so a
slow `/tick` composer never starves the `/reply` path.

The reply path is deliberately **tier-3-first**: a deterministic classifier (auto-reply /
opt-out-hostile / explicit-intent / question / off-topic / neutral) selects the action
(`send|wait|end`) and a template, and the LLM is only invoked to phrase a `send` when there is
budget. Reply correctness is scored on *flow* (did you end, did you switch to action mode), which is
a classification problem, not a generation problem.

### 4.5 Zero-malformed-response guarantee

One egress function. Nothing else is allowed to construct an action.

```
emit_action(a) → Optional[action]
  require all of: conversation_id, merchant_id, send_as, trigger_id, body, cta,
                  suppression_key, rationale        # api-call-examples F.2 list
  require body non-empty after strip, ≥ 40 chars, ≤ 900 chars
  require no URL   (regex: https?://, www., bare TLD patterns)   # F.4, −3 each
  require no taboo term from category.voice.vocab_taboo (FULL list, not the judge's first 5)
  require send_as == ("merchant_on_behalf" if customer_id else "vera")
  require conversation_id unused this run           # tick must not reuse an existing conv
  require body ∉ bodies_sent[conversation_id]       # F.5 anti-repetition, −2 each
  require normalized body ∉ case_study_bodies       # plagiarism similarity check
  require every numeric/date/proper-noun token ∈ FactLedger
  require rationale tokens ⊆ body tokens ∪ field paths
  on ANY failure → return None (DROP)
```

**Dropping beats emitting.** A dropped action scores 0. A malformed one scores 0 *and* costs −2 *and*
pollutes the mean. There is no scenario where emitting an action that failed validation is correct.

Above that: the tick handler is wrapped in `try/except → {"actions": []}` and the reply handler in
`try/except → {"action":"wait","wait_seconds":1800,"rationale":"..."}`. The process must never return
a 500 and must never return a non-JSON body. Schema-validate my own response against the contract
before writing it to the socket.

### 4.6 Anti-repetition and suppression taxonomy

Suppression keys are `topic:scope:period`, echoing the pack's own examples
(`research:dentists:2026-W17`, `recall:c_001_priya_for_m001:6mo`):

| Family | Key shape | Period |
|---|---|---|
| Category knowledge (research_digest, cde, regulation) | `research:{category}:{iso_week}` | week |
| Performance (perf_dip/spike, milestone, seasonal_perf_dip) | `perf:{merchant_id}:{metric}:{iso_week}` | week |
| Lifecycle (renewal, winback, gbp_unverified) | `lifecycle:{merchant_id}:{kind}` | run |
| Customer recall/refill/appointment | `recall:{customer_id}:{cycle}` | cycle |
| Relationship (curious_ask, dormant) | `ask:{merchant_id}:{iso_week}` | week |
| External event (festival, IPL, competitor, supply) | `event:{event_key}:{date}` | date |

Prefer the trigger's own `suppression_key` when it is informative; the generated ones
(`{kind}:{merchant}:gen_N`) are not, so I substitute my own taxonomy key for those and record both.
Anti-repetition is enforced at two levels: exact-body set per `conversation_id` (the scored rule)
and a 5-gram Jaccard similarity ≥ 0.8 check against everything sent to that *merchant*, which is
stricter than the rule but protects against a templated composer reading as spam to the merchant-
playing sub-LLM (which then replies with hostility, which then costs me flow points).

### 4.7 Deployment topology and cold-start avoidance

- **Single always-on process, single replica.** State is in-process; a second replica splits the
  context store and makes `contexts_loaded` wrong on ~half of healthz polls. Explicitly disable
  autoscaling, scale-to-zero, and rolling deploys during the window.
- Paid always-on tier (Fly machine with `min_machines_running=1`, or equivalent). **Never a free
  tier that sleeps** — a 15–30 s cold start on the first healthz is three failed polls away from
  −10 and disqualification.
- Region chosen for lowest RTT to the LLM provider, not to the judge — my p99 is dominated by the
  composer round trip, not by the judge's.
- **T-90 min**: deploy final build. **T-75**: run the full local harness against the public URL
  (`full_evaluation` scenario, not the default `all` — note `judge_simulator.py:785–799`, the
  default scenario never invokes the LLM judge at all, so a team self-testing on defaults has never
  exercised the rubric). **T-60**: freeze. No deploys after T-60 under any circumstance.
- **Warm everything at boot**: LLM HTTP connection pool opened and one throwaway completion issued,
  DNS pre-resolved, TLS sessions established, JSON codecs warmed, templates compiled, first-request
  JIT/import cost paid before the first healthz.
- A **self-poll** thread hits `/v1/healthz` every 20 s and logs; a supervisor (`restart: always`)
  plus the `state.jsonl` rehydration (4.2) means the worst-case process death costs one poll, not
  three.
- Also handle `POST /v1/teardown` (optional per §11) idempotently — accept, wipe, return 200.

---

## 5. The adaptation play (+25, the cheapest large block on the board)

Phase 3 injects, interleaved with Phase 2: 5 new digest items per category as a new category
`version`; new performance snapshots for 10 merchants; 15 new triggers; and — **scripted** — for 5
specific merchants, a new `customer` context followed by a `recall_due` trigger **2 minutes later**.

Most entrants will store the higher version, overwrite, and never know anything changed. That is a
forfeit of up to 25 points.

### 5.1 Detection and diff

On every accepted push where `version > stored.version`:

1. Structural diff at JSON-pointer granularity → `{added[], changed[], removed[]}`.
2. **Semantic fact extraction** by scope:
   - `category`: new `digest[]` entries by `id` (set difference) → each yields
     `{title, source, summary, kind, deadline?}`. Also new `trend_signals`, changed `peer_stats`.
   - `merchant`: changed scalars under `performance` → each yields the **pair**
     `{path, old, new, delta_pct}` — the delta is itself a new derivable fact and it *proves* I held
     both versions.
   - `customer`: an entirely new customer id → flagged as a Phase-3 scripted-scenario candidate.
   - `trigger`: new trigger ids arriving mid-window.
3. Append to a per-merchant **`freshness_queue`**: `{fact, source_path, from_version, to_version,
   first_seen_tick, cited: false, expires: +3 ticks}`.

### 5.2 Scheduling — adaptation outranks urgency

The candidate ranker uses a lexicographic key: `(has_uncited_fresh_fact, urgency, p̂)`. Any merchant
with an uncited fresh fact sorts above everything else and **bypasses Θ**. Rationale: the marginal
adaptation point is worth up to 5× the marginal rubric point, and the window is short (the judge
must see the citation in a *subsequent* send, so a fact left uncited for 3 ticks is probably lost).

For a category-level bump, 5 new digest items × 10 merchants per category is far more candidates
than my budget; I pick the **1–2 merchants per category whose `signals`/`customer_aggregate` best
match the new item's `patient_segment`/`kind`**, which is also the highest-scoring composition
(Case 1's 10/10 merchant fit came from exactly this match).

### 5.3 Provable citation

The new fact is not a suggestion to the composer; it is a **hard post-condition**:

- The composer is given the fresh fact as a mandatory ledger entry.
- The verifier requires a literal (normalized) token from it in the body — the new digest title's
  distinctive keyword, the new numeric value, the source string, or the computed delta.
- Fail → regenerate once → fail again → **deterministic freshness template**, which is constructed
  from the fact and therefore cannot fail the check:

  > "{Owner}, update from this morning: {new_fact_title} ({source}). For your {matched_segment},
  > that's {implication}. Want me to {bounded_effort_ask}?"

- The rationale then states the adaptation explicitly and checkably:

  > "category:dentists bumped v1→v2 at 10:50Z; new compliance item `d_2026W17_dci_radiograph_NEW`
  > (DCI circular 2026-11-04) was not present in v1 and has not been cited in any prior send this
  > run. Merchant matched on `signals=[...]`. Prior send on this merchant cited the v1 fluoride item;
  > this send supersedes it."

  For a merchant perf bump: *"merchant m_001 v1→v2: `performance.views` 2410→2580 (+7.1%). Message
  cites the delta, which is only derivable from holding both versions."* Citing a **delta** is the
  strongest possible proof of adaptation — a bot that only stored v2 cannot produce it.

### 5.4 The scripted 5-merchant customer scenario

New `customer` context, then `recall_due` trigger ~2 min later. Dedicated path:

1. On a mid-test *new* customer context: immediately (in the background worker) pre-compose a
   customer-facing draft — `send_as: merchant_on_behalf`, language from
   `identity.language_pref`, state-appropriate register per `state`, consent-scope checked, slots/
   offer pulled from the merchant's **active** offers — and park it.
2. On the matching customer-scoped trigger: emit in the **same tick**, no additional composition
   latency, with `conversation_id` shaped `conv_{customer}_{kind}_{yyyy_mm}` per the pack's
   "legible conversation_id" pattern.
3. Guard: if `consent.scope` is empty or `phone_redacted` is null (the walk-in case exists in the
   data), **do not send** and log the restraint in the next rationale. Messaging a customer who
   cannot legally be messaged is the kind of thing a judge notices once and remembers.

---

## 6. The top-10 gate (making the +30 reachable)

Ranking into Phase 4 is on Phase 2 score. Under A1 (mean), the top-10 gate is about **floor, not
ceiling** — one timeout, one malformed action and one hallucinated stat drag a 46-mean bot below a
41-mean bot that never faults.

What I believe actually separates the top 10, in order:

1. **Survive warmup.** Sleeping free tiers, multi-replica state splits, healthz that awaits an LLM,
   and `contexts_loaded` that counts pushes instead of distinct ids. I estimate 25–40% of the field
   dies here or on a later healthz poll. Cost to me: the work in §4.1/§4.2/§4.7.
2. **Never time out.** The field will discover that 20 actions × one LLM call each does not fit in
   15 s. Cost to me: §4.3's guillotine and parallel composition.
3. **Zero malformed / zero repeats.** Templated composers with no anti-repetition set will bleed −2s.
   Cost to me: §4.5.
4. **Handle replies well in Phase 2.** This is the point both opponents miss (A3): ~75% of judged
   interactions in Phase 2 are `/v1/reply` turns, not first sends. A bot with a beautiful opener and
   a dumb reply loop gets scored on the dumb reply loop four times as often. My tier-3-first reply
   classifier (auto-reply → wait/end escalation; explicit intent → immediate action language with
   `actioning` verbs and no `qualifying` verbs; hostility → `end`; off-topic → decline + redirect) is
   the same code that Phase 4 scores, so it is paid for once and scored twice.
5. **≥3 provenanced facts, ≥2 Tier-A, every time.** This is the mechanical route to specificity ≈ 10
   and merchant fit ≈ 9–10 without any prompt artistry.
6. **Correct `send_as` and language on every customer-facing send** — a categorical, visible,
   binary miss the judge cannot overlook.
7. **A rationale that isn't a stub.** Free generosity on edge cases, per the FAQ.

Items 1–4 and 7 are pure ops/plumbing. That is my claim: **the top-10 gate is mostly an
engineering gate, and the +30 behind it is therefore an engineering prize.**

---

## 7. My three biggest weaknesses, stated plainly

### W1 — Rubric-optimized messages may be messages a real merchant would hate. Partly true.

A hard floor of 3 provenanced facts, a mandatory quantified effort bound, and a mandatory single
binary CTA will, applied mechanically across 48 messages, produce dashboard-speak: dense, numeric,
slightly interchangeable, and — at volume — faintly robotic. "Ramesh, your views are 2,410 (−5% w/w)
vs a 3.0% peer CTR; want me to draft X? 10 min." is a 46/50 message and a mildly annoying WhatsApp.
The rubric rewards fact density; a real merchant rewards *relevance and brevity*, and those diverge
past about three facts.

There is a second, sharper version of this: the highest-scoring case in the pack (Case 5, IPL) wins
precisely by **reasoning past** the trigger — advising the merchant *not* to run the obvious promo.
That is a judgment move, and judgment is the one thing my mechanical rules cannot manufacture.

**Mitigation**: (a) cap facts at 4 and require at least one sentence of plain implication language
that contains no number — the "so what" line; (b) keep an explicit **contrarian check** in the
planner: when `category.seasonal_beats` or `trend_signals` contradict the naive reading of the
trigger (gym April–June lull, Saturday IPL underperformance, expected seasonal dip), the composer is
instructed to lead with the reframe rather than the trigger — this is both the highest-scoring move
in the pack *and* the one a real merchant would actually thank you for, so the objectives align
exactly where it matters most; (c) sample 10 of my own outputs and read them as a merchant, not as
a judge, before freeze.

### W2 — My whole restraint policy rests on an unverified aggregation assumption (A1).

I inferred mean-aggregation from a reference simulator that the spec explicitly says may not be the
real grader. If Phase 2 sums, Θ=42 is leaving points on the table and I have no mid-test feedback
signal to detect it — the judge returns nothing I can observe.

**Mitigation**: the hedge is already priced in. `B_t = 4` is not the mean-optimal policy (which would
be closer to 1–2 very high-confidence sends per tick); it is deliberately set near the *throughput*
ceiling so that the sum-aggregation downside is bounded at roughly −4 (§2.4). I also make Θ a single
config constant and pre-compute a "Θ=36, B_t=6" variant that can be flipped at T-60 if any late
information (an organizer clarification, another team's report) resolves A1. After T-60 it is frozen
either way.

### W3 — Ops excellence is invisible if the copy is mediocre, and ~13 of my claimed hours are conditional.

Rank 2 in my table (+14 for replay handlers) is partly gated on reaching the top 10, which I cannot
reach on reliability alone. If my composer lands at 38/50 while an LLM-first team lands at 47/50,
they take the +30 and my ops work bought me a clean 38. Points-per-hour tables flatter the work you
already decided to do; mine is not immune.

**Mitigation**: (a) A3 substantially de-risks this — the conversation handlers score in Phase 2 too,
where ~150 of ~200 judged turns live, so their value is mostly *unconditional*; (b) I commit a real
floor of composer investment (the §3.1 fact-ledger pipeline plus the mechanical rules is ~6 hours and
empirically gets to ~44–46/50 based on the pack's own deltas), rather than treating copy as a
rounding error; (c) if forced to choose at the margin, I spend the last free hours on the
**contrarian/judgment check** in W1, because that is the single highest-scoring lever in the entire
example pack and it is a planner feature, not a prompt-artistry feature.

---

## 8. Two attacks I expect, and my rebuttals

### From the determinism-first architect

**D1: "Your own design concedes my case. Tier 3 is a template bank, your rationale is template-
assembled, your reply path is a classifier, your adaptation citation is a hard string check. The LLM
is the only component in your system that can hallucinate, time out, or drift — delete it and every
operational guarantee you just spent five sections building becomes free."**

Rebuttal: the deterministic path is my *floor*, not my ceiling, and the gap between floor and
ceiling is where the top 10 is decided. Concretely: 80 template variants across 50 merchants and 12
ticks produce visible sameness — my own 5-gram similarity guard (§4.6) would start rejecting my own
output, and the merchant-playing sub-LLM replies to formulaic outreach with disengagement or
hostility, which is scored. More decisively: **Case 4 (44/50) is what a good template produces, and
Case 5 (50/50) is what judgment produces.** That 6-point gap × ~48 messages is the entire margin.
Second: I do not carry the LLM's risk, because every LLM output passes a verifier that can only
*subtract* — an unverifiable output is dropped and the deterministic path fills in. The LLM is
strictly upside with a hard-bounded downside of latency, and latency is bounded by a 3.5 s deadline
inside a 6 s budget inside a 10 s timeout. The correct architecture isn't "LLM or templates", it's
**templates as the guaranteed floor and the LLM as an unreliable-but-verified enhancer**, which is
exactly what I've specified.

**D2: "Your adaptation play doesn't need a model at all — a JSON diff plus a slot-fill is provable,
deterministic and always cites the new fact. You're routing your single highest-value block through
your least reliable component."**

Rebuttal: I concede this, and it is already my design — §5.3's post-condition is a string check, and
the fallback is a deterministic freshness template that cannot fail it. The model only phrases the
implication sentence. If forced to choose, adaptation runs deterministic-only; it is the one block
where I'd take the voice hit for the guarantee.

### From the LLM-first architect

**L1: "Restraint is score suicide. The rubric is per-message. You are voluntarily declining ~15
messages worth ~40 points each to protect an average you inferred from a simulator the spec says
isn't the grader. Send 20 per tick like the cap allows and let the mean fall where it falls."**

Rebuttal: this is an arithmetic claim and it doesn't survive the arithmetic. The cap is 20 per tick
but the *serviceable* rate is not, because every action opens a conversation the judge drives for up
to 5 turns and I must answer each turn in under ~8 s (A2, A3). 20 actions/tick → ~960 reply calls in
a 30–45 minute wall-clock window → 21–32 replies/minute sustained with bursts (§2.3). That does not
fit, and what doesn't fit is paid at −1 per timeout against a −20 floor, reached inside three ticks,
*plus* the timed-out turns are scored as `bot_silent`. So the real choice isn't "48 vs 240
conversations", it's "48 clean conversations vs ~60 conversations with a penalty cascade". Under
sum-aggregation my policy costs about +4 of foregone score; under mean-aggregation yours costs 5–10
points of rubric plus the entire penalty budget. I'll take that asymmetry every time. And note what
I am *not* doing: I'm not sending 1 message per tick. Θ=42 with B_t=4 is a hedged policy precisely
because I take your objection seriously.

**L2: "Your grounding verifier is a creativity guillotine. The single best message in the entire
example pack — Case 5, the IPL contrarian — asserts '-12% restaurant covers on Saturday matches',
which is nowhere in that trigger's payload. Your verifier drops it, you regenerate, you fall to a
template, and you ship a 42 where a 50 was available. You have optimized your way to the mean."**

Rebuttal: the sharpest attack, and it lands on a real edge — but it misreads the verifier. The
verifier is a **provenance** checker, not a novelty blocker: a fact is admissible if it traces to
*any* pushed context field, and `category.seasonal_beats` / `trend_signals` / `peer_stats` are
exactly where a "Saturday matches underperform" beat lives (the data dictionary confirms restaurants
carry precisely that seasonal note). Case 5's fact is admissible under my rules and lands as a
Tier-B ledger entry with its field path named in the rationale — which is *better* than Case 5 as
shipped, because Case 6 and Case 3 each lost their tenth point specifically to "assumes data is in
MerchantContext or fabricates — judge will check". My verifier is the thing that recovers those
points, not the thing that costs them. What it does block is an *unsourced* number, and the brief is
unambiguous that unsourced numbers are the lowest-scoring failure mode there is. Where I'll concede
ground: the verifier makes the composer's job harder, tightens the prompt, and will occasionally
reject a good phrasing on a normalization miss (₹1,420 vs 1420, "38%" vs 0.38) — so the normalizer
is load-bearing and needs its own test suite, and the retry budget exists exactly for that case.

---

## 9. Build order (34 hours to the claimed +81)

1. **(4h)** Skeleton + healthz/metadata/context/tick/reply contracts + `emit_action()` fail-closed
   egress + top-level exception handlers. *Nothing else until this is airtight.*
2. **(3h)** Versioned store, idempotency semantics (§4.2), `state.jsonl` crash-safety, atomic counters.
3. **(3h)** Deployment: always-on paid tier, boot warm-up, self-poll, supervisor. Verify the 255-push
   warmup gate end-to-end against the public URL.
4. **(5h)** Reply classifier + the four conversation handlers (auto-reply escalation, intent
   transition, hostile exit, off-topic redirect). Test against `judge_simulator.py` scenarios
   individually — **not** the default `all`, which never calls the judge.
5. **(4h)** Precompute worker + angle bank + fact ledger + tier-A/B classification + `p̂` model +
   ranker + suppression taxonomy.
6. **(5h)** Grounding verifier + normalizer + its test suite; tier-3 template bank.
7. **(6h)** Adaptation engine: diff, freshness queue, priority bypass, forced citation, freshness
   templates, the scripted 5-merchant customer path.
8. **(2h)** Rationale assembler + consistency assertion.
9. **(2h)** Composer prompt + mechanical rules + contrarian check.
10. **(freeze at T-60)** Full-harness dry run, read 10 outputs as a merchant, flip Θ only if A1
    resolves.

---
---

# CROSS-EXAMINATION RESPONSE

I have read both opponent designs in full. Before the point-by-point: the three of us have
converged much further than the framing suggests. All three designs independently arrived at
a single stateful process, precompute at `/v1/context` time, a deterministic ranker with hard
gates, a fail-closed egress validator, a `topic:scope:period` suppression taxonomy, restraint
at 3–8 sends per tick, a reply policy (`send`/`wait`/`end`) decided by pure Python *before*
any model is consulted, and a deterministic template floor. The live disagreement is narrow:
**who writes the body, and what that is worth.** I am going to argue that narrow question
honestly, and concede a good deal on the way.

---

## 1. CONCEDED

### C1 — My fact-tiering rule is wrong as a requirement, and I can show you exactly how wrong.

The moderator confirmed the mechanism. I will now refute my own conclusion with the strongest
evidence available, which is the brief's own gold standard.

Case 1 / Appendix A, scored 50/50, is the challenge authors' own exemplar. Its facts:

| Token | Source | In the simulator's judge window? |
|---|---|---|
| "Dr. Meera" | `identity.owner_first_name` | **Tier-A** |
| "your high-risk adult patients" | `customer_aggregate.high_risk_adult_count` (also echoed by `signals:["high_risk_adult_cohort"]`) | Tier-B by value; Tier-A only as an unquantified phrase |
| "2,100-patient trial" | `category.digest[].trial_n` | **Tier-B** |
| "38% better" | `category.digest[].title` | **Tier-B** |
| "JIDA Oct 2026 p.14" | `category.digest[].source` | **Tier-B** |

**Numeric Tier-A facts in the highest-scoring message in the entire package: zero.** My rule,
as written in §3.2 and paired with the ≥3-fact floor, would have rejected Appendix A and
forced a regeneration that stuffed in `views`/`ctr` — which is a strictly worse message. That
is not a marginal miscalibration; it is a rule that inverts the target.

And to the sharper charge — *is this the same error I refused elsewhere?* Partly yes, and the
distinction I drew was too flattering to myself. I refused parser exploits on the grounds
that the simulator "is not necessarily the exact grading harness." Tier-A rests on exactly the
same evidentiary base, and challenge-brief §16 says plainly that the real judge session
receives the full brief, the full base dataset, the injections, and the rubric. A judge with
the dataset can verify a digest citation as easily as a CTR. So the premise of the rule is
probably false in the real harness, and the rule's cost — distorting fact selection away from
the strongest available evidence — is paid whether or not the premise holds. That is a bad
trade and I withdraw it.

**Revised position.** Tier-A survives only as a *tie-breaker of last resort*: when two fact
sets are of genuinely equal quality, prefer the one a judge can check without leaving the
action's own context. It is never a floor, never a count, never a gate. What actually does the
work — and what I should have proposed in the first place — is the thing I already had: **name
the field path for every Tier-B fact in the rationale.** That converts an unverifiable claim
into a verifiable one for *any* judge, defective-window or full-dataset. It is strictly better
than tiering and it costs nothing.

One sub-rule survives on independent merit, and I want to be precise that it survives for
different reasons than I gave: **never assert an inactive offer as available.** Both opponents
derived the same rule from Cases 3 and 6 losing a point each for unverifiable catalog claims,
and it is substantively correct regardless of any judge window — telling a merchant their
expired offer is running is simply a factual error. I now think ARCH-L's formulation is the
right one: catalog offers are *proposable* ("we can run Dental Cleaning @ ₹299"), merchant
offers are *assertable* only when `status=="active"`, and an expired offer may be referenced
only in explicit past tense inside a winback/renewal frame, where the framing is self-evidently
deliberate. That is better than my blanket ban.

### C2 — My +12 / +13 ops estimates are field-relative, and against these two opponents they are close to zero.

This is the concession that costs me the most and I should have caught it myself. My
points-per-hour table was computed against a baseline of "the reference skeleton in
testing-brief §7 plus a competent composer prompt" — i.e. against the *field*. Both opponents
build the identical ops floor. ARCH-D's Appendix is my `emit_action()` with a better
recompose-then-drop ladder. ARCH-L's §3.6 is my deadline ladder with a load-shedding queue I
did not think to add. Against the field, +12/+13 is defensible. Against *these two designs*,
my ops advantage is approximately **+1 to +2**, and it lives entirely in three details neither
opponent specified: crash-safe `state.jsonl` rehydration, the equal-version `accepted:true`
call, and merchant-global auto-reply keying (F3, below — which I also got wrong).

Two different questions were being answered by one table. For "who ranks top 10 against 40
entrants", field-relative is the right frame and ops is real. For "which of these three
architectures is best", opponent-relative is the right frame and ops is settled ground. I was
answering the first while appearing to answer the second.

### C3 — F3: cross-conversation auto-reply. I got this wrong too, and so did both opponents.

Verified in source: `_auto_reply` (judge_simulator.py:693) loops `conv_auto_1..conv_auto_4`,
same merchant, same text, `turn_number` 2→5. **Four distinct `conversation_id`s.**

- My §4.4 reply classifier specified an "auto-reply → wait/end escalation" and never specified
  the key. My §4.6 anti-repetition is explicitly per-`conversation_id`. Guilty.
- ARCH-D §3.2 detector (a) iterates `conv.inbound_history`; the ladder in §3.3 keys on
  `conv.autoreply_streak`. D's regex detector (b) still fires on every turn, so D *classifies*
  correctly — but the streak never exceeds 1, so D emits the flag-send four times and never
  reaches `wait` or `end`. D's own §3.3 wrinkle note ("simulator-imperfect") understates this:
  it is not a tuning choice, the ladder structurally cannot advance.
- ARCH-L §5.1 has the same defect for the same reason (`strike 1/2/3` on `conv`).

The fix is cheap and is an architecture property, not a prompt property: the escalation
counter keys on `(merchant_id, normalized_inbound_signature)` in a process-global store,
with `conversation_id` used only for transcript threading. Note the objectives align here —
merchant-global escalation is both harness-correct and substantively correct, because four
identical canned texts from one merchant genuinely means the owner is not at the phone,
whatever thread they arrived on.

**Does this raise my +14?** Honestly: it raises my *confidence* in the estimate more than its
magnitude — call it +14 → +15. It is one scenario of three, it is cheap to fix once seen, and
any team that reads the harness source will see it. What it does raise materially is the case
for **regression fixtures over argument**: this defect was invisible to three careful readers
of the prose and obvious in eleven lines of Python.

### C4 — ARCH-D is substantially right that the per-action rubric has no cross-message window, and this cuts against my own W1.

D's §7.1 claim is correct about the scoring prompt: one body, one trigger, one merchant, one
category per call. "Reads templated across twenty sends" is not visible there.

I will note where it is too strong — anti-repetition at −2/repeat is an explicit cross-message
comparison, so *some* cross-message machinery exists in the grader; the Phase-2 merchant-playing
sub-LLM sees the conversation and reacts to formulaic copy with disengagement, which shortens
conversations and costs flow points; and testing-brief §13 ships `conversations.jsonl` plus a
`final_report.md` of "qualitative feedback", which a human reads when picking a top 10. So:
weakly observable, not unobservable.

But the direction is D's, and I have to follow it even though it helps me: **my W1 concession
was over-priced.** Mechanical fact density is less costly than I said. That in turn moves my
composer-artistry line from +9 to roughly **+7**, which *strengthens* my own thesis — which is
precisely why I scrutinised it rather than pocketing it. Intellectual-honesty note: I should be
more suspicious of an opponent's argument when it happens to favour me, and this one does.

### C5 — ARCH-D's `_intent` finding is real; my reading of it is narrower than his.

Verified, and sharper than either of us stated. `"here"` is a substring of `"there"`,
`"where"`, `"therefore"`:

```
'There are 3 options.'            → actioning=['here']            PASS=True
'Where do we start?'              → actioning=['here']            PASS=True
'Would you like me to send the draft?' → qualifying=['would you'] PASS=False
```

The actioning half is nearly free in any body of normal length. **The entire check reduces to a
five-phrase negative constraint.** That is the finding, and it changes the conclusion: a purely
negative constraint is satisfied 100% by a *regex blocklist on the output*, which ARCH-L
already specifies (`V_ACTION`) and which I specify implicitly in `emit_action()`. So this is a
**validator finding, not an architecture finding.** It favours determinism decisively only over
an *unvalidated* LLM. D overclaims when he calls it "the single cleanest example where a
template is strictly more reliable than a model" — it is the single cleanest example where a
three-line output filter is strictly more reliable than trusting a generator, which is a claim
all three of us already agree with.

It does raise my conversation-handler estimate, by about **+1**, because it is another
concrete cheap win. It does not re-rank anything.

### C6 — My 75% figure was overstated in the way that mattered.

The coordinator is right to call this load-bearing, so here is the arithmetic and the caveat
that undoes part of it.

Per emitted action, testing-brief §4 Phase 2 step 4: judge logs it → sub-LLM plays merchant →
POST `/v1/reply` → bot responds → "Repeat up to 5 turns or until bot ends."

| Reading | Bot-emitted turns per conversation | Reply share |
|---|---|---|
| 5 turns total, opener included | 1 opener + 4 replies | 80% |
| 5 reply exchanges after the opener | 1 + 5 | 83% |
| Realistic, with my own early exits (hostile ends turn 1, auto-reply ladder ends turn 3) | 1 + ~2.5 | **~71%** |

So **71–83%, midpoint ~75%** — the number is right *as a share of bot-emitted turns the judge
observes and logs.*

**The caveat that damages my rebuttal**: "turns the judge observes" is not "actions the
5-dimension rubric scores." In the reference harness, `_score_and_display` is invoked only on
tick actions (lines 669, 825); the three reply scenarios run zero LLM scoring. If the real
harness likewise applies the rubric only to tick actions, then the Phase-2 rubric mean is
computed over **openers only**, and replies contribute nothing to it. My rebuttal to ARCH-L
implied otherwise and that was sloppy.

What survives: testing-brief §13 specifies `scoring.json` as "5-dimension scores per action
**+ per conversation**". A per-conversation score exists in Phase 2. So conversation quality is
scored in Phase 2 — just not, on the available evidence, inside the per-action rubric mean.
**Revised claim**: replies are ~75% of judged *turns* and feed a Phase-2 per-conversation
score of unknown weight; they are not 75% of the rubric mean. My replay-handler estimate
therefore carries more top-10 conditionality than I claimed — but strictly less than ARCH-L's
"a prize you cannot reach", because the per-conversation score is Phase 2, not Phase 4.

---

## 2. HELD

### H1 — The restraint arithmetic, unchanged, and now uncontested.

Both opponents independently landed on 3–8 sends per tick with an evidence gate and an
average-aggregation argument. ARCH-D's `TICK_BUDGET=8`, ARCH-L's `SEND_BUDGET 3-5`, my
`B_t=4`. ARCH-L's attack O1 does not actually contain the volume attack I predicted — he
concedes the point in his own §3.4. This is settled, and the throughput derivation in my §2.3
(20 actions/tick → ~960 reply calls → 21–32/min, unserviceable) stands unrebutted.

One refinement I take from ARCH-D that improves my design: his `EARLY_RESERVE` (elevated
threshold on ticks 1–3 to preserve merchant slots for the Phase-3 injections). Given
`PER_MERCHANT_WINDOW_CAP=2`, spending a merchant's slots before the new digest lands is a
direct forfeit of adaptation points. I had the priority bypass but not the reservation. Adopted.

### H2 — F2: ARCH-L's speculation is real, but he has the timing backwards, and the gap concentrates on the +25 block.

The mechanism is sound and I accept it. But L's §3.1 says the push→tick gap is "seconds in
the simulator and minutes in the live harness." **That is inverted.**

- `judge_simulator._full` (807–810, then 825) pushes *all* merchants and *all* triggers, then
  ticks in batches. Enormous gap. L's cache is warm.
- The live harness, testing-brief §4 Phase 2: "At each tick: **1.** Judge POSTs any new/updated
  contexts that happened during this tick. **2.** Judge calls POST `/v1/tick`." Steps 1 and 2
  are adjacent lines of sequential judge code. The gap is plausibly **sub-second**.

L's own numbers: T2 p50 4.8 s, p95 9 s. A trigger pushed at step 1 and ticked at step 2 is
**cold**. His fallback is `urgency>=4 → TemplateFloor, else skip`. So under the live ordering,
newly-injected context is exactly the case that floors or drops — and "newly-injected context"
*is* Phase 3, the +25 block. Worse, his `CompositionKey` includes `merchant_version` and
`category_version`, so a Phase-3 bump invalidates precisely the keys he most needs warm.

This is survivable and I will say so: the *next* tick is 2.5–3.75 minutes later, the cache is
warm by then, his `freshness_bonus` promotes it, and the adaptation requirement is to cite the
new fact in a *subsequent* send. So L's ceiling is available with a **one-tick lag**, at the
cost of one floored-or-skipped send per injection. That is a real but bounded defect, and the
fix is to make the TemplateFloor genuinely good at the *new-fact citation* case specifically —
which is exactly my §5.3 deterministic freshness template, and exactly ARCH-D's NOVELTY move.
All three of us need the same component; only D and I specified it.

**Does my ranking survive?** Yes, and the mechanics are worth stating because the coordinator's
framing assumes otherwise. Points-per-hour is Δpoints ÷ hours. Speculation reduces the *hours*
needed for timeout discipline (my §4.3 guillotine: ~2 h → ~1 h) while leaving Δpoints
unchanged, so that line's pts/hr **rises**. And it does not touch Rank 1 at all: speculation
prevents timeouts, not missing `suppression_key` fields, `send_as` inversions, URL leakage, or
repeat bodies. Recomputed top of table, opponent-relative rather than field-relative:

| Rank | Intervention | hrs | Δ (field-rel.) | Δ (vs D and L) | pts/hr (field) |
|---|---|---:|---:|---:|---:|
| 1 | Adaptation engine + freshness templates | 8 | +20 | **+6** | 2.5 |
| 2 | Conversation handlers (incl. F3 + C5 fixes) | 5 | +15 | **+4** | 3.0 |
| 3 | Zero-defect egress | 4 | +12 | **+1.5** | 3.0 |
| 4 | Restraint / suppression / EARLY_RESERVE | 3 | +7 | **+1** | 2.3 |
| 5 | Healthz, crash-safe state, deploy | 5 | +13 | **+1.5** | 2.6 |
| 6 | Composer quality | 15 | +7 | **?** — the open question | 0.5 |

The honest reading of that table is that against these opponents **the only line with real
headroom is the one I ranked ninth**, plus adaptation. My thesis was correct about the field
and wrong about the room.

### H3 — ARCH-L's core empirical claim (templates score 32/50) is asserted, not measured, and so is ARCH-D's (44–48).

This is the largest live disagreement in the debate: 12–16 points on ~48 messages, on the
bucket that decides top-10 entry. ARCH-L's O1 rebuttal asserts "a template bot does not score
47; it scores 6-7 per dimension." ARCH-D's §7.1 asserts the opposite, reasoning from the fact
that the 44/50 case lost points for fact poverty, not formulaicness. **Neither produced a
number from the judge.** Both arguments are plausible and they cannot both be right. See §4.

### H4 — I hold that the adaptation block is the highest-value contested ground, and that it is the one place ARCH-D's own analysis defeats him.

D's §6.2 concedes his counter-indication table "only knows the contrarian relationships present
in the *base* digest; a Phase-3 item introducing a new one gets cited faithfully but not argued
from." That is the +25 block, and it is made *by construction* of content nobody saw during
development. D can cite; he cannot reason about. L can reason about; his cache is cold exactly
when it matters. My design — deterministic diff and forced citation for the guarantee, model
for the implication sentence, deterministic freshness template as the floor — is the only one
of the three that is both warm on arrival and able to argue. I hold this.

I also hold the specific Phase-3 detail neither opponent has: **cite the delta, not the new
value.** "Views moved 2,410 → 2,580 since we last looked" is only producible by a bot holding
*both* versions. It is the most legible possible proof of adaptation. ARCH-D reaches the same
idea in §4.3 and states it as well as I do; ARCH-L does not.

---

## 3. THE SYNTHESIS I WOULD ACCEPT

Not mine. This one:

> **ARCH-L's speculative pipeline as the skeleton, ARCH-D's composition engine promoted from
> exception handler to co-equal first path, my policy and adaptation layer as the governor.**

Concretely:

1. **Transport and state**: L's topology — `/v1/context` acks in <25 ms and enqueues; `/v1/tick`
   is a cache read and a sort; `/v1/healthz` touches integers on an unlocked route. Plus my
   `state.jsonl` crash-safe rehydration and the equal-version `accepted:true` call.
2. **Two composers, raced, not laddered.** D's FactPack + grammar composes in ~4 ms at push
   time; L's T2 composes speculatively in ~5 s. Both are verified by the same validator suite.
   At tick, take the verified LLM composition if present, D's engine output otherwise. D's
   engine is then never a "failure mode" — it is the guaranteed-warm path, which fixes L's
   cold-cache-on-injection problem (H2) directly, because D's engine is warm *by construction*.
3. **One validator suite**, the union of all three: L's `facts_used`/`surface_form` substring
   invariant and orphan-numeral scan (the best grounding mechanism proposed by anyone),
   D's phrase-level taboo compilation with parenthetical stripping and the 5-gram case-study
   blocklist, my rationale/body consistency assertion and fail-closed drop.
4. **Reply**: pure-Python policy decides `send`/`wait`/`end` before any model runs — all three
   of us agree. Escalation counters keyed **merchant-global** (C3). `V_ACTION` negative filter
   on the five qualifying phrases (C5). LLM supplies the artifact in ACTION MODE, because L is
   right that Case 6's 49/50 is *the draft itself*, and a state machine cannot emit a draft.
5. **Policy**: my gates and budgets plus D's `EARLY_RESERVE`, restraint at 4/tick, ≤2
   conversations per merchant, the suppression taxonomy all three of us wrote near-identically.
6. **Adaptation**: deterministic diff → freshness queue → priority bypass → forced literal
   citation → deterministic freshness template floor, with the delta cited across versions.
7. **Rationale**: assembled from the verified fact ledger with field paths named — which,
   per C1, is what I should have proposed instead of tiering.

I would rather ship that than mine, and if the coordinator wants a single architecture, that is
my vote. My distinctive contributions to it are the governor and the adaptation machinery, not
the composer — which is the correct outcome of this debate, not a graceful concession.

---

## 4. WHAT SHOULD BE DECIDED BY TEST, NOT ARGUMENT

Four. The first is the whole competition.

### T1 — The paired composer bake-off. **Do this first; it settles H3.**

The disagreement is 12–16 points on the largest bucket, and it is directly measurable with
assets we already have.

- Build ARCH-D's Tier-0 engine (backstop family + 5 voice packs — he estimates this is the
  smallest shippable unit, a few hours) and a single frontier composer with L's ledger and
  validators. Roughly one day for both.
- Run both over the **same 30 canonical `test_pairs.json`** pairs, plus 30 deliberately thin
  pairs (generated merchant + placeholder trigger) where the two architectures should diverge
  most.
- Score with `judge_simulator.py` in `full_evaluation` mode, real LLM judge, 3 scoring
  repetitions per body to damp judge variance.
- Report **per-dimension paired means with a paired t-test or Wilcoxon**, split by rich/thin.
- Decision rule agreed in advance: if the gap is <3 points total, ARCH-D wins on ops and cost
  and the LLM goes to authoring time only. If it is >8 points, ARCH-L wins the composer and the
  engine becomes the floor. Between 3 and 8, ship the raced hybrid in §3.2.

I commit to abiding by the result. Note that this test also silently measures the thing D and L
each assert about the *other's* architecture, which is why it should be paired and blinded
rather than each of us scoring our own.

### T2 — The aggregation question (A1): mean or sum.

This cannot be resolved by experiment on our side — the reference simulator only tells us about
the reference simulator. It must be **asked of the organizers**, and it is the single highest-
value question we could ask. If unanswerable, the decision-theoretic answer is the hedge
already in all three designs (Θ and the budgets as config constants, flipped at T-60), because
all three of us independently chose roughly the same volume anyway.

### T3 — The speculation-gap measurement (settles H2).

Build a local harness that replicates the **live** push→tick ordering — contexts for tick N
pushed immediately before tick N, not batched up front — and measure cache-hit rate for
newly-injected triggers, and separately for version-bumped merchants. If hit rate on injections
is <50%, L's ceiling is not available on the +25 block without the deterministic freshness
floor, and §3.2's raced architecture is mandatory rather than optional. Half a day.

### T4 — Behavioural regression fixtures (settles C3 and C5, and everything like them).

The F3 defect was invisible to three careful readers of the prose and obvious in eleven lines
of Python. Freeze the three canonical judge messages, the four-distinct-`conversation_id`
loop, and the exact `qualifying`/`actioning` substring lists as CI fixtures, and assert against
them on every build. The general lesson, which I am taking as the main methodological result of
this round: **read the harness, then test against it — do not reason about it.** Every finding
that moved this debate came from source, not from argument.

---

## 5. Net position after cross-examination

- Withdrawn: the Tier-A requirement (C1), and the claim that ops is where the marginal point
  lies **against these opponents** (C2).
- Corrected: the 75% figure and its rubric implication (C6); my W1 pricing (C4); the auto-reply
  keying (C3).
- Held: the restraint arithmetic (H1), the speculation-timing correction and the ranking
  mechanics (H2), the adaptation block as the decisive contested ground (H4).
- Conceded to D: no cross-message window in the per-action rubric; the intent check as a pure
  negative constraint; `EARLY_RESERVE`.
- Conceded to L: the speculative pipeline; `facts_used`/`surface_form` as the best grounding
  mechanism proposed by anyone; ACTION MODE must deliver the artifact, not a promise of one.
- The open question is no longer mine: it is **how much a frontier composer actually beats a
  compiled one on this rubric**, and it should be measured (T1) rather than argued.
