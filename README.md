# Vera bot: decide in code, write with care

A stateful HTTP bot for the magicpin AI Challenge, built on the Python standard library. An LLM is optional and only polishes wording.

## Approach

Every proactive message goes through the same five steps:

1. **Facts.** The four contexts are normalised into checked, human-readable facts: "CTR 2.1% vs 3.0% peer average", "78 patients lapsed 180+ days", "your last Google post went up 22 days ago". Every number the bot can print is registered. That includes numbers it derives on purpose, such as "111 short of 1,000".
2. **Decision.** One playbook per trigger family picks a single why-now, at most one supporting merchant fact, one action Vera will take, and one CTA as the last line.
   - **Empty triggers:** 13 of the 30 canonical pairs have empty trigger payloads. For these, the why-now is built from merchant data instead of being invented.
   - **Data that contradicts the trigger:** the bot says so. Example: a "perf_dip" whose numbers are up pivots to the merchant's real problem, a lapsed plan.
   - **Unknown trigger kinds:** these are mapped to the closest family by keywords. A heatwave, for example, connects to the category's summer digest.
3. **Guard.** Before anything is sent, four checks run: every number must be grounded, taboo words are blocked, raw internal codes like `ctr_below_peer` can't leak, and only one CTA is allowed, placed last. A failing sentence is removed rather than sent.
4. **Optional polish.** An LLM rewrites for flow under strict rules. The result is accepted only if it keeps exactly the same numbers, quotes, salutation and CTA. Otherwise the deterministic draft ships.
5. **Tick scheduling.** Candidates are ranked by urgency plus evidence strength, and each recipient gets at most one message per tick. Suppression keys stop repeats, and opted-out recipients are never messaged again. Polishing runs in parallel under an 8-second budget (the local judge simulator times out at 15 s), so a slow LLM never causes a timeout.

Replies go through a rule-based router built on English and Hinglish lexicons:

| Reply type | What the bot does |
|---|---|
| Auto-reply (detected per merchant, even across conversations) | Nudges once, then waits, then ends |
| Commitment ("ok let's do it", "haan bhej do") | Delivers the artifact immediately, with no more questions |
| Opt-out | Ends the conversation and suppresses the merchant permanently |
| Abuse | Apologises once and offers STOP; ends if it repeats |
| Off-topic (GST, loans) | Declines honestly and steers back |
| Question | Answered from known facts, never guessed |

The reply language follows the merchant's language turn by turn.

## Tradeoffs

- **Deterministic first.** Wording is a little more templated than a pure LLM writer, in exchange for zero hallucinated numbers, millisecond latency (tick p99 is about 20 ms) and identical output for identical input.
- **In-memory state.** Pushed contexts are also snapshotted to disk, and the public base dataset is bundled as a silent fallback, so a restart mid-test still resolves merchants.
- **Restraint.** The bot holds back a festival trigger flagged as irrelevant to the merchant's category, and any customer message that the customer's consent scope does not cover.

## What would have helped most

- Real slot calendars and service prices per merchant. Appointment triggers had no times, and many merchants had no offers.
- Per-merchant reply history to learn each merchant's own auto-reply text before the first repeat.
- Locality-level search demand, to turn category trends into "searches near you" facts.

## Files

`server.py` (HTTP) · `vera/` (store, facts, playbooks, compose, conversation, llm, bot) · `make_submission.py` (submission.jsonl and the `compose()` contract) · `conversation_handlers.py` (`respond()`) · `tests/` (adversarial tests) · `tools/judge_run.py` (end-to-end harness) · `HOW_IT_WORKS.md` (design walkthrough).

## Run

```
python server.py                      # serves /v1/* on $PORT (default 8080)
python -m unittest discover -s tests  # tests
python make_submission.py             # regenerates submission.jsonl
```

Python 3.10+. Optional environment variables: `LLM_API_KEY` (enables polish), `TEAM_NAME`, `TEAM_MEMBERS`, `CONTACT_EMAIL`.
