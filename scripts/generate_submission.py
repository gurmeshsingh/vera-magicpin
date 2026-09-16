"""Compose our message for each of the 30 canonical test pairs.

This is challenge-brief.md §7.2. Every line is produced by the same composer
the live service runs, through the same grounding gate -- no special path.
"""
import json, pathlib, sys
sys.path.insert(0, "src")
from vera.compose.engine import compose
from vera.compose.facts import FactLedger
from vera.grounding.verify import verify, Severity

G = pathlib.Path("generated")
cats = {p.stem: json.loads(p.read_text()) for p in pathlib.Path("pkg/dataset/categories").glob("*.json")}
merch = {json.loads(p.read_text())["merchant_id"]: json.loads(p.read_text()) for p in G.glob("merchants/*.json")}
cust = {json.loads(p.read_text())["customer_id"]: json.loads(p.read_text()) for p in G.glob("customers/*.json")}
trig = {json.loads(p.read_text())["id"]: json.loads(p.read_text()) for p in G.glob("triggers/*.json")}
pairs = json.loads((G / "test_pairs.json").read_text())["pairs"]

out, silent, ungrounded = [], 0, 0
for p in pairs:
    m = merch.get(p["merchant_id"]); t = trig.get(p["trigger_id"])
    c = cats.get((m or {}).get("category_slug"))
    cu = cust.get(p["customer_id"]) if p.get("customer_id") else None
    if not (m and t and c):
        silent += 1
        out.append({"test_id": p["test_id"], "body": "", "cta": "none",
                    "send_as": "vera", "suppression_key": "",
                    "rationale": "Context unresolvable; no message."})
        continue
    o = compose(m, c, t, cu)
    if o is None:
        silent += 1
        out.append({"test_id": p["test_id"], "body": "", "cta": "none",
                    "send_as": "merchant_on_behalf" if cu else "vera",
                    "suppression_key": "",
                    "rationale": "Nothing clears the evidence floor for this pair; staying silent."})
        continue
    v = verify(o.body, FactLedger.build(m, c, t, cu), rationale=o.rationale,
               contexts=[m, c, t] + ([cu] if cu else []))
    if any(x.severity is Severity.ERROR for x in v):
        ungrounded += 1
    out.append({"test_id": p["test_id"], "body": o.body, "cta": o.cta,
                "send_as": o.send_as, "suppression_key": o.suppression_key,
                "rationale": o.rationale})

pathlib.Path("submission.jsonl").write_text(
    "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n")
print(f"wrote submission.jsonl: {len(out)} lines, {silent} silent, {ungrounded} ungrounded")
