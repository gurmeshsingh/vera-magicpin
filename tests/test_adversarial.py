"""Adversarial tests (Phase 6). Run: python -m unittest discover -s tests -v"""
import copy
import json
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)

from vera.bot import Bot  # noqa: E402
from vera.compose import guard_issues, plan, ungrounded_numbers  # noqa: E402
from vera.conversation import classify  # noqa: E402
from vera.facts import Ctx  # noqa: E402

from vera.dataset import load_bundle  # noqa: E402

_B = load_bundle()
CATS, MS, CS, TS = _B["categories"], _B["merchants"], _B["customers"], _B["triggers"]
MEERA = MS["m_001_drmeera_dentist_delhi"]
NOW = "2026-04-26T10:30:00Z"


def trig(kind, payload=None, mid="m_001_drmeera_dentist_delhi", tid=None, scope="merchant", cid=None, urgency=2):
    return {"id": tid or f"t_{kind}_{time.time_ns()}", "scope": scope, "kind": kind, "source": "internal",
            "merchant_id": mid, "customer_id": cid, "payload": payload or {}, "urgency": urgency,
            "suppression_key": f"k_{kind}_{time.time_ns()}", "expires_at": "2026-12-31T00:00:00Z"}


def fresh_bot(llm_transport=None):
    b = Bot(data_dir=None)
    for s, c in CATS.items():
        b.store.put("category", s, 1, c)
    for mid, m in MS.items():
        b.store.put("merchant", mid, 1, m)
    for cid, c in CS.items():
        b.store.put("customer", cid, 1, c)
    if llm_transport:
        b.llm.transport = llm_transport
        b.llm.enabled = True
    return b


def push_and_tick(b, *triggers, now=NOW):
    for t in triggers:
        b.store.put("trigger", t["id"], 1, t)
    return b.tick(now, [t["id"] for t in triggers])["actions"]


class Compose(unittest.TestCase):
    def assertClean(self, ctx, body, draft=None):
        self.assertTrue(body.strip())
        self.assertEqual(ungrounded_numbers(body, ctx), [], body)

    def test_missing_merchant_fields(self):
        m = {"merchant_id": "m_bare", "category_slug": "salons"}
        ctx = Ctx(CATS["salons"], m, trig("perf_dip", mid="m_bare"), None, now=NOW)
        c = plan(ctx)
        self.assertClean(ctx, c.body)
        self.assertTrue(c.body.startswith("Hi there,"), c.body)  # no name at all -> neutral greeting, nothing invented

    def test_missing_trigger_fields(self):
        ctx = Ctx(CATS["dentists"], MEERA, {"merchant_id": MEERA["merchant_id"]}, None, now=NOW)
        c = plan(ctx)
        self.assertClean(ctx, c.body)

    def test_missing_category(self):
        ctx = Ctx({}, MEERA, trig("research_digest", {"top_item_id": "nope"}), None, now=NOW)
        c = plan(ctx)
        self.assertTrue(c.body)

    def test_conflicting_signals_dip_without_dip(self):
        m = copy.deepcopy(MEERA)
        m["performance"]["delta_7d"] = {"views_pct": 0.2, "calls_pct": 0.1}
        ctx = Ctx(CATS["dentists"], m, trig("perf_dip", {"placeholder": True}), None, now=NOW)
        c = plan(ctx)
        self.assertNotIn("dropped", c.body)
        self.assertIn("up", c.body)

    def test_zero_and_negative_metrics(self):
        m = copy.deepcopy(MEERA)
        m["performance"] = {"views": 0, "calls": 0, "ctr": 0, "delta_7d": {"views_pct": -1.0, "calls_pct": 0}}
        m["customer_aggregate"] = {"total_unique_ytd": 0, "lapsed_180d_plus": -5}
        for kind in ("perf_dip", "perf_spike", "milestone_reached", "dormant_with_vera", "renewal_due"):
            ctx = Ctx(CATS["dentists"], m, trig(kind, {"placeholder": True}), None, now=NOW)
            self.assertClean(ctx, plan(ctx).body)

    def test_expired_offer_not_presented_as_live(self):
        m = copy.deepcopy(MEERA)
        m["offers"] = [{"title": "Deep Cleaning @ ₹499", "status": "expired"}]
        ctx = Ctx(CATS["dentists"], m, trig("competitor_opened", {"competitor_name": "X Dental", "distance_km": 2,
                                                                  "their_offer": "Cleaning @ ₹199"}), None, now=NOW)
        self.assertNotIn("your 'Deep Cleaning", plan(ctx).body)

    def test_unseen_trigger_kinds(self):
        for kind, payload in (("weather_heatwave", {"temp_c": 45, "city": "Delhi"}),
                              ("local_news_event", {"headline": "Road closed for repairs"}),
                              ("category_trend_movement", {"query": "clear aligners", "delta_yoy": 0.62}),
                              ("totally_new_kind_xyz", {"foo": "bar", "count": 7}),
                              ("scheduled_recurring", {})):
            ctx = Ctx(CATS["dentists"], MEERA, trig(kind, payload), None, now=NOW)
            c = plan(ctx)
            self.assertClean(ctx, c.body)
            self.assertFalse(guard_issues(c.body, ctx, c.draft), (kind, c.body))

    def test_category_mismatch_customer_kind(self):
        t = TS["trg_081_chronic_refill_due_m_011_dr_sameer_dent"]
        m = MS[t["merchant_id"]]
        ctx = Ctx(CATS["dentists"], m, t, CS[t["customer_id"]], now=NOW)
        c = plan(ctx)
        self.assertEqual(c.send_as, "merchant_on_behalf")
        self.assertNotIn("dawai", c.body.lower())  # no pharmacy language in a dental message

    def test_consent_blocks(self):
        cust = copy.deepcopy(CS["c_001_priya_for_m001"])
        cust["consent"]["scope"] = []
        ctx = Ctx(CATS["dentists"], MEERA, TS["trg_003_recall_due_priya"], cust, now=NOW)
        self.assertTrue(plan(ctx).skip)

    def test_customer_trigger_without_customer(self):
        ctx = Ctx(CATS["dentists"], MEERA, TS["trg_003_recall_due_priya"], None, now=NOW)
        self.assertTrue(plan(ctx).skip)

    def test_irrelevant_festival_held_back(self):
        t = trig("festival_upcoming", {"festival": "Diwali", "days_until": 10, "category_relevance": ["salons"]})
        ctx = Ctx(CATS["dentists"], MEERA, t, None, now=NOW)
        self.assertTrue(plan(ctx).skip)

    def test_extremely_long_context(self):
        cat = copy.deepcopy(CATS["dentists"])
        cat["digest"] = cat["digest"] * 120
        m = copy.deepcopy(MEERA)
        m["conversation_history"] = m["conversation_history"] * 500
        m["signals"] = m["signals"] * 50
        t0 = time.time()
        ctx = Ctx(cat, m, trig("research_digest", {}), None, now=NOW)
        c = plan(ctx)
        self.assertLess(time.time() - t0, 1.0)
        self.assertClean(ctx, c.body)

    def test_all_dataset_triggers_grounded(self):
        for t in TS.values():
            m = MS[t["merchant_id"]]
            cu = CS.get(t.get("customer_id") or "")
            ctx = Ctx(CATS[m["category_slug"]], m, t, cu, now=NOW)
            c = plan(ctx)
            if c.skip:
                continue
            self.assertFalse([i for i in guard_issues(c.body, ctx, c.draft) if i != "too_long"], (t["id"], c.body))


class Tick(unittest.TestCase):
    def test_multiple_triggers_one_merchant_one_message(self):
        b = fresh_bot()
        acts = push_and_tick(b, trig("perf_dip", {"placeholder": True}, urgency=2),
                             trig("regulation_change", {"top_item_id": "d_2026W17_dci_radiograph"}, urgency=4))
        self.assertEqual(len(acts), 1)
        self.assertIn("compliance", acts[0]["body"].lower())  # strongest signal wins

    def test_repeated_trigger_suppressed(self):
        b = fresh_bot()
        t = trig("perf_spike", {"metric": "calls", "delta_pct": 0.3})
        self.assertEqual(len(push_and_tick(b, t)), 1)
        self.assertEqual(push_and_tick(b, t, now="2026-04-26T10:35:00Z"), [])

    def test_duplicate_tick_request_same_answer(self):
        b = fresh_bot()
        t = trig("perf_spike", {"metric": "calls", "delta_pct": 0.3})
        b.store.put("trigger", t["id"], 1, t)
        a1 = b.tick(NOW, [t["id"]])
        a2 = b.tick(NOW, [t["id"]])
        self.assertEqual(a1, a2)
        self.assertEqual(len(a1["actions"]), 1)

    def test_unknown_trigger_id_and_missing_merchant(self):
        b = fresh_bot()
        t = trig("perf_dip", mid="m_does_not_exist")
        b.store.put("trigger", t["id"], 1, t)
        self.assertEqual(b.tick(NOW, ["nope", t["id"], None, 5])["actions"], [])

    def test_twenty_action_cap(self):
        b = fresh_bot()
        ts = [trig("perf_spike", {"metric": "calls", "delta_pct": 0.2}, mid=mid) for mid in list(MS)[:30]]
        self.assertLessEqual(len(push_and_tick(b, *ts)), 20)


class LLMPath(unittest.TestCase):
    def _bot(self, fn):
        return fresh_bot(llm_transport=fn)

    def test_good_polish_accepted(self):
        def good(model, messages):
            draft = messages[1]["content"].split("DRAFT:\n", 1)[1]
            return json.dumps({"body": draft.replace("just landed one worth your time", "just published something useful")})
        b = self._bot(good)
        a = push_and_tick(b, trig("research_digest", {"top_item_id": "d_2026W17_jida_fluoride"}))[0]
        self.assertIn("just published something useful", a["body"])
        self.assertIn("polished", a["rationale"])

    def test_polish_that_adds_numbers_rejected(self):
        def liar(model, messages):
            draft = messages[1]["content"].split("DRAFT:\n", 1)[1]
            return json.dumps({"body": draft + " 3 dentists near you already did this."})
        b = self._bot(liar)
        a = push_and_tick(b, trig("research_digest", {"top_item_id": "d_2026W17_jida_fluoride"}))[0]
        self.assertNotIn("3 dentists", a["body"])

    def test_malformed_llm_output_falls_back(self):
        b = self._bot(lambda m, msg: "Sure! here is your message: not json at all")
        a = push_and_tick(b, trig("perf_spike", {"metric": "calls", "delta_pct": 0.3}))[0]
        self.assertTrue(a["body"])

    def test_llm_exception_falls_back(self):
        def boom(model, messages):
            raise RuntimeError("503")
        b = self._bot(boom)
        self.assertEqual(len(push_and_tick(b, trig("perf_spike", {"metric": "calls", "delta_pct": 0.3}))), 1)

    def test_slow_llm_tick_stays_under_budget(self):
        def slow(model, messages):
            time.sleep(9)
            return "{}"
        b = self._bot(slow)
        b.tick_budget = 3
        t0 = time.time()
        acts = push_and_tick(b, *[trig("perf_spike", {"metric": "calls", "delta_pct": 0.2}, mid=mid) for mid in list(MS)[:8]])
        self.assertLess(time.time() - t0, 5)
        self.assertEqual(len(acts), 8)
        self.assertTrue(all(a["body"] for a in acts))


class Replies(unittest.TestCase):
    def setUp(self):
        self.b = fresh_bot()
        self.a = push_and_tick(self.b, trig("perf_dip", {"metric": "calls", "delta_pct": -0.4}))[0]
        self.turn = 1

    def say(self, msg, conv=None, role="merchant", cid=None):
        self.turn += 1
        return self.b.reply({"conversation_id": conv or self.a["conversation_id"], "merchant_id": self.a["merchant_id"],
                             "customer_id": cid, "from_role": role, "message": msg, "received_at": NOW,
                             "turn_number": self.turn})

    def test_classifier_matrix(self):
        cases = {"ok let's do it": "commit", "haan bhej do": "commit", "STOP": "opt_out", "not interested": "opt_out",
                 "Thank you for contacting us! We will get back to you.": "auto_reply", "busy, baad mein": "later",
                 "no thanks": "decline", "how much will it cost?": "question", "hmm": "ambiguous",
                 "can you file my GST": "off_topic", "you are useless": "abuse", "kar do na": "commit",
                 "we run non-stop on weekends, what do you suggest?": "question", "ok let's not do it": "other"}
        for msg, want in cases.items():
            self.assertEqual(classify(msg)[0], want, msg)

    def test_auto_reply_across_conversations(self):
        canned = "Thanks for reaching out! Our team will get back to you shortly."
        acts = [self.say(canned, conv=f"conv_auto_{i}")["action"] for i in range(4)]
        self.assertIn("end", acts[:3])

    def test_duplicate_reply_request_idempotent(self):
        req = {"conversation_id": self.a["conversation_id"], "merchant_id": self.a["merchant_id"], "customer_id": None,
               "from_role": "merchant", "message": "We have a weird auto text here ok", "received_at": NOW, "turn_number": 2}
        r1, r2 = self.b.reply(dict(req)), self.b.reply(dict(req))
        self.assertEqual(r1, r2)

    def test_intent_goes_to_action(self):
        r = self.say("Ok lets do it. Whats next?")
        self.assertEqual(r["action"], "send")
        low = r["body"].lower()
        self.assertFalse(any(w in low for w in ["would you", "do you", "can you tell", "what if", "how about"]), low)

    def test_opt_out_ends_and_suppresses(self):
        self.assertEqual(self.say("Stop messaging me")["action"], "end")
        self.assertEqual(push_and_tick(self.b, trig("perf_spike", {"metric": "calls", "delta_pct": 0.3})), [])

    def test_hostile_then_off_topic(self):
        r = self.say("You idiots. Can you help me file my GST?")
        self.assertEqual(r["action"], "send")
        self.assertIn("sorry", r["body"].lower())
        self.assertIn("stop", r["body"].lower())

    def test_language_switch_to_hindi(self):
        r = self.say("haan ji bilkul kar dijiye")
        self.assertEqual(r["action"], "send")
        self.assertTrue(any(w in r["body"].lower() for w in ("hai", "kar", "doon", "yeh")), r["body"])

    def test_no_verbatim_repeat_in_conversation(self):
        bodies = [self.a["body"]]
        for msg in ["why?", "why?", "why?", "hmm", "hmm"]:
            r = self.say(msg)
            if r["action"] == "send":
                self.assertNotIn(r["body"], bodies)
                bodies.append(r["body"])

    def test_unknown_conversation_is_adopted(self):
        r = self.say("ok let's do it", conv="conv_never_seen")
        self.assertEqual(r["action"], "send")

    def test_garbage_reply_payload(self):
        self.assertIn(self.b.reply({})["action"], ("send", "wait", "end"))
        self.assertIn(self.b.reply({"message": None, "conversation_id": 5})["action"], ("send", "wait", "end"))

    def test_customer_slot_booking(self):
        b = fresh_bot()
        t = TS["trg_003_recall_due_priya"]
        a = push_and_tick(b, t)[0]
        r = b.reply({"conversation_id": a["conversation_id"], "merchant_id": a["merchant_id"],
                     "customer_id": a["customer_id"], "from_role": "customer", "message": "2", "received_at": NOW,
                     "turn_number": 2})
        self.assertIn("Thu 6 Nov, 5pm", r["body"])


if __name__ == "__main__":
    unittest.main()
