# Submission

Form: https://partners.magicpin.com/vera/ai-challenge  ("Submit entry")

| Field | Value |
|---|---|
| Full name | Gurmesh Singh |
| Email | gurmeshsingh120@gmail.com |
| Phone number | *(yours — I do not have it)* |
| Submission URL | `https://vera-magicpin-gs.onrender.com` |
| LinkedIn (optional) | *(yours)* |

## Before you submit

1. Run `./scripts/keepwarm.sh` and leave it running. A free Render instance
   idles out after ~15 minutes and cold-starts in 50+ seconds; the judge's
   first health poll landing on a cold start is an avoidable failure.
2. Confirm the service answers: `./scripts/preflight.sh https://vera-magicpin-gs.onrender.com`

## Known risk, accepted

Measured on the deployed free instance: **4 health-check failures in 30 probes
(13.3%)**, max 1 consecutive, median latency 1.14s. The judge disqualifies on 3
consecutive failures, which works out at roughly a **7.6% chance the run does
not complete**. This is free-tier resource contention, not idle spin-down — the
keep-warm script does not address it. Upgrading to Render Starter removes it.

## What the bot does

Five endpoints, stateful for the whole window, deterministic, no model in the
request path — so no API key, no rate limit, no provider timeout.

- Composes from a **fact ledger**: every number carries the field path proving it
- A **grounding verifier** withholds any message whose claims cannot be traced
- **Restraint**: 4 sends per tick, ~48 across a 12-tick window, not 240
- **Adaptation**: cites facts that arrive mid-run, never the value they replaced
- **Conversation**: detects auto-replies across conversation ids, switches to
  action mode on commitment, exits on hostility, answers questions from facts
  and admits when it cannot
