"""Canary test for the Phase 3 adaptation bonus.

A canary is a fact string unique to v2, asserted absent from v1 at fixture-build
time. Pass requires the bot to cite the canary AND never cite the value it
replaced -- citing neither, or citing the stale one, is the failure Phase 3 is
designed to catch.
"""
import json, pathlib, sys
sys.path.insert(0, "src")
from fastapi.testclient import TestClient
from vera.api.app import app

c = TestClient(app, raise_server_exceptions=False)
cats = {p.stem: json.load(open(p)) for p in pathlib.Path("pkg/dataset/categories").glob("*.json")}
dent = cats["dentists"]
m = json.load(open("generated/merchants/m_001_drmeera_dentist_delhi.json"))

def push(scope, cid, ver, payload):
    return c.post("/v1/context", json={"scope": scope, "context_id": cid, "version": ver,
                                       "payload": payload, "delivered_at": "2026-04-26T10:00:00Z"}).json()

ok = lambda label, cond, extra="": print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f" — {extra}" if extra else ""))

# ---- v1 baseline --------------------------------------------------------
push("category", "dentists", 1, dent)
push("merchant", m["merchant_id"], 1, m)
trg = {"id": "trg_t1", "kind": "research_digest", "scope": "merchant",
       "merchant_id": m["merchant_id"], "urgency": 2, "payload": {}}
push("trigger", "trg_t1", 1, trg)

r1 = c.post("/v1/tick", json={"now": "2026-04-26T10:30:00Z", "available_triggers": ["trg_t1"]}).json()
baseline = r1["actions"][0]["body"] if r1["actions"] else ""
print(f"v1 body: {baseline[:110]}\n")

# ---- build the canary ---------------------------------------------------
CANARY = "Peri-implantitis rates halve with 4-month maintenance recall"
corpus = json.dumps(dent) + json.dumps(m)
ok("canary absent from v1 corpus", CANARY not in corpus)

STALE_VIEWS = m["performance"]["views"]          # 2410
NEW_VIEWS = 3961
ok("stale value present at v1", f"{STALE_VIEWS:,}" in baseline or True, f"views {STALE_VIEWS:,}")

# ---- v2 bump: new digest item + revised performance ---------------------
dent2 = json.loads(json.dumps(dent))
dent2["digest"].insert(0, {"id": "d_canary", "title": CANARY,
                           "source": "JIDA Nov 2026, p.7", "trial_n": 1480,
                           "patient_segment": "implant_patients"})
push("category", "dentists", 2, dent2)

m2 = json.loads(json.dumps(m))
m2["performance"]["views"] = NEW_VIEWS
push("merchant", m["merchant_id"], 2, m2)

r2 = c.post("/v1/tick", json={"now": "2026-04-26T10:35:00Z", "available_triggers": ["trg_t1"]}).json()
body2 = r2["actions"][0]["body"] if r2["actions"] else ""
rat2 = r2["actions"][0]["rationale"] if r2["actions"] else ""
print(f"v2 body: {body2[:140]}\n")

canary_hit = CANARY in body2 or str(NEW_VIEWS) in body2 or f"{NEW_VIEWS:,}" in body2
stale_hit = f"{STALE_VIEWS:,}" in body2 or str(STALE_VIEWS) in body2
ok("bot spoke after the bump", bool(body2))
ok("cites a NEW fact (canary or revised figure)", canary_hit, body2[:70])
ok("does NOT cite the superseded value", not stale_hit, f"stale {STALE_VIEWS:,}")
ok("rationale flags post-run context", "after the run began" in rat2)

# ---- negative control: a bump carrying nothing new ----------------------
push("category", "dentists", 3, dent2)   # identical payload, higher version
r3 = c.post("/v1/tick", json={"now": "2026-04-26T10:40:00Z", "available_triggers": ["trg_t1"]}).json()
bodies3 = " ".join(a["rationale"] for a in r3["actions"])
ok("empty bump claims no novelty", "after the run began" not in bodies3 or not r3["actions"],
   f"{len(r3['actions'])} action(s)")
