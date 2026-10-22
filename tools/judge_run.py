"""End-to-end harness: drives the HTTP server the way the magicpin judge does.

    python tools/judge_run.py [base_url]

Checks contracts, latency, grounding, anti-repetition, reply routing,
mid-test context injection and unseen trigger kinds. Prints a report and exits
non-zero if any hard check fails.
"""
import copy
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vera.compose import ungrounded_numbers  # noqa: E402
from vera.facts import Ctx  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
FAILS, NOTES, LAT = [], [], {"tick": [], "reply": [], "context": []}


def call(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=35) as r:
            code, out = r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        code, out = e.code, json.loads(e.read() or b"{}")
    return code, out, time.time() - t0


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
    return cond


from vera.dataset import load_bundle  # noqa: E402

_B = load_bundle()
cats, ms, cs, ts = _B["categories"], _B["merchants"], _B["customers"], _B["triggers"]

# ---------------------------------------------------------------- 1. warmup + contracts
call("POST", "/v1/teardown", {})
c, h, _ = call("GET", "/v1/healthz")
check(c == 200 and h.get("status") == "ok", "healthz not ok")
c, m, _ = call("GET", "/v1/metadata")
check(c == 200 and all(k in m for k in ("team_name", "model", "approach", "version")), "metadata incomplete")
for scope, items in (("category", cats), ("merchant", ms), ("customer", cs)):
    for cid, payload in items.items():
        c, r, dt = call("POST", "/v1/context", {"scope": scope, "context_id": cid, "version": 1, "payload": payload,
                                                "delivered_at": "2026-04-26T10:00:00Z"})
        LAT["context"].append(dt)
        check(c == 200 and r.get("accepted"), f"context push failed {scope}/{cid}: {c} {r}")
c, h, _ = call("GET", "/v1/healthz")
check(h["contexts_loaded"] == {"category": 5, "merchant": 50, "customer": 200, "trigger": 0},
      f"warmup counts wrong: {h['contexts_loaded']}")
cid0 = next(iter(ms))
c, r, _ = call("POST", "/v1/context", {"scope": "merchant", "context_id": cid0, "version": 1, "payload": ms[cid0], "delivered_at": "x"})
check(c == 200 and r.get("accepted"), f"idempotent re-post should be 200 accepted, got {c} {r}")
c, r, _ = call("POST", "/v1/context", {"scope": "merchant", "context_id": cid0, "version": 0, "payload": ms[cid0], "delivered_at": "x"})
check(c == 409 and r.get("reason") == "stale_version", f"stale version should be 409, got {c} {r}")
c, r, _ = call("POST", "/v1/context", {"scope": "planet", "context_id": "x", "version": 1, "payload": {}, "delivered_at": "x"})
check(c == 400, f"bad scope should be 400, got {c}")
c, r, _ = call("POST", "/v1/context", raw=b"{not json")
check(c == 400, f"malformed JSON should be 400, got {c}")
c, r, _ = call("POST", "/v1/tick", raw=b"garbage")
check(c == 200 and r == {"actions": []}, f"garbage tick should give empty actions, got {c} {r}")
c, r, _ = call("POST", "/v1/reply", raw=b"")
check(c == 200 and r.get("action") in ("send", "wait", "end"), f"empty reply body mishandled: {c} {r}")

# ---------------------------------------------------------------- 2. triggers + ticks
for tid, t in ts.items():
    call("POST", "/v1/context", {"scope": "trigger", "context_id": tid, "version": 1, "payload": t, "delivered_at": "x"})
all_actions = []
ids = list(ts)
NOW = "2026-04-26T10:30:00Z"
for i in range(0, len(ids), 10):
    c, r, dt = call("POST", "/v1/tick", {"now": NOW, "available_triggers": ids[i:i + 10]})
    LAT["tick"].append(dt)
    check(c == 200 and isinstance(r.get("actions"), list), "tick bad response")
    all_actions += r["actions"]
# second pass picks up triggers deferred by the one-per-recipient rule
c, r, dt = call("POST", "/v1/tick", {"now": "2026-04-26T10:35:00Z", "available_triggers": ids})
LAT["tick"].append(dt)
all_actions += r["actions"]
c, r, dt = call("POST", "/v1/tick", {"now": "2026-04-26T10:40:00Z", "available_triggers": ids})
all_actions += r["actions"]
fired = [a["trigger_id"] for a in all_actions]
check(len(fired) == len(set(fired)), "a trigger was sent twice")
REQ = ("conversation_id", "merchant_id", "customer_id", "send_as", "trigger_id", "template_name", "template_params",
       "body", "cta", "suppression_key", "rationale")
convs = set()
for a in all_actions:
    check(all(k in a for k in REQ), f"action missing keys: {set(REQ) - set(a)}")
    check(bool(a["body"].strip()), f"empty body for {a['trigger_id']}")
    check(a["conversation_id"] not in convs, "conversation id reused")
    convs.add(a["conversation_id"])
    t = ts[a["trigger_id"]]
    m = ms[a["merchant_id"]]
    cu = cs.get(a.get("customer_id") or "")
    ctx = Ctx(cats[m["category_slug"]], m, t, cu, now=NOW)
    # derived numbers are registered during planning; recompute them
    from vera.compose import plan as _plan
    _plan(ctx, "")
    bad = ungrounded_numbers(a["body"], ctx)
    check(not bad, f"ungrounded numbers {bad} in {a['trigger_id']}: {a['body'][:120]}")
    if t.get("scope") == "customer":
        check(a["send_as"] == "merchant_on_behalf", f"customer trigger not sent on behalf: {a['trigger_id']}")
NOTES.append(f"{len(all_actions)} of {len(ts)} triggers produced messages "
             f"(rest skipped: consent/missing customer). Unique bodies: {len({a['body'] for a in all_actions})}")

# ---------------------------------------------------------------- 3. conversations
SCRIPTS = {
    "commit": ["Ok lets do it. Whats next?", "yes go ahead", "thanks"],
    "question_then_commit": ["How much does this cost?", "when can you do it?", "ok let's do it"],
    "auto": ["Thank you for contacting us! Our team will respond shortly."] * 4,
    "hindi_auto": ["Aapki jaankari ke liye bahut-bahut shukriya. Main aapki yeh sabhi baatein team tak pahuncha deti hoon."] * 4,
    "hostile_gst": ["You guys are idiots. Can you help me file my GST?", "Still useless"],
    "opt_out": ["Stop messaging me. This is useless spam."],
    "later": ["busy right now, baad mein baat karte hain"],
    "hinglish_commit": ["haan bhej do", "theek hai kar do"],
    "curveball": ["We already run a Diwali offer, what else should I do?", "what is your name?", "ok sure"],
    "decline": ["no thanks"],
}
outcomes = {}
RESERVED = {"m_001_drmeera_dentist_delhi", "m_009_apollo_pharmacy_jaipur", "m_005_pizzajunction_restaurant_delhi"}
merchant_actions = [a for a in all_actions if a["send_as"] == "vera" and a["merchant_id"] not in RESERVED]
for i, (name, msgs) in enumerate(SCRIPTS.items()):
    a = merchant_actions[i % len(merchant_actions)]
    sent = [a["body"]]
    trail = []
    for turn, msg in enumerate(msgs, start=2):
        c, r, dt = call("POST", "/v1/reply", {"conversation_id": a["conversation_id"], "merchant_id": a["merchant_id"],
                                              "customer_id": None, "from_role": "merchant", "message": msg,
                                              "received_at": "2026-04-26T10:50:00Z", "turn_number": turn})
        LAT["reply"].append(dt)
        check(c == 200 and r.get("action") in ("send", "wait", "end"), f"bad reply action {r}")
        if r.get("action") == "send":
            check(bool(r.get("body", "").strip()), "send with empty body")
            check(r["body"] not in sent, f"repeated body in {name}")
            sent.append(r["body"])
        trail.append((msg[:40], r.get("action"), (r.get("body") or r.get("rationale") or "")[:150]))
        if r.get("action") == "end":
            break
    outcomes[name] = trail

exp = {"auto": "end", "hindi_auto": "end", "opt_out": "end", "decline": "end", "later": "wait"}
for name, want in exp.items():
    check(outcomes[name][-1][1] == want, f"{name}: expected final {want}, got {outcomes[name][-1][1]}")
check(outcomes["commit"][0][1] == "send" and "?" not in outcomes["commit"][0][2].split("\"")[0][:40],
      "commit should go straight to action")
q = ["would you", "do you", "can you tell", "what if", "how about"]
check(not any(w in outcomes["commit"][0][2].lower() for w in q), "commit reply contains a qualifying question")
check(outcomes["hostile_gst"][0][1] == "send" and "gst" in outcomes["hostile_gst"][0][2].lower() or
      "tax" in outcomes["hostile_gst"][0][2].lower(), "hostile+GST should decline GST and steer back")

# opt-out suppression: new trigger for the opted-out merchant must not be sent
oo = merchant_actions[list(SCRIPTS).index("opt_out") % len(merchant_actions)]["merchant_id"]
t_new = copy.deepcopy(ts[next(t for t in ts if ts[t]["merchant_id"] == oo)])
t_new["id"], t_new["suppression_key"] = "trg_after_optout", "after_optout"
call("POST", "/v1/context", {"scope": "trigger", "context_id": "trg_after_optout", "version": 1, "payload": t_new, "delivered_at": "x"})
c, r, _ = call("POST", "/v1/tick", {"now": NOW, "available_triggers": ["trg_after_optout"]})
check(r["actions"] == [], "opted-out merchant was messaged again")

# ---------------------------------------------------------------- 4. adaptive context injection
den = copy.deepcopy(cats["dentists"])
den["digest"].append({"id": "d_2026W18_new_sealant", "kind": "research", "title": "Bioactive sealants cut pit-and-fissure caries 41% over 24 months",
                      "source": "IJDR May 2026, p.22", "trial_n": 860, "patient_segment": "pediatric",
                      "summary": "Randomised trial in 6-12 year olds; bioactive glass sealants retained 89% at 24 months.",
                      "actionable": "Offer sealants at the next pediatric recall"})
c, r, _ = call("POST", "/v1/context", {"scope": "category", "context_id": "dentists", "version": 2, "payload": den, "delivered_at": "x"})
check(c == 200, "category v2 push failed")
meera = copy.deepcopy(ms["m_001_drmeera_dentist_delhi"])
meera["performance"]["views"], meera["performance"]["calls"] = 3105, 11
meera["performance"]["delta_7d"] = {"views_pct": 0.29, "calls_pct": -0.39}
call("POST", "/v1/context", {"scope": "merchant", "context_id": meera["merchant_id"], "version": 2, "payload": meera, "delivered_at": "x"})
inj = [
    {"id": "trg_inj_research", "scope": "merchant", "kind": "research_digest", "source": "external", "merchant_id": meera["merchant_id"],
     "customer_id": None, "payload": {"category": "dentists"}, "urgency": 2, "suppression_key": "inj:research", "expires_at": "2026-05-10T00:00:00Z"},
    {"id": "trg_inj_dip", "scope": "merchant", "kind": "perf_dip", "source": "internal", "merchant_id": meera["merchant_id"],
     "customer_id": None, "payload": {"placeholder": True}, "urgency": 4, "suppression_key": "inj:dip", "expires_at": "2026-05-10T00:00:00Z"},
    {"id": "trg_inj_heat", "scope": "merchant", "kind": "weather_heatwave", "source": "external", "merchant_id": "m_009_apollo_pharmacy_jaipur",
     "customer_id": None, "payload": {"city": "Jaipur", "temp_c": 44, "days": 3}, "urgency": 3, "suppression_key": "inj:heat", "expires_at": "2026-05-10T00:00:00Z"},
    {"id": "trg_inj_news", "scope": "merchant", "kind": "local_news_event", "source": "external", "merchant_id": "m_005_pizzajunction_restaurant_delhi",
     "customer_id": None, "payload": {"headline": "Metro Pink Line closed Saturday for maintenance", "date": "2026-05-02"}, "urgency": 2,
     "suppression_key": "inj:news", "expires_at": "2026-05-10T00:00:00Z"},
]
newcust = {"customer_id": "c_901_neha_for_m001", "merchant_id": meera["merchant_id"],
           "identity": {"name": "Neha", "language_pref": "hi-en mix", "age_band": "30-40"},
           "relationship": {"first_visit": "2025-06-02", "last_visit": "2025-10-20", "visits_total": 3, "services_received": ["cleaning", "scaling"]},
           "state": "lapsed_soft", "preferences": {"preferred_slots": "weekend_morning"},
           "consent": {"opted_in_at": "2025-06-02", "scope": ["recall_reminders"]}}
call("POST", "/v1/context", {"scope": "customer", "context_id": newcust["customer_id"], "version": 1, "payload": newcust, "delivered_at": "x"})
inj.append({"id": "trg_inj_recall", "scope": "customer", "kind": "recall_due", "source": "internal", "merchant_id": meera["merchant_id"],
            "customer_id": newcust["customer_id"], "payload": {"service_due": "6_month_cleaning", "last_service_date": "2025-10-20",
            "due_date": "2026-04-20", "available_slots": [{"iso": "2026-04-28T10:00:00+05:30", "label": "Sat 2 May, 10am"},
            {"iso": "2026-04-29T11:00:00+05:30", "label": "Sun 3 May, 11am"}]}, "urgency": 3, "suppression_key": "inj:recall",
            "expires_at": "2026-05-10T00:00:00Z"})
for t in inj:
    call("POST", "/v1/context", {"scope": "trigger", "context_id": t["id"], "version": 1, "payload": t, "delivered_at": "x"})
got = {}
for t in inj:
    c, r, dt = call("POST", "/v1/tick", {"now": "2026-04-26T11:00:00Z", "available_triggers": [t["id"]]})
    LAT["tick"].append(dt)
    got[t["id"]] = r["actions"][0]["body"] if r["actions"] else "(no action)"
check("IJDR" in got["trg_inj_research"] or "sealant" in got["trg_inj_research"].lower(), "new digest item not used")
check("39%" in got["trg_inj_dip"], "updated performance numbers not used in dip message")
check(got["trg_inj_recall"] != "(no action)" and "Neha" in got["trg_inj_recall"], "mid-test customer recall not sent")
check(got["trg_inj_heat"] != "(no action)", "unseen trigger kind (heatwave) produced nothing")

# ---------------------------------------------------------------- report
def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))] if v else 0


print("=" * 70)
for k, v in LAT.items():
    print(f"latency {k:8s} n={len(v):4d}  p50={pct(v, .5) * 1000:6.1f}ms  p99={pct(v, .99) * 1000:6.1f}ms  max={max(v or [0]) * 1000:6.1f}ms")
for n in NOTES:
    print("note:", n)
print("\nCONVERSATIONS")
for name, trail in outcomes.items():
    print(f"  [{name}]")
    for msg, act, txt in trail:
        print(f"     merchant: {msg!r:44} -> {act:5s} | {txt}")
print("\nINJECTION / UNSEEN TRIGGERS")
for k, v in got.items():
    print(f"  {k}: {v}")
print("\n" + ("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} FAILURES:\n  - " + "\n  - ".join(FAILS[:40])))
sys.exit(1 if FAILS else 0)
