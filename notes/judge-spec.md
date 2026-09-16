# judge_simulator.py — Technical Spec

Source: `/Users/gurmeshsingh/vera-challenge/pkg/judge_simulator.py` (962 lines), read in full.

This is a **local, reference judge simulator** distributed to entrants — it is not necessarily the exact grading harness used for official scoring, but it is presumably representative of it. It calls a real LLM (configured by the entrant with their own API key) to score bot output, plus runs a handful of deterministic behavioral scenarios against the bot's `/v1/reply` and `/v1/tick` endpoints.

---

## 1. The judge prompt(s) — VERBATIM

There is exactly one system prompt and one user-prompt template, both defined in `LLMScorer` (`judge_simulator.py:440-530`).

### System prompt (`judge_simulator.py:443-492`)

```
You are a STRICT judge for the magicpin AI Challenge. You score merchant engagement messages.

SCORING DIMENSIONS (0-10 each, be strict - 5 is average, 7+ is good, 9+ is excellent):

1. SPECIFICITY: Does the message have VERIFIABLE facts?
   - Numbers (percentages, counts, prices)
   - Dates/times
   - Source citations
   - Concrete claims vs vague statements

2. CATEGORY FIT: Does the voice match the business type?
   - Dentists: clinical, peer-to-peer, technical OK, use "Dr." prefix
   - Salons: warm, friendly, practical
   - Restaurants: operator-to-operator
   - Gyms: coaching, motivational
   - Pharmacies: trustworthy, precise

3. MERCHANT FIT: Is it personalized to THIS merchant?
   - Uses their name/owner name correctly
   - References their actual data (not fabricated)
   - Honors language preference

4. TRIGGER RELEVANCE: Does it connect to WHY NOW?
   - Clear reason for this specific message
   - Uses data from the trigger payload
   - Not a generic nudge

5. ENGAGEMENT COMPULSION: Would they reply?
   - Loss aversion, curiosity, social proof
   - Clear CTA
   - Low friction ask

PENALTIES:
- Fabricating data not in context: -2
- Exposing internal jargon to merchant: -1

RESPOND ONLY WITH THIS EXACT JSON FORMAT:
{
  "specificity": <0-10>,
  "specificity_reason": "<why this score, 1-2 sentences>",
  "category_fit": <0-10>,
  "category_fit_reason": "<why this score>",
  "merchant_fit": <0-10>,
  "merchant_fit_reason": "<why this score>",
  "decision_quality": <0-10>,
  "decision_quality_reason": "<why this score>",
  "engagement_compulsion": <0-10>,
  "engagement_reason": "<why this score>",
  "hint": "<one sentence guidance for improvement, cryptic not direct>"
}
```

**Note the mismatch (important gotcha, see §7):** the rubric text lists dimension **4 as "TRIGGER RELEVANCE"**, but the required JSON output schema has no `trigger_relevance` key at all — it asks for `decision_quality` instead. The parser (`_parse_response`, `judge_simulator.py:555-556`) accepts either key name as a fallback for the same slot (`data.get("decision_quality", data.get("trigger_relevance", 5))`), meaning the LLM's own confusion about which name to emit is silently absorbed. "Decision quality" and "trigger relevance" are treated as the exact same scored field even though the code/spec name (`decision_quality`) never appears anywhere in the rubric description shown to the judge LLM.

### User prompt template (`judge_simulator.py:504-530`)

Built per-scored-action inside `LLMScorer.score()`. `f"""..."""` with the following literal structure (braces below show real interpolation points):

```
SCORE THIS MESSAGE:

=== CONTEXT PROVIDED TO BOT ===
Category: {category.get('slug', 'unknown')}
Voice: {category.get('voice', {}).get('tone', 'unknown')}
Taboos: {category.get('voice', {}).get('vocab_taboo', [])[:5]}

Merchant: {merchant.get('identity', {}).get('name', 'unknown')}
Owner: {merchant.get('identity', {}).get('owner_first_name', 'unknown')}
Locality: {merchant.get('identity', {}).get('locality', 'unknown')}
Languages: {merchant.get('identity', {}).get('languages', [])}
Performance: views={merchant.get('performance', {}).get('views', '?')}, calls={merchant.get('performance', {}).get('calls', '?')}, ctr={merchant.get('performance', {}).get('ctr', '?')}
Signals: {merchant.get('signals', [])}
Active Offers: {[o.get('title') for o in merchant.get('offers', []) if o.get('status') == 'active']}

Trigger Kind: {trigger.get('kind', 'unknown')}
Trigger Payload: {json.dumps(trigger.get('payload', {}))}
Trigger Urgency: {trigger.get('urgency', '?')}

Customer: {json.dumps(customer.get('identity', {})) if customer else 'None (merchant-facing)'}

=== BOT'S MESSAGE ===
Body ({len(body)} chars): "{body}"
CTA: {action.get('cta', 'none')}
Send As: {action.get('send_as', 'vera')}

Score each dimension 0-10 with clear reasoning. Be STRICT.
```

Only the first 5 taboo words are shown (`[:5]`, line 509) — taboo words 6+ are invisible to the judge even if your message violates them. Only `offers` with `status == "active"` are surfaced (line 517); inactive/expired offers are dropped entirely from what the judge sees, so referencing them can look like "fabrication" to the judge even if it's real merchant data. The action fields actually read: `action["body"]`, `action["cta"]`, `action["send_as"]`, `action["trigger_id"]`, `action["merchant_id"]`, `action["customer_id"]` — no other fields of an action object are ever inspected by the scorer.

---

## 2. Scoring mechanics

- Each dimension is scored 0–10 by the LLM: `specificity`, `category_fit`, `merchant_fit`, `decision_quality` (aka trigger_relevance), `engagement_compulsion` (`ScoreResult` dataclass, `judge_simulator.py:118-137`).
- **No weights** — all 5 dimensions are summed unweighted. `ScoreResult.total` (`judge_simulator.py:134-137`):
  ```python
  @property
  def total(self) -> int:
      return max(0, self.specificity + self.category_fit + self.merchant_fit +
                 self.decision_quality + self.engagement_compulsion - self.penalties)
  ```
  Max possible = 50 (5 × 10). Floor-clamped at 0 (never negative) via `max(0, ...)`.
- **Penalties**: rubric text names two penalty types (fabrication −2, jargon exposure −1, `judge_simulator.py:476-478`), but **the code never actually populates `ScoreResult.penalties` or `penalty_reasons` from the LLM response** — `_parse_response` (lines 540-564) does not read any `penalties`/`penalty_reasons` key from the parsed JSON at all. The dataclass fields default to `0` / `[]` and are simply never set. **Penalties described in the prompt are not mechanically applied by this harness** — the judge LLM has no dedicated JSON field to report them in, so they can only manifest indirectly by the LLM lowering one of the 5 category scores itself.
- No pass/fail threshold is enforced in code for an individual message. Aggregate: `_final_summary` (`judge_simulator.py:880-916`) computes the **average across all scored messages** (integer division `// n` per dimension, `judge_simulator.py:888-893`) and buckets the average percentage (`total/50`) into cosmetic bands only (no exit code / gating):
  - `>= 80%` → "EXCELLENT"
  - `>= 60%` → "GOOD"
  - `>= 40%` → "NEEDS IMPROVEMENT"
  - `< 40%` → "BELOW EXPECTATIONS"
  (`judge_simulator.py:909-916`)
- **Parsing the LLM response** (`_parse_response`, `judge_simulator.py:540-564`):
  1. Regex-extracts the first `{...}` blob greedily across the whole response: `re.search(r'\{[\s\S]*\}', response)` (line 542). If no match → fallback score.
  2. `json.loads()` on that match. On any exception (bad JSON) → fallback score.
  3. Each numeric field is coerced via `int(data.get(field, 5))` then clamped `min(10, max(0, ...))` — default value if the key is absent is **5** (average), not 0.
  4. `hint` and each `_reason` field default to empty string `""` if missing.
- **Fallback scoring on failure** (`_fallback_score`, `judge_simulator.py:566-578`), triggered by (a) an exception during the LLM call itself (`score()`, line 536-538), (b) no JSON found in response, or (c) JSON parse/int-coercion error:
  - `specificity = min(10, 3 + nums*2)` where `nums` = count of regex `\d+` matches in the lowercased body (line 569-571) — pure heuristic, rewards raw digit-count regardless of what the digits mean.
  - All other 4 dimensions hard-coded to **5** with reason `"Could not evaluate"`.
  - `hint = "LLM scoring failed - using basic heuristics"`.
  - This means an LLM outage/timeout/malformed-JSON still produces a non-zero, non-punishing score (25/50 baseline + specificity bonus) rather than a 0 or an error — bots aren't hurt by judge failures, and a message stuffed with digits can score decently on the fallback path even with zero real content.

---

## 3. Non-LLM (deterministic) checks

There is **no schema validation, banned-word regex, length-limit check, hallucination check, or determinism/repeat-call check anywhere in this file.** The only deterministic logic is:

1. **HTTP transport-level checks** in `BotClient._request` (`judge_simulator.py:390-410`): distinguishes `HTTPError` 401 ("Unauthorized") from other HTTP errors (reports `f"HTTP {e.code}"`) from generic exceptions (timeouts, connection errors — reported as `str(e)`). It also tries to parse an HTTPError body as JSON (some APIs return structured error JSON on 4xx/5xx) before falling back to the bare status string.
2. **`push_context` "accepted" check** (`_warmup`, `judge_simulator.py:643,648`): `status = "PASS" if data and data.get("accepted") else "FAIL"` — the only field inspected from `/v1/context`'s response is the boolean `accepted`.
3. **Auto-reply scenario** (`_auto_reply`, `judge_simulator.py:681-713`): purely deterministic string/action-type check — loops sending the same canned "Thank you for contacting us..." message 4 times and checks whether the bot's returned `action` field is `"end"` (pass) or `"wait"` (still ok) vs. anything else (bot kept talking to a bot — fails only in the sense of a warning after 4 turns; function still returns `True` regardless, see §7).
4. **Intent-transition scenario** (`_intent`, `judge_simulator.py:715-751`): keyword-list check on the reply body. Lowercased `body` checked against:
   - `qualifying = ["would you", "do you", "can you tell", "what if", "how about"]`
   - `actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]`
   Logic: `if any(actioning) and not any(qualifying)` → PASS ("switched to ACTION mode"); `elif any(qualifying)` → FAIL ("still qualifying"); else → WARN ("unclear"). Purely substring matching, no LLM involved. (Also: the return value of `_intent()` is always `True` even on the printed FAIL — see §7.)
5. **Hostile-handling scenario** (`_hostile`, `judge_simulator.py:753-783`): checks `action == "end"` OR (`action == "send"` AND body contains one of `"sorry"`, `"apolog"`, `"won't"`). Anything else prints FAIL. Return value is always `True` regardless (see §7).
6. No dedupe/suppression-key check, no duplicate-send check, no rate-limit-of-actions check anywhere in the file.

---

## 4. Exact API contract (as the simulator calls it)

All requests built in `BotClient` (`judge_simulator.py:386-434`); base URL from `BOT_URL` (line 24), path prefix `/v1/...`. Requests are `application/json`, sent via stdlib `urllib.request`.

### `GET /v1/healthz` (`judge_simulator.py:412-413`)
- Request: no body. Timeout 5s.
- Response: entirely unvalidated — only used to detect network/HTTP error (any successful JSON body, even `{}`, counts as pass). No fields are read from a successful response.

### `GET /v1/metadata` (`judge_simulator.py:415-416`)
- Request: no body. Timeout 5s.
- Response fields read (all optional, defaulted if missing): `team_name` (default `"?"`), `model` (default `"?"`) — printed in `_warmup` (`judge_simulator.py:638`). No other fields inspected. Failure here is only a WARN, not a hard failure (`judge_simulator.py:635-636`).

### `POST /v1/context` (`push_context`, `judge_simulator.py:418-422`)
- Request body sent:
  ```json
  {
    "scope": "<'category'|'merchant'|'trigger'>",
    "context_id": "<string, e.g. category slug or merchant_id or trigger id>",
    "version": 1,
    "payload": { ...full category/merchant/trigger JSON object from dataset... },
    "delivered_at": "<UTC ISO8601 with trailing Z, from datetime.utcnow().isoformat()+'Z'>"
  }
  ```
  Timeout 10s. Called for every category and the first 5 merchants during `_warmup` (`judge_simulator.py:641-650`); for all merchants and all triggers during `_full` (`judge_simulator.py:807-810`); for a batch of trigger IDs during `_phase2_short` (`judge_simulator.py:662`).
- Expected response: only `accepted` (boolean) is read (`judge_simulator.py:643,648`). Any other fields are ignored. Missing/falsy `accepted` → printed as `"FAIL"` for that context push, but does not abort the run.

### `POST /v1/tick` (`judge_simulator.py:424-427`)
- Request body sent:
  ```json
  {
    "now": "<UTC ISO8601 + 'Z'>",
    "available_triggers": ["<trigger_id>", ...]
  }
  ```
  Timeout 15s.
- Expected response: `{"actions": [ ... ]}` — `data.get("actions", [])` (`judge_simulator.py:669,825`), defaults to empty list if missing/malformed (no crash). Each action object in that list is expected (by the scorer, not validated) to carry: `trigger_id`, `merchant_id`, `customer_id` (optional/nullable), `body` (string), `cta` (optional, default `"none"` when scoring), `send_as` (optional, default `"vera"` when scoring). None of these are type-checked; `.get()` with defaults is used throughout, so a missing `body` just scores as an empty string (specificity will fall through to fallback-style low score via the judge's own read of `""`).

### `POST /v1/reply` (`judge_simulator.py:429-434`)
- Request body sent:
  ```json
  {
    "conversation_id": "<string, e.g. 'conv_auto_1'>",
    "merchant_id": "<string>",
    "customer_id": null,
    "from_role": "merchant",
    "message": "<string — the simulated merchant's incoming message>",
    "received_at": "<UTC ISO8601 + 'Z'>",
    "turn_number": <int>
  }
  ```
  Timeout 15s. `customer_id` is **always literally `null`** in every call the simulator makes (never populated) — the reply scenarios are always merchant-facing, never customer-facing.
- Expected response fields read: `action` (string — checked against `"end"`, `"wait"`, `"send"`, default `"?"` if missing), `wait_seconds` (only read when `action == "wait"`, default `"?"`), `body` (string, default `""`). No schema enforcement — a bot that omits `action` entirely just falls into the catch-all `else` branch in each scenario (treated as "bot sent a message" / unclear, not a hard error).

### General malformed-response handling
`BotClient._request` (`judge_simulator.py:398-410`): if the HTTP call succeeds but the body isn't valid JSON, `json.loads` will raise and propagate as a generic exception caught by the outer `except Exception as e: return None, str(e), ...` — surfaces as an error string to the caller, all downstream `data.get(...)` calls are skipped because callers check `err` first before touching `data`.

---

## 5. Test scenarios — `TEST_SCENARIO`

Dispatch table in `JudgeSimulator.run` (`judge_simulator.py:606-614`):

| Key | Method | What it probes |
|---|---|---|
| `warmup` | `_warmup` (625-652) | Bot reachability (`/v1/healthz`), metadata reporting, and that `/v1/context` accepts pushes for every category and the first 5 merchants. No LLM scoring. |
| `phase2_short` | `_phase2_short` (654-679) | Runs `_warmup` first, then pushes 3 triggers and calls `/v1/tick`, LLM-scoring every returned action. Probes basic tick→action→judge pipeline end-to-end on a small trigger set. |
| `auto_reply_hell` | `_auto_reply` (681-713) | Sends the identical canned "Thank you for contacting us..." auto-reply message to the bot 4 times in a row (turns 2–5) via `/v1/reply` and checks whether the bot recognizes it's talking to another bot/auto-responder and returns `action: "end"` (or at least `"wait"`) instead of continuing to converse forever. Deterministic, no LLM judge call. |
| `intent_transition` | `_intent` (715-751) | Sends one merchant message signaling commitment/agreement ("Ok lets do it. Whats next?") and checks (via keyword matching) whether the bot's next reply shifts from "qualifying" language to "actioning" language — i.e., stops asking discovery questions once the merchant has said yes. Deterministic. |
| `hostile` | `_hostile` (753-783) | Sends a hostile/annoyed merchant message ("Stop messaging me. This is useless spam.") and checks the bot either ends the conversation (`action == "end"`) or apologizes gracefully in a `"send"` response. Deterministic. |
| `all` | `_all` (785-799) | Runs `warmup`, `auto_reply`, `intent`, `hostile` in sequence (note: **not** `phase2_short` or `full_evaluation`), collecting a pass/fail per scenario and printing a summary table. This is the harness's **default** scenario per `TEST_SCENARIO = "all"` (line 39). It does **not** invoke the LLM judge at all (none of its four sub-scenarios call `_score_and_display`), so running the default config never actually exercises the 5-dimension scoring rubric — only the 3 deterministic behavioral checks plus context-push plumbing. |
| `full_evaluation` | `_full` (801-831) | Pushes **every** merchant and **every** trigger as context, then calls `/v1/tick` in batches of 5 trigger IDs at a time across the full trigger set, LLM-scoring every returned action (non-verbose: score bars only, no reason text printed). This is the only scenario that broadly samples the dataset for LLM scoring. |

`_all`'s aggregate boolean is `all(p for _, p in results)` (line 799) — but see §7 for why the three behavioral sub-scenario functions always return `True` regardless of what they printed as FAIL.

---

## 6. Operational limits enforced in code

| Limit | Value | Location |
|---|---|---|
| LLM completion timeout | 45s (`TIMEOUT_LLM`) | `judge_simulator.py:59`, used by every provider's `urlopen(..., timeout=TIMEOUT_LLM)` except Ollama |
| Ollama completion timeout | 90s (hardcoded, not `TIMEOUT_LLM`) | `judge_simulator.py:297` |
| LLM `max_tokens` / `maxOutputTokens` | 1500 | every provider's request body, e.g. `judge_simulator.py:171, 193, 221, 248, 273, 319` |
| LLM `temperature` | 0.2 (fixed, not configurable) | same call sites |
| `healthz` timeout | 5s | `judge_simulator.py:413` |
| `metadata` timeout | 5s | `judge_simulator.py:416` |
| `push_context` timeout | 10s | `judge_simulator.py:419` |
| `tick` timeout | 15s | `judge_simulator.py:425` |
| `reply` timeout | 15s | `judge_simulator.py:430` |
| Retries | **None** — no retry logic anywhere; any single failed HTTP call or LLM call is either treated as a scenario failure or triggers the LLM fallback-scoring path once. | throughout `BotClient` and `LLMScorer.score` |
| Rate limiting | **None enforced by the simulator itself** (no sleep/backoff between calls) | n/a |
| Max actions per tick | **None enforced/capped** — the simulator scores every action the bot returns in a `/v1/tick` response, however many that is | `judge_simulator.py:669, 676-677, 825, 828-829` |
| Payload caps | **None** — full merchant/category/trigger JSON objects are pushed verbatim as `payload`, no size truncation; the only truncation is display-only (printed body strings sliced to 50/100/200 chars, e.g. `judge_simulator.py:108, 709, 738, 847` — cosmetic terminal output, not sent to bot or judge) | various |
| Context push scope in `warmup` | Only first 5 merchants (`list(...)[:5]`), all categories, no triggers | `judge_simulator.py:646` |
| Taboo words shown to judge | First 5 only (`[:5]`) | `judge_simulator.py:509` |

---

## 7. Exploitable / gotcha surface

1. **Default scenario (`TEST_SCENARIO = "all"`) never invokes the LLM judge.** `_all` only runs `warmup`, `auto_reply`, `intent`, `hostile` — none of which call `_score_and_display`/`LLMScorer.score`. An entrant who only ever runs the tool with default config will never see the 5-dimension rubric exercised; they need `phase2_short` or `full_evaluation` for that. (`judge_simulator.py:785-799` vs `606-614`)

2. **The three behavioral scenario functions always return `True`, even when they print FAIL.** `_auto_reply` returns `True` unconditionally after the loop even if the bot "never ended after 4 auto-replies" (`judge_simulator.py:712-713`, only a `print_warn`, function still falls through to `return True`). `_intent` prints `print_fail("Bot is STILL QUALIFYING after commitment")` but still executes `return True` at the end (`judge_simulator.py:747, 751`). `_hostile` prints `print_fail("Bot didn't handle hostility well")` but also unconditionally `return True` (`judge_simulator.py:781, 783`). This means `_all`'s pass/fail aggregation (`all(p for _, p in results)`) is **not actually sensitive to the printed FAIL verdicts** in these three scenarios — the overall "all passed" boolean and process exit code (`sys.exit(0 if success else 1)`, line 958) will read as success regardless of whether the bot handled auto-replies, intent transitions, or hostility correctly. Only genuine connection errors (`err` truthy) make these return `False`. Anyone gating a CI pipeline on this script's exit code should know it doesn't actually fail on bad behavioral responses, only on unreachability.

3. **Fallback scoring rewards raw digit density, not correctness.** If the LLM call throws, or its output can't be parsed as JSON, specificity is computed purely as `3 + 2*count_of_digit_runs` (capped at 10) with everything else defaulted to 5/10 (`judge_simulator.py:566-578`). A message like "call 99999999 for 50% off on 3/3/3000" scores a high specificity fallback despite being nonsense. This only matters if the LLM call itself is flaky/rate-limited during grading — but it means a bot author testing against an unreliable/rate-limited provider might see inflated, misleading specificity scores that don't reflect the real judge's opinion.

4. **Missing JSON keys default to `5` (average), not `0` or a penalty.** `data.get("specificity", 5)` etc. (`judge_simulator.py:549-559`) — if the judge LLM's JSON omits a dimension (e.g., truncated response due to the 1500 max_tokens cap), that dimension silently scores as a middling 5/10 rather than failing loudly. Combined with a verbose 5-reason JSON payload plus a `hint` field, 1500 max_tokens can plausibly get tight for longer bodies/reasons — long, verbose bot messages could push the judge's response near the truncation boundary, corrupting the trailing JSON keys (`hint`, `engagement_reason`) most.

5. **Penalties in the rubric text are never mechanically wired up.** The system prompt tells the LLM about −2/−1 penalties (`judge_simulator.py:475-478`) and `ScoreResult` has `penalties`/`penalty_reasons` fields, but `_parse_response` never reads a `penalties` key from the LLM's JSON (the required output schema in the system prompt doesn't even include one) — so `penalties` stays `0` forever in this harness. Any penalty effect can only occur indirectly, if the LLM lowers one of the 5 named 0–10 scores itself to reflect fabrication/jargon. This is a meaningful gap between the documented rubric and the actual scoring code — worth knowing if this simulator is representative of the real grader (it may not be, but if it is, "penalties" as a distinct scoring lever may not really exist).

6. **`decision_quality` / `trigger_relevance` naming mismatch.** Rubric prose calls dimension 4 "TRIGGER RELEVANCE" but the required JSON schema field is `decision_quality`; the parser accepts either name interchangeably for the same slot (`judge_simulator.py:555-556`). This is the field the task prompt calls "decision quality" — functionally it is scored purely as "did the message use the trigger data / justify why-now", not some broader notion of decision-making quality. Optimize your bot's trigger-utilization, not some abstract "decision" narrative.

7. **Only active offers are shown to the judge; inactive ones are invisible and referencing them risks a fabrication read.** `[o.get('title') for o in merchant.get('offers', []) if o.get('status') == 'active']` (`judge_simulator.py:517`) — if your bot references a recently-expired or scheduled (non-active) offer using real data pushed via `/v1/context`, the judge prompt won't show that offer at all, and the LLM may score it down as "fabricating data not in context" purely because of this filter, not because your bot actually invented anything.

8. **Only the first 5 taboo words are ever shown to the judge** (`judge_simulator.py:509`, `[:5]`). If a category's `vocab_taboo` list has more than 5 entries, violating word #6+ is literally invisible to the LLM judge in this harness — the judge cannot penalize what it never sees, though a "real" production judge/grader might not have this truncation.

9. **The scorer only reads `body`, `cta`, `send_as`, `trigger_id`, `merchant_id`, `customer_id` off an action object** (`judge_simulator.py:502, 526-528, 835-837`). Any other fields your bot returns in a tick action (extra metadata, confidence scores, reasoning/rationale fields, suppression keys, etc.) are completely ignored by this scorer — they aren't fed to the judge and can't help or hurt your LLM score in this harness. Conversely, nothing in the file cross-checks `trigger_id`/`merchant_id` for existing in the dataset before lookup — `self.dataset.triggers.get(tid, {})` / `.get(mid, {})` silently return `{}` in `_score_and_display` (`judge_simulator.py:839-840`) if your bot returns an ID that isn't in the loaded dataset, meaning the judge prompt would show "unknown" everywhere for that context, likely tanking merchant_fit/category_fit scores with no error raised.

10. **No cross-call determinism check, no duplicate-send/suppression check exists in this file at all.** Nothing calls the bot twice with identical input to check for consistent output, and nothing checks whether the same trigger/merchant pair gets messaged twice across ticks. If the real challenge grader does check for this, it is not visible in this reference simulator — do not assume the absence here means the real grader skips it.

11. **`customer_id` is always sent as `null` in `/v1/reply` calls** (`judge_simulator.py:431`) — the three conversational scenarios (`auto_reply`, `intent`, `hostile`) are always simulated as **merchant-facing** conversations. There is no customer-facing reply scenario tested anywhere in this file, even though the scorer's prompt template supports a `Customer:` block (line 523) for when `customer_id` is present on a tick action. Bots should not assume the "hostile"/"auto-reply"/"intent" behavioral checks will ever be run against a customer-facing conversation in this harness.

12. **The `hint` field is explicitly asked to be "cryptic not direct"** (`judge_simulator.py:491`) — by design, the improvement hint returned to you will deliberately withhold a direct explanation, so don't expect actionable clarity from it; it's meant to be evocative rather than a to-do list.
