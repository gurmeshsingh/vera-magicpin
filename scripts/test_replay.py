"""The three Phase-4 replay scenarios, scripted with per-turn assertions."""
import json, pathlib, sys
sys.path.insert(0, "src")
from fastapi.testclient import TestClient
from vera.api.app import app

c = TestClient(app, raise_server_exceptions=False)
dent = json.load(open("pkg/dataset/categories/dentists.json"))
m = json.load(open("generated/merchants/m_011_dr_sameer_dentist_bangalore.json"))
push = lambda s,i,v,p: c.post("/v1/context", json={"scope":s,"context_id":i,"version":v,"payload":p,"delivered_at":"2026-04-26T10:00:00Z"})
push("category","dentists",1,dent); push("merchant",m["merchant_id"],1,m)
MID = m["merchant_id"]
ok = lambda l,cond,x="": print(f"{'PASS' if cond else 'FAIL'}  {l}" + (f" — {x}" if x else ""))
def reply(cid, msg, turn):
    return c.post("/v1/reply", json={"conversation_id":cid,"merchant_id":MID,
        "from_role":"merchant","message":msg,"received_at":"2026-04-26T10:45:00Z","turn_number":turn}).json()

QUAL = ["would you","do you","can you tell","what if","how about"]
ACT  = ["done","sending","draft","here","confirm","proceed","next"]

print("=== R01 auto-reply hell (4 sends, 4 DIFFERENT conversation ids) ===")
auto = "Thank you for contacting us! Our team will respond shortly."
acts = [reply(f"conv_auto_{i}", auto, i+1)["action"] for i in range(1,5)]
print("   ", " -> ".join(acts))
ok("exits rather than looping", "end" in acts)
ok("at most one probe before exiting", acts.count("send") <= 1, f"{acts.count('send')} send(s)")

print("\n=== R02 intent transition ===")
r = reply("conv_intent", "Ok lets do it. Whats next?", 2)
b = r.get("body","")
ok("action mode", r["action"]=="send")
ok("contains an actioning token", any(w in b.lower() for w in ACT))
ok("contains NO qualifying phrase (harness veto)", not any(w in b.lower() for w in QUAL), b[:70])
r2 = reply("conv_intent", "ok", 3)
ok("second turn does not repeat verbatim", r2.get("body","") != b, r2["action"])

print("\n=== R03 hostile, then off-topic ===")
r = reply("conv_host", "Stop messaging me. This is useless spam.", 2)
ok("hostile -> end", r["action"]=="end")
r = reply("conv_gst", "can you also help me file my GST?", 2)
ok("off-topic stays on mission", r["action"]=="send" and "gst" not in r.get("body","").lower(), r.get("body","")[:60])

print("\n=== R04 questions answered, not deflected ===")
for cid, q, must in [("q1","How much will this cost me?","charge"),
                     ("q2","how long does it take?","two minutes"),
                     ("q3","where did you get those numbers?","dashboard"),
                     ("q4","what is the airspeed velocity of a swallow?","do not have")]:
    r = reply(cid, q, 2)
    body = r.get("body","").lower()
    ok(f"{q[:34]:<34}", r["action"]=="send" and must in body, r.get("body","")[:62])
