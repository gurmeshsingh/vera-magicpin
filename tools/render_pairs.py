"""Render the 30 canonical test pairs deterministically and print them (dev tool)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vera.compose import guard_issues, plan  # noqa: E402
from vera.facts import Ctx  # noqa: E402

from vera.dataset import load_bundle  # noqa: E402

NOW = sys.argv[1] if len(sys.argv) > 1 else "2026-04-26T10:30:00Z"
_B = load_bundle()
cats, ms, cs, ts, pairs = _B["categories"], _B["merchants"], _B["customers"], _B["triggers"], _B["test_pairs"]
only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
for pr in pairs:
    if only and pr["test_id"] not in only:
        continue
    t, m = ts[pr["trigger_id"]], ms[pr["merchant_id"]]
    c = cs.get(pr.get("customer_id") or "")
    ctx = Ctx(cats.get(m["category_slug"]), m, t, c, now=NOW)
    out = plan(ctx, t.get("suppression_key", ""))
    print(f"\n## {pr['test_id']} {t['kind']} [{out.family}, {out.cta}, {out.send_as}, s={out.strength:.1f}]")
    print(out.body or f"(SKIP: {out.skip})")
    iss = guard_issues(out.body, ctx, out.draft) if out.body else []
    if iss:
        print("   !! ISSUES:", iss)
    print("   rationale:", out.rationale)
