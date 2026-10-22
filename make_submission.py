"""Generate submission.jsonl for the 30 canonical test pairs.

    python make_submission.py                 # deterministic (no LLM needed)
    LLM_API_KEY=gsk_... python make_submission.py   # with LLM polish

Also exposes `compose(category, merchant, trigger, customer)` as the brief's
bot.py contract asks.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from vera.bot import Bot  # noqa: E402

_BOT = None
NOW = os.environ.get("SUBMISSION_NOW", "2026-04-26T10:30:00Z")


def compose(category: dict, merchant: dict, trigger: dict, customer: dict | None = None) -> dict:
    """Brief §7.1 contract: returns body, cta, send_as, suppression_key, rationale."""
    global _BOT
    if _BOT is None:
        _BOT = Bot(data_dir=None)
    out = _BOT.compose_one(category, merchant, trigger, customer, now=NOW)
    return {k: out[k] for k in ("body", "cta", "send_as", "suppression_key", "rationale")}


def main(out_path: str = "submission.jsonl") -> None:
    from vera.dataset import load_bundle
    b = load_bundle()
    cats, ms, cs, ts = b["categories"], b["merchants"], b["customers"], b["triggers"]
    with open(out_path, "w", encoding="utf-8") as fh:
        for p in b["test_pairs"]:
            m = ms[p["merchant_id"]]
            res = compose(cats[m["category_slug"]], m, ts[p["trigger_id"]], cs.get(p.get("customer_id") or ""))
            fh.write(json.dumps({"test_id": p["test_id"], **res}, ensure_ascii=False) + "\n")
    print(f"wrote {len(b['test_pairs'])} lines to {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "submission.jsonl")
