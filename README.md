# Vera — magicpin AI Challenge

A stateful HTTP service that plays magicpin's merchant-AI assistant, judged live
over a 60-simulated-minute window.

**No model runs in the request path.** The composer is deterministic, so the
service needs no API key, cannot be rate-limited mid-test, and returns the same
message for the same input every time.

## Run

    python -m venv .venv && ./.venv/bin/pip install -r requirements.txt
    PYTHONPATH=src ./.venv/bin/uvicorn vera.api.app:app --host 0.0.0.0 --port 8080

Or `docker build -t vera-bot . && docker run -p 8080:8080 vera-bot`.

## Test

    ./.venv/bin/python scripts/smoke.py              # endpoints + contract
    PYTHONPATH=src ./.venv/bin/python scripts/test_adaptation.py   # Phase 3 canaries
    PYTHONPATH=src ./.venv/bin/python scripts/test_replay.py       # Phase 4 scenarios
    ./scripts/preflight.sh https://your-host         # against a live URL

## Deploy

`render.yaml` and `fly.toml` are both configured. Two settings are not
negotiable on either:

* **The instance must not sleep.** Render's free plan and Fly's
  `auto_stop_machines` both idle a service out. The judge polls `/v1/healthz`
  every 60 seconds and three consecutive failures end the run.
* **One instance, one worker.** State is in memory and the contract forbids
  losing it mid-test. Two replicas means two half-filled context stores, each
  reporting the wrong count to the warmup gate.

## How it works

    /v1/context   store it, diff it against the version we held, reopen the
                  topics that gained new facts
    /v1/tick      resolve triggers -> consent gate -> compose -> ground-check
                  -> rank -> send the strongest few, or nothing
    /v1/reply     classify the merchant's reply, then answer, wait, or exit
    /v1/healthz   honest per-scope counts; the warmup gate checks them
    /v1/metadata  identity

Composition assembles a message from a **fact ledger** — every number carries
the field path that proves it. A grounding verifier then checks the finished
text against that ledger, and anything untraceable is withheld rather than sent.

    src/vera/context/     versioned store, diffing, resolution, consent
    src/vera/compose/     fact ledger, category voice, angles, engine
    src/vera/grounding/   provenance verification
    src/vera/conversation/ reply classification and composition
    src/vera/api/         the five endpoints
    harness/              our own judge, stricter than the shipped simulator
    notes/                research: data dictionary, judge spec, design debate
    docs/                 the playbook and the product brief

## Things learned by measurement, not assumption

* The briefs advertise a 30-second timeout. The harness enforces
  **5s / 10s / 15s** per endpoint. Building to the documented figure times out
  everywhere.
* `ctr` is **not** `calls / views` — they disagree for 50 of 50 merchants.
  Deriving one from the other hands the judge arithmetic that fails.
* The shipped `judge_simulator.py` never calls the LLM judge under its default
  setting, and its behavioural scenarios return success unconditionally.
* Auto-reply detection must key on **merchant + message signature**, not
  conversation id — the harness sends its four identical messages under four
  different conversation ids.
* The judge's own noise floor is SD 1.3 on an identical message. Differences
  under 3 points mean nothing.
