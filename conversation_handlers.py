"""Optional brief §7.4 contract: respond(state, merchant_message) -> dict.

The live bot handles replies through POST /v1/reply (see vera/conversation.py).
This wrapper exposes the same engine as a plain function for offline judging.

    state = {"conversation_id": "...", "merchant_id": "...", "customer_id": None,
             "from_role": "merchant", "turn_number": 2}
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vera.bot import Bot  # noqa: E402

_BOT = Bot(data_dir=Path(__file__).resolve().parent / "dataset")


def respond(state: dict, merchant_message: str) -> dict:
    req = dict(state or {})
    req["message"] = merchant_message
    return _BOT.reply(req)
