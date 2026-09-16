Multi-turn state per conversation_id. Drives /v1/reply.
  state.py       turns, what was said, what the merchant signalled
  autoreply.py   WA Business canned-reply detection (verbatim repeat 3+ = auto-reply)
  intent.py      explicit-intent transition: stop qualifying, start acting
  exit.py        graceful exit: not-interested, hostile, or 3 unanswered nudges
