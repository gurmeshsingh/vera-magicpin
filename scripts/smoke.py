"""Smoke test: start the app in-process and exercise all five endpoints."""
import sys, json
sys.path.insert(0, "src")
from fastapi.testclient import TestClient
from vera.api.app import app

c = TestClient(app, raise_server_exceptions=False)
ok = lambda label, cond, extra="": print(f"{'PASS' if cond else 'FAIL'}  {label}{(' — ' + extra) if extra else ''}")

# healthz before anything
r = c.get("/v1/healthz"); h = r.json()
ok("healthz 200 + real counts", r.status_code == 200 and h["contexts_loaded"]["merchant"] == 0, json.dumps(h["contexts_loaded"]))

# metadata
ok("metadata 200", c.get("/v1/metadata").status_code == 200)

# context push
push = lambda s, i, v, p: c.post("/v1/context", json={"scope": s, "context_id": i, "version": v, "payload": p, "delivered_at": "2026-04-26T10:00:00Z"}).json()
r1 = push("category", "dentists", 1, {"slug": "dentists", "voice": {"tone": "peer_clinical"}, "digest": [{"id": "d1", "title": "old item"}]})
ok("context accepted", r1.get("accepted") is True)

# IDEMPOTENCY TRAP: equal version must still accept
r2 = push("category", "dentists", 1, {"slug": "dentists"})
ok("equal-version re-push ACCEPTS (warmup trap)", r2.get("accepted") is True, str(r2))

# strictly lower must refuse
push("category", "dentists", 5, {"slug": "dentists", "digest": [{"id": "d1", "title": "old item"}]})
r3 = push("category", "dentists", 2, {"slug": "dentists"})
ok("stale version refused", r3.get("accepted") is False and r3.get("current_version") == 5, str(r3))

# invalid scope
r4 = push("nonsense", "x", 1, {})
ok("invalid scope rejected cleanly", r4.get("accepted") is False and r4.get("reason") == "invalid_scope")

# version bump produces a delta with the NEW fact
push("category", "dentists", 6, {"slug": "dentists", "digest": [{"id": "d1", "title": "old item"}, {"id": "d2", "title": "NEW fluoride trial"}]})
from vera.api.app import store
deltas = store.deltas_for("category", "dentists")
newest = deltas[-1]
found = any("NEW fluoride trial" == v for v in newest.new_facts.values())
ok("version bump records the new fact", found, f"{len(newest.new_facts)} new leaf paths")

# merchant + trigger, then tick
push("merchant", "m_001", 1, {"merchant_id": "m_001", "category_slug": "dentists",
     "identity": {"name": "Dr. Meera's", "languages": ["en","hi"]},
     "performance": {"views": 2410, "calls": 18, "ctr": 0.021},
     "offers": [{"id":"o1","title":"Cleaning @ Rs299","status":"active"},
                {"id":"o2","title":"Deep Clean @ Rs499","status":"expired"}]})
push("trigger", "trg_1", 1, {"id": "trg_1", "kind": "research_digest", "merchant_id": "m_001", "suppression_key": "research:dentists:2026-W17"})
push("trigger", "trg_orphan", 1, {"id": "trg_orphan", "kind": "perf_dip", "merchant_id": "m_999_missing"})

r = c.post("/v1/tick", json={"now": "2026-04-26T10:30:00Z", "available_triggers": ["trg_1", "trg_orphan", "trg_nonexistent"]})
acts = r.json().get("actions", [])
# trg_1 resolves and legitimately composes. The other two must contribute
# nothing: trg_orphan names a merchant we were never pushed, trg_nonexistent
# was never pushed at all. Silence on those is the contract.
refs = {a["trigger_id"] for a in acts}
ok("tick 200 + schema-valid", r.status_code == 200 and isinstance(acts, list))
ok("orphan/unknown triggers produce no action", refs <= {"trg_1"}, f"referenced {refs or 'nothing'}")
ok("composed action is well-formed", all(a.get("body") and a.get("rationale") for a in acts), f"{len(acts)} action(s)")

# active-offers-only rule
from vera.api.app import index
m = store.get("merchant", "m_001")
ok("active offers filter", [o["title"] for o in index.active_offers(m)] == ["Cleaning @ Rs299"])

# healthz counts now real
h = c.get("/v1/healthz").json()["contexts_loaded"]
ok("healthz counts reflect pushes", h == {"category":1,"merchant":1,"customer":0,"trigger":2}, json.dumps(h))

print("\n--- reply state machine ---")
# AUTO-REPLY across DIFFERENT conversation ids (the harness's actual shape)
auto = "Thank you for contacting us! Our team will respond shortly."
results = []
for i in range(1, 5):
    rr = c.post("/v1/reply", json={"conversation_id": f"conv_auto_{i}", "merchant_id": "m_001",
                                   "from_role": "merchant", "message": auto, "turn_number": i+1}).json()
    results.append(rr["action"])
ok("auto-reply detected across separate conversation ids", "end" in results, " -> ".join(results))

# INTENT TRANSITION
rr = c.post("/v1/reply", json={"conversation_id": "conv_intent_1", "merchant_id": "m_002",
                               "from_role": "merchant", "message": "Ok lets do it. Whats next?", "turn_number": 2}).json()
qual = ["would you","do you","can you tell","what if","how about"]
act  = ["done","sending","draft","here","confirm","proceed","next"]
b = rr.get("body","").lower()
ok("intent -> action mode, passes harness veto",
   rr["action"] == "send" and any(w in b for w in act) and not any(w in b for w in qual), rr["action"])

# HOSTILE
rr = c.post("/v1/reply", json={"conversation_id": "conv_hostile", "merchant_id": "m_003",
                               "from_role": "merchant", "message": "Stop messaging me. This is useless spam.", "turn_number": 2}).json()
ok("hostile -> end", rr["action"] == "end")

# OFF-TOPIC
rr = c.post("/v1/reply", json={"conversation_id": "conv_gst", "merchant_id": "m_004",
                               "from_role": "merchant", "message": "can you also help me file my GST?", "turn_number": 3}).json()
ok("off-topic -> stays on mission", rr["action"] == "send" and "gst" not in rr["body"].lower())

# never-500 on garbage
r = c.post("/v1/context", json={"garbage": True})
ok("malformed push never errors", r.status_code == 200 and r.json().get("accepted") is True, str(r.status_code))
r = c.post("/v1/tick", json={"available_triggers": "not-a-list"})
ok("malformed tick returns valid schema", r.status_code == 200 and "actions" in r.json())
