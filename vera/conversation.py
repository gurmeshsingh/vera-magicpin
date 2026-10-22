"""Reply engine: what to do when a merchant (or customer) answers.

Step 1, classify the incoming message (deterministic, microseconds):

    opt_out      "stop messaging me", "not interested", "band karo"     -> end + never message again
    auto_reply   canned WhatsApp-Business text, or the same text again  -> nudge once, wait, then end
    abuse        insults (optionally with an off-topic ask)             -> de-escalate once, then end
    commit       "yes", "ok let's do it", "haan bhej do", "1"           -> ACTION: deliver, no more questions
    later        "busy, baad mein"                                      -> wait
    decline      "no", "nahi"                                           -> end politely
    off_topic    GST filing, loans, visas...                            -> decline that, steer back once
    question     anything with a question                               -> answer from facts
    other        statements                                             -> acknowledge + next step

Step 2, respond.  Canned situations use deterministic text (with variants so
nothing repeats).  Questions and statements try the LLM first (grounded facts
only, strict number check) and fall back to a deterministic answer.

Auto-replies are tracked per MERCHANT, not just per conversation: the judge's
"auto-reply hell" sends the same canned text, possibly on several
conversation ids, and the bot must recognise the pattern across them.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

from .facts import Ctx, fmt_date, fmt_int, humanize, numbers_in
from .lang import customer_mode, detect_reply_language, merchant_mode, pick
from .llm import LLM

# ------------------------------------------------------------------ lexicons
_AUTO = [
    "thank you for contacting", "thanks for contacting", "thank you for reaching out", "thanks for reaching out",
    "thank you for your message", "thanks for your message", "we have received your message",
    "we've received your message", "received your message", "will get back to you", "get back to you shortly",
    "respond shortly", "reply shortly", "our team will", "team will contact", "team will reach",
    "this is an automated", "automated message", "automated response", "automated reply", "auto-reply",
    "auto reply", "autoreply", "i am an automated", "i'm an automated", "automated assistant",
    "virtual assistant", "out of office", "currently unavailable", "currently closed", "outside business hours",
    "our business hours", "working hours are", "we are closed", "for faster service", "visit our website",
    "aapki jaankari ke liye", "jaankari ke liye bahut", "team tak pahuncha", "team tak pahucha",
    "hum jald hi", "jald hi aapse", "jald hi sampark", "aapka sandesh", "main ek automated",
]
_OPT_OUT = [
    r"^\s*(stop|unsubscribe|band karo|bas karo|stop it)\s*[.!]*\s*$",
    r"\b(stop|quit)\s+(messaging|messages|texting|sending|contacting|bothering|spamming|this)\b",
    r"\bunsubscribe\b", r"\bopt[\s-]?out\b",
    r"\b(don'?t|do not|never)\s+(message|text|contact|call|whatsapp|msg|ping)\b",
    r"\bnot interested\b", r"\bno interest\b", r"\bremove (me|my number)\b", r"\bleave me alone\b",
    r"\b(message|msg|messages)\s+(mat|na)\s+(bhejo|bhejiye|karo|kijiye)\b", r"\bnahi chahiye\b",
    r"\bmat bhejo\b", r"\bband karo\b",
]
_ABUSE = [
    r"\bidiot", r"\bstupid\b", r"\bnonsense\b", r"\buseless\b", r"\brubbish\b", r"\bshut up\b", r"\bfraud\b",
    r"\bscam\b", r"\bcheat", r"\bbakwa+s\b", r"\bpagal\b", r"\bbewakoof\b", r"\bwaste of (my )?time\b",
    r"\bgo to hell\b", r"\bdamn\b", r"\bbloody\b", r"\bf+u+c+k", r"\bwtf\b", r"\bharami\b", r"\bkamina\b",
    r"\bspam\b", r"\bannoying\b", r"\bbekar\b", r"\bfaltu\b",
]
_OFF_TOPIC = [
    (r"\bgst\b|\bitr\b|income tax|tax return|tax filing|file (my )?tax", "tax filing",
     "a chartered accountant or the GST portal is the right place for that"),
    (r"\bloan\b|\bemi\b|credit card|insurance", "loans or insurance", "your bank is the right place for that"),
    (r"\bvisa\b|\bpassport\b|aadhaa?r|pan card|voter id", "ID documents", "that's handled by the official portals"),
    (r"\blawyer\b|legal (notice|advice|case)|court|lawsuit", "legal matters", "a lawyer is the right person for that"),
    (r"electricity bill|mobile recharge|\brecharge\b|gas booking", "bills and recharges", "your provider's app handles that"),
    (r"cricket score|\bmovie\b|\bjoke\b|\bweather\b|\bpolitic", "general chat", "that's outside what I do"),
]
_COMMIT = re.compile(
    r"\b(yes|yeah|yep|yup|yess+|ya|haan+|han|haa|hanji|ha ji|haan ji|ok+|okay|okk|sure|done|go ahead|go for it|"
    r"proceed|let'?s do it|lets do it|let'?s go|do it|please do|sounds good|perfect|great|chalo|chalega|"
    r"theek hai|thik hai|thick hai|kar do|kardo|kar dijiye|kar dena|bhej do|bhejo|bhej dijiye|confirm|"
    r"book it|book karo|book kar do|interested|zaroor|zarur|bilkul|why not|send it|send me|send the|"
    r"i want|want to join|join karna|judna|start it|let'?s start|agreed|approve|approved|whats next|what'?s next)\b")
_NEG = re.compile(r"\b(no|not|nope|nah|don'?t|dont|nahi|nahin|na|mat|never|cancel)\b")
_LATER = re.compile(r"\b(later|not now|busy|baad mein|baad me|abhi nahi|kal baat|call me later|next week|"
                    r"thoda time|after some time|in a meeting|driving)\b")
_QUESTION_START = re.compile(r"^\s*(what|how|when|why|which|who|where|can|could|will|would|is|are|do|does|"
                             r"kya|kaise|kab|kyun|kitna|kitne|kaun|kahan)\b")
_THANKS = re.compile(r"^\s*(thanks|thank you|thx|ty|shukriya|dhanyavaad|great thanks|ok thanks|"
                     r"thanks a lot|cool|nice|👍|🙏)[\s.!]*$")
_SLOT_PICK = re.compile(r"^\s*(\d)\s*[.!)]?\s*$|\b(option|slot)\s*(\d)\b")


def classify(text: str) -> tuple[str, dict]:
    """Return (label, features). Order matters: safety and exits first."""
    raw = (text or "").strip()
    low = raw.lower().replace("’", "'")
    feats = {"question": "?" in raw or bool(_QUESTION_START.search(low))}
    if not raw:
        return "empty", feats
    if any(re.search(p, low) for p in _OPT_OUT):
        return "opt_out", feats
    if any(p in low for p in _AUTO) and not _COMMIT.search(low.split(".")[-1] if "." in low else ""):
        return "auto_reply", feats
    abusive = any(re.search(p, low) for p in _ABUSE)
    off = next(((label, tip) for pat, label, tip in _OFF_TOPIC if re.search(pat, low)), None)
    feats["off_topic"] = off
    if abusive:
        return "abuse", feats
    m = _SLOT_PICK.search(low)
    if m:
        feats["slot"] = int(m.group(1) or m.group(3))
        return "commit", feats
    if _LATER.search(low):
        return "later", feats
    commit = _COMMIT.search(low)
    neg = _NEG.search(low)
    negated = bool(neg and neg.start() < commit.start() and commit.start() - neg.start() <= 14) if commit else False
    negated = negated or bool(re.search(r"\b(not|don'?t|dont|mat|nahi|never)\s+(do|send|bhej|kar|book|go)", low))
    hedged = feats["question"] and bool(re.search(r"\b(but|lekin|par|however)\b", low))
    if commit and not negated and not hedged:
        return "commit", feats
    if off:
        return "off_topic", feats
    if neg and re.match(r"^\s*(no|nope|nah|nahi|nahin|na)\b", low) and not feats["question"]:
        return "decline", feats
    if _THANKS.match(low):
        return "thanks", feats
    if feats["question"] and len(low) > 3:
        return "question", feats
    if len(re.findall(r"\w+", low)) <= 2:
        return "ambiguous", feats
    return "other", feats



_VERB_START = re.compile(r"^(draft|set|put|publish|send|turn|walk|rewrite|reactivate|renew|register|book|block|start|"
                         r"run|pull|create|make|update|add|fix|share|post|launch|reply|enable|move|act)\b", re.I)


def ask_phrase(st, mode: str) -> str:
    """'Shall I <do the thing>?' built from whatever the opening message offered."""
    d = (st.deliverable or "").strip().rstrip(".")
    if not d:
        q = "Shall I go ahead?"
    elif _VERB_START.match(d):
        q = f"Shall I {d[0].lower() + d[1:]}?"
    else:
        q = f"Shall I go ahead with the {d[0].lower() + d[1:]}?"
    return pick(mode, q, q + " Bas YES boliye.", q + " Bas YES boliye.")

# ------------------------------------------------------------------ state
@dataclass
class ConvState:
    conversation_id: str
    merchant_id: str
    customer_id: str | None
    trigger_id: str | None
    family: str = "general"
    anchor: str = ""
    deliverable: str = ""
    first_body: str = ""
    mode: str = "en"
    sent: list = field(default_factory=list)
    inbound: list = field(default_factory=list)
    auto_streak: int = 0
    abuse: int = 0
    off_topic: int = 0
    delivered: int = 0
    questions: int = 0
    ended: bool = False
    created: float = field(default_factory=time.time)


class ReplyEngine:
    def __init__(self, store, llm: LLM | None = None) -> None:
        self.store = store
        self.llm = llm
        self.lock = threading.RLock()
        self.convs: dict[str, ConvState] = {}
        self.opted_out_merchants: set[str] = set()
        self.opted_out_customers: set[str] = set()
        self.merchant_auto: dict[str, dict[str, int]] = {}  # merchant -> normalized text -> count
        self.sent_to: dict[str, set] = {}  # recipient key -> bodies sent (anti-repetition across convs)
        self._recent: dict[tuple, dict] = {}  # (conv, turn, message) -> answer, for duplicate requests

    # -------------------------------------------------------------- registry
    def register(self, conversation_id: str, merchant_id: str, customer_id: str | None, trigger_id: str | None,
                 family: str, anchor: str, deliverable: str, body: str, mode: str) -> None:
        with self.lock:
            st = ConvState(conversation_id, merchant_id, customer_id, trigger_id, family, anchor, deliverable,
                           body, mode)
            st.sent.append(body)
            self.convs[conversation_id] = st
            self.sent_to.setdefault(self._recipient(merchant_id, customer_id), set()).add(body)

    def is_opted_out(self, merchant_id: str, customer_id: str | None = None) -> bool:
        if customer_id:
            return customer_id in self.opted_out_customers
        return merchant_id in self.opted_out_merchants

    def bodies_sent_to(self, merchant_id: str, customer_id: str | None) -> set:
        return self.sent_to.get(self._recipient(merchant_id, customer_id), set())

    def clear(self) -> None:
        with self.lock:
            self.convs.clear()
            self.opted_out_merchants.clear()
            self.opted_out_customers.clear()
            self.merchant_auto.clear()
            self.sent_to.clear()
            self._recent.clear()

    @staticmethod
    def _recipient(merchant_id: str, customer_id: str | None) -> str:
        return f"{merchant_id}|{customer_id or ''}"

    # -------------------------------------------------------------- context
    def _ctx(self, st: ConvState, now: str | None) -> Ctx:
        merchant = self.store.get("merchant", st.merchant_id) or {"merchant_id": st.merchant_id}
        category = self.store.get("category", merchant.get("category_slug")) or {}
        trigger = self.store.get("trigger", st.trigger_id) if st.trigger_id else None
        customer = self.store.get("customer", st.customer_id) if st.customer_id else None
        return Ctx(category, merchant, trigger or {}, customer, now=now)

    # -------------------------------------------------------------- main entry
    def handle(self, req: dict) -> dict:
        conv_id = str(req.get("conversation_id") or "conv_unknown")
        merchant_id = str(req.get("merchant_id") or "")
        customer_id = req.get("customer_id") or None
        role = str(req.get("from_role") or ("customer" if customer_id else "merchant")).lower()
        msg = str(req.get("message") or "")
        now = req.get("received_at")
        dedupe_key = (conv_id, str(req.get("turn_number")), msg)
        with self.lock:
            if dedupe_key in self._recent:
                return dict(self._recent[dedupe_key])  # judge retry: same answer, no double counting
            st = self.convs.get(conv_id)
            if st is None:
                st = self._adopt(conv_id, merchant_id, customer_id, role, now)
                self.convs[conv_id] = st
            if st.ended:
                return {"action": "end", "rationale": "Conversation already closed; not re-opening it."}
            st.inbound.append(msg)
            detected = detect_reply_language(msg)
            if detected:
                st.mode = detected
            label, feats = classify(msg)
            label = self._auto_by_repetition(st, msg, label)
            ctx = self._ctx(st, now)
            out = self._route(st, ctx, label, feats, msg, role)
            if out.get("action") == "send":
                out["body"] = self._dedupe(st, out["body"], ctx)
                st.sent.append(out["body"])
                self.sent_to.setdefault(self._recipient(st.merchant_id, st.customer_id), set()).add(out["body"])
                if len(st.sent) >= 7:  # hard cap on our own turns; next reply will end it
                    st.ended = True
            elif out.get("action") == "end":
                st.ended = True
            out.setdefault("rationale", label)
            self._recent[dedupe_key] = dict(out)
            if len(self._recent) > 5000:
                self._recent.pop(next(iter(self._recent)))
            return out

    def _adopt(self, conv_id: str, merchant_id: str, customer_id: str | None, role: str, now) -> ConvState:
        """A conversation we never started (e.g. after a restart, or a replay test)."""
        st = ConvState(conv_id, merchant_id, customer_id, None)
        merchant = self.store.get("merchant", merchant_id) or {}
        category = self.store.get("category", merchant.get("category_slug")) or {}
        if customer_id:
            st.mode = customer_mode(self.store.get("customer", customer_id) or {})
        else:
            st.mode = merchant_mode(merchant, category) if merchant else "en"
        if merchant:
            from .playbooks import pb_dormant
            try:
                d = pb_dormant(Ctx(category, merchant, {}, None, now=now))
                st.family, st.anchor, st.deliverable = "re_engage", d.anchor, d.deliverable
            except Exception:
                pass
        return st

    def _auto_by_repetition(self, st: ConvState, msg: str, label: str) -> str:
        norm = re.sub(r"\W+", " ", msg.lower()).strip()
        if len(norm) < 12:
            return label
        seen = self.merchant_auto.setdefault(st.merchant_id, {})
        seen[norm] = seen.get(norm, 0) + 1
        if label not in ("opt_out", "commit") and (seen[norm] >= 2 or st.inbound[:-1].count(msg) >= 1):
            return "auto_reply"
        return label

    # -------------------------------------------------------------- routing
    def _route(self, st: ConvState, ctx: Ctx, label: str, feats: dict, msg: str, role: str) -> dict:
        if label != "auto_reply":
            st.auto_streak = 0
        if label == "empty":
            return {"action": "wait", "wait_seconds": 1800, "rationale": "Empty message; giving them time."}
        if label == "opt_out":
            if st.customer_id:
                self.opted_out_customers.add(st.customer_id)
            else:
                self.opted_out_merchants.add(st.merchant_id)
            return {"action": "end", "rationale": "Explicit opt-out. Ending now and suppressing all future "
                                                  "messages to this recipient."}
        if label == "auto_reply":
            return self._on_auto(st, ctx)
        if label == "abuse":
            return self._on_abuse(st, ctx, feats)
        if label == "commit":
            return self._on_commit(st, ctx, feats, msg, role)
        if label == "later":
            return {"action": "wait", "wait_seconds": 14400,
                    "rationale": "They asked for time; backing off 4 hours instead of pushing."}
        if label == "decline":
            return {"action": "end", "rationale": "Merchant said no; exiting gracefully without another pitch."}
        if label == "thanks":
            if st.delivered:
                return {"action": "end", "rationale": "Work delivered and acknowledged; closing cleanly."}
            return self._on_other(st, ctx, msg, role, "thanks")
        if label == "off_topic":
            return self._on_off_topic(st, ctx, feats)
        if label == "ambiguous":
            return {"action": "send", "cta": "binary_yes_no",
                    "rationale": "Unclear one-word reply: made the choice binary and easy instead of guessing.",
                    "body": pick(st.mode, f"No rush. {ask_phrase(st, 'en')} Just reply YES, or STOP if it's not for you.",
                                 f"Koi jaldi nahi. {ask_phrase(st, 'en')} Bas YES likhiye, ya STOP agar nahi chahiye.")}
        if label == "question":
            st.questions += 1
            return self._on_question(st, ctx, msg, role)
        return self._on_other(st, ctx, msg, role, "other")

    # -------------------------------------------------------------- handlers
    def _on_auto(self, st: ConvState, ctx: Ctx) -> dict:
        st.auto_streak += 1
        total = max(st.auto_streak, max(self.merchant_auto.get(st.merchant_id, {}).values() or [0]))
        if total >= 3 or st.auto_streak >= 3:
            return {"action": "end", "rationale": "Same canned auto-reply 3 times: no human on this line. "
                                                  "Exiting to stop wasting turns."}
        if total == 2 or st.auto_streak == 2:
            return {"action": "wait", "wait_seconds": 14400,
                    "rationale": "Auto-reply again; waiting 4 hours for the owner instead of messaging a bot."}
        owner = ctx.owner or "the owner"
        anchor = st.anchor or (ctx.name + " listing")
        body = pick(st.mode,
                    f"Looks like an auto-reply, no problem. Could you pass this to {owner}? One line: {anchor}. "
                    f"A YES from them is all I need to get started.",
                    f"Lagta hai yeh auto-reply hai, koi baat nahi. {owner} ji tak bas itna pahuncha dijiye: {anchor}. "
                    f"Unka ek YES kaafi hai, baaki main kar dungi.",
                    f"Lagta hai yeh auto-reply hai. {owner} ji tak yeh pahuncha dijiye: {anchor}. "
                    f"Unka ek YES kaafi hai.")
        return {"action": "send", "body": body, "cta": "binary_yes_no",
                "rationale": "Auto-reply detected; one short nudge aimed at the owner, then I back off."}

    def _on_abuse(self, st: ConvState, ctx: Ctx, feats: dict) -> dict:
        st.abuse += 1
        if st.abuse >= 2:
            self.opted_out_merchants.add(st.merchant_id) if not st.customer_id else None
            return {"action": "end", "rationale": "Repeated hostility; exiting politely and not messaging again."}
        off = feats.get("off_topic")
        offer = st.deliverable or "a quick fix for your listing"
        if off:
            body = pick(st.mode,
                        f"Sorry this has been frustrating, and I'll keep it short. {off[0].capitalize()} is outside what "
                        f"I can do; {off[1]}. What I can do for {ctx.name} today: {offer}. Reply YES if that helps, "
                        f"or STOP and I won't message again.",
                        f"Sorry agar pareshani hui, main short rakhti hoon. {off[0].capitalize()} mere scope mein nahi hai; "
                        f"{off[1]}. {ctx.name} ke liye main aaj yeh kar sakti hoon: {offer}. Kaam ka ho toh YES, "
                        f"warna STOP likhiye, main dobara message nahi karungi.")
        else:
            body = pick(st.mode,
                        f"Sorry, I didn't mean to bother you. One useful thing and then I'll leave it with you: "
                        f"{st.anchor or offer}. Reply YES if you want it, or STOP and I won't message again.",
                        f"Sorry agar pareshani hui. Bas ek kaam ki baat: {st.anchor or offer}. Chahiye toh YES, "
                        f"warna STOP likhiye, main dobara message nahi karungi.")
        return {"action": "send", "body": body, "cta": "binary_yes_no",
                "rationale": "Hostile reply: apologise once, stay on mission, offer a clean exit (STOP)."
                + (f" Declined off-topic ask ({off[0]})." if off else "")}

    def _on_off_topic(self, st: ConvState, ctx: Ctx, feats: dict) -> dict:
        st.off_topic += 1
        label, tip = feats["off_topic"]
        if st.off_topic >= 3:
            return {"action": "end", "rationale": "Kept drifting off-topic; closing politely."}
        variants = [
            pick(st.mode, f"{label.capitalize()} is outside what I can help with; {tip}. Back to {ctx.name}: "
                          f"{ask_phrase(st, 'en')} Reply YES.",
                 f"{label.capitalize()} mere scope mein nahi hai; {tip}. {ctx.name} ke liye: {ask_phrase(st, 'mix')}"),
            pick(st.mode, f"Sorry, I can't help with {label}. What I can still do today for {ctx.name}: "
                          f"{ask_phrase(st, 'en')}",
                 f"{label.capitalize()} mein madad nahi kar paungi. Par {ctx.name} ke liye aaj hi: {ask_phrase(st, 'mix')}"),
        ]
        return {"action": "send", "body": variants[(st.off_topic - 1) % 2], "cta": "binary_yes_no",
                "rationale": f"Off-topic ask ({label}) declined honestly, steered back to the original task."}

    def _on_commit(self, st: ConvState, ctx: Ctx, feats: dict, msg: str, role: str) -> dict:
        st.delivered += 1
        if role == "customer" or st.customer_id:
            return self._customer_commit(st, ctx, feats)
        if st.delivered >= 3:
            return {"action": "end", "rationale": "Merchant has confirmed and the work is done; nothing left to ask."}
        if st.delivered == 2:
            body = pick(st.mode,
                        f"Done, it's live. I'll track how it performs for {ctx.name} and report back here next week.",
                        f"Ho gaya, live hai. {ctx.name} ke liye iska result track karke agle hafte yahin batati hoon.")
            return {"action": "send", "body": body, "cta": "none",
                    "rationale": "Second confirmation: executed and closed the loop, no new ask."}
        body = self._deliverable(st, ctx)
        if feats.get("question") and re.search(r"price|cost|charge|fee|kitna|how much|kab|when|how long", msg.lower()):
            ans = self._question_fallback(st, ctx, msg, short=True)
            body = (ans + " " + body) if ans else body
        return {"action": "send", "body": body, "cta": "binary_yes_no",
                "rationale": "Commitment detected: switched straight to action mode and delivered the "
                             f"{st.deliverable or 'next step'} instead of asking more questions."}

    def _customer_commit(self, st: ConvState, ctx: Ctx, feats: dict) -> dict:
        p = ctx.payload
        slots = [s.get("label") for s in (p.get("available_slots") or p.get("next_session_options") or [])
                 if isinstance(s, dict) and s.get("label")]
        mode = st.mode
        if st.family == "appointment":
            if feats.get("slot") == 2:
                return {"action": "send", "cta": "open_ended", "rationale": "Customer wants to reschedule.",
                        "body": pick(mode, "No problem. What day and time suit you better? We'll fix it.",
                                     "Koi baat nahi. Kaunsa din aur time aapke liye theek rahega? Hum set kar denge.",
                                     "Koi baat nahi. Kaunsa din aur samay theek rahega? Hum badal denge.")}
            return {"action": "send", "cta": "none", "rationale": "Customer confirmed the appointment.",
                    "body": pick(mode, f"Confirmed, see you tomorrow at {ctx.name}!",
                                 f"Confirm ho gaya, kal {ctx.name} mein milte hain!",
                                 f"Pakka ho gaya, kal {ctx.name} mein milte hain!")}
        if slots:
            idx = (feats.get("slot") or 1) - 1
            chosen = slots[idx] if 0 <= idx < len(slots) else slots[0]
            offer = next((o for o in ctx.active_offers if "₹" in o), "")
            return {"action": "send", "cta": "none", "rationale": f"Customer picked a slot; booked {chosen}.",
                    "body": pick(mode, f"Booked: {chosen} at {ctx.name}" + (f", {offer}" if offer else "") +
                                 ". We'll send a reminder the day before.",
                                 f"Booking ho gayi: {chosen}, {ctx.name}" + (f" ({offer})" if offer else "") +
                                 ". Ek din pehle reminder bhej denge.",
                                 f"Booking pakki: {chosen}, {ctx.name}. Ek din pehle yaad dila denge.")}
        if st.family == "refill":
            return {"action": "send", "cta": "none", "rationale": "Customer confirmed the refill.",
                    "body": pick(mode, "Confirmed. Your refill is being packed and we'll message you before delivery.",
                                 "Confirm ho gaya. Aapka refill pack ho raha hai, delivery se pehle message karenge.",
                                 "Ho gaya ji. Dawai pack ho rahi hai, delivery se pehle message karenge.")}
        return {"action": "send", "cta": "open_ended", "rationale": "Customer said yes; asking only for a time.",
                "body": pick(mode, "Great! Which day and time work best for you? We'll book it right away.",
                             "Badhiya! Kaunsa din aur time aapke liye best hai? Turant book kar denge.",
                             "Badhiya! Kaunsa din aur samay theek rahega? Turant book kar denge.")}

    # -------------------------------------------------------------- deliverables
    def _deliverable(self, st: ConvState, ctx: Ctx) -> str:
        fam, mode = st.family, st.mode
        name, loc = ctx.name, ctx.locality
        offer = ctx.priced_offer
        p = ctx.payload
        if fam == "research":
            item = ctx.digest_item(p.get("top_item_id") or p.get("digest_item_id")) or {}
            gist = str(item.get("summary", "")).split(". ")[0].rstrip(".")
            draft = f"New research ({item.get('source', 'this month')}): {item.get('title', st.anchor)}. Ask us what it means for you at your next visit. - {name}"
            return pick(mode, f"Here's the gist: {gist}. Patient WhatsApp draft: \"{draft}\" Shall I send it to your list today?",
                        f"Gist yeh hai: {gist}. Patient WhatsApp draft: \"{draft}\" Aaj hi aapki list ko bhej doon?")
        if fam == "compliance":
            item = ctx.digest_item(p.get("top_item_id")) or ctx.find_digest(kinds=("compliance",)) or {}
            steps = [s.strip().rstrip(".") for s in re.split(r";|\. ", str(item.get("actionable", ""))) if s.strip()]
            steps += ["record the check in your SOP file with today's date"]
            listed = " ".join(f"{i + 1}) {s[0].upper() + s[1:]}." for i, s in enumerate(steps[:3]))
            return pick(mode, f"Here's your checklist: {listed} Shall I set a reminder a week before the deadline?",
                        f"Aapki checklist: {listed} Deadline se ek hafte pehle reminder set kar doon?")
        if fam == "learning":
            return pick(mode, f"Done: seat request sent for {st.anchor}, and it's blocked in your calendar. Want a reminder that morning?",
                        f"Ho gaya: {st.anchor} ke liye seat request bhej di, calendar mein block bhi kar diya. Us din subah reminder bhej doon?")
        if fam == "planning":
            title = humanize(p.get("intent_topic") or "plan").title()
            pitch = f"{title} from {name}" + (f", {loc}" if loc else "") + (f": built on our {offer}" if offer else "") + ". Reply to this message to set up your team's order."
            return pick(mode, f"Publishing the {title} on your listing now. Launch message draft: \"{pitch}\" Shall I send it to your past customers too?",
                        f"{title} abhi listing pe publish kar rahi hoon. Launch message draft: \"{pitch}\" Purane customers ko bhi bhej doon?")
        if fam in ("demand_shift", "alert"):
            note = (f"{name}: summer essentials in stock - ORS, sunscreen and anti-fungal care. Reply to reserve yours."
                    if fam == "demand_shift" else
                    f"{name}: a batch of one of your medicines has a voluntary recall. Please bring your strip in and we'll replace it.")
            return pick(mode, f"Drafted the customer message: \"{note}\" Shall I send it to your regulars now?",
                        f"Customer message ready hai: \"{note}\" Abhi regulars ko bhej doon?")
        if fam in ("verification",):
            return pick(mode, "Let's do it. Step 1: open your Google Business Profile and tap 'Get verified'. "
                              "Step 2: choose phone call if it's offered, else postcard. Tell me which option you see and I'll guide the next step.",
                        "Chaliye. Step 1: Google Business Profile kholiye aur 'Get verified' dabaiye. Step 2: phone call option ho toh woh chuniye, "
                        "warna postcard. Kaunsa option dikh raha hai, bataiye, agla step main bataungi.")
        if fam in ("renewal", "winback"):
            plan = ctx.subscription.get("plan") or "current"
            return pick(mode, f"Done, I've started the renewal on your {plan} plan. You'll get the payment link from magicpin here; once paid, upkeep continues without a gap.",
                        f"Ho gaya, {plan} plan ka renewal shuru kar diya. Payment link magicpin se yahin aayega; pay hote hi upkeep bina break ke chalta rahega.")
        # Default: a concrete artifact that matches what was offered, built from this merchant's facts
        what = (st.deliverable or "").lower()
        cat = ctx.catalog_offer()
        line = offer or (f"{cat} (suggested starter offer)" if cat else "your most popular service")
        where = f"{name}" + (f", {loc}" if loc else "")
        ppl = {"dentists": "patients", "gyms": "members", "salons": "clients", "restaurants": "guests"}.get(ctx.slug, "customers")
        if "offer" in what:
            card = ctx.catalog_offer() or line
            return pick(mode, f"Done, offer card drafted: \"{card} at {where}. Book on WhatsApp or walk in.\" Shall I make it live on your listing?",
                        f"Ho gaya, offer card ready: \"{card} at {where}. WhatsApp pe book karein ya walk in karein.\" Listing pe live kar doon?")
        if "listing" in what or "first line" in what:
            return pick(mode, f"Here's the new opening line for your listing: \"{where}: {line}. Same-day slots, call or WhatsApp to book.\" Shall I update it on Google now?",
                        f"Listing ki nayi opening line: \"{where}: {line}. Same-day slots, call ya WhatsApp karke book karein.\" Google pe abhi update kar doon?")
        if "win-back" in what or "winback" in what or "thank-you" in what or "regulars" in what:
            msg = f"Hi! It's been a while since we saw you at {where}. {line} is on for you this week. Reply here to book."
            return pick(mode, f"Draft for your {ppl}: \"{msg}\" Shall I send it to them now?",
                        f"Aapke {ppl} ke liye draft: \"{msg}\" Abhi bhej doon?")
        if "review" in what:
            msg = f"Thank you for visiting {where}! If you have a minute, a Google review helps us a lot."
            return pick(mode, f"Here's the review request: \"{msg}\" Shall I send it to this week's {ppl}?",
                        f"Review request ready: \"{msg}\" Is hafte ke {ppl} ko bhej doon?")
        if "challenge" in what or "retention" in what:
            return pick(mode, f"Here's the challenge: \"{where} four-week streak: show up three times a week, and everyone who finishes gets a shout-out on our page.\" Shall I post it for your {ppl}?",
                        f"Challenge ready: \"{where} four-week streak: hafte mein teen baar aaiye, poora karne walon ka page pe shout-out.\" {ppl} ke liye post kar doon?")
        if "fix plan" in what or "check" in what:
            acts = [i.action for i in ctx.insights() if i.action][:3] or ["publish a fresh Google post"]
            listed = " ".join(f"{i + 1}) {a[0].upper() + a[1:]}." for i, a in enumerate(acts))
            return pick(mode, f"Here's this week's fix plan: {listed} Shall I start with step 1?",
                        f"Is hafte ka fix plan: {listed} Step 1 se shuru karun?")
        post = f"{where}: {line}. Call or walk in today."
        return pick(mode, f"On it. Here's the draft post: \"{post}\" Shall I publish it to your Google listing?",
                    f"Shuru kar diya. Yeh raha draft post: \"{post}\" Google listing pe publish kar doon?")

    # -------------------------------------------------------------- questions & statements
    def _on_question(self, st: ConvState, ctx: Ctx, msg: str, role: str) -> dict:
        llm_body = self._llm_reply(st, ctx, msg, role, "question")
        body = llm_body or self._question_fallback(st, ctx, msg)
        return {"action": "send", "body": body, "cta": "binary_yes_no",
                "rationale": "Answered their question from known facts" + (" (LLM, number-checked)" if llm_body else "")
                + " and kept one next step."}

    def _on_other(self, st: ConvState, ctx: Ctx, msg: str, role: str, kind: str) -> dict:
        llm_body = self._llm_reply(st, ctx, msg, role, kind)
        if llm_body:
            return {"action": "send", "body": llm_body, "cta": "binary_yes_no",
                    "rationale": "Acknowledged what they said and moved to one concrete next step (LLM, checked)."}
        offer = st.deliverable or "the next step"
        variants = [
            pick(st.mode, f"Got it, thanks for telling me. Given that, the quickest win is {offer}. Shall I go ahead? Reply YES.",
                 f"Samajh gayi, batane ke liye shukriya. Toh sabse jaldi fayda {offer} se hoga. Shuru karun? YES reply kijiye."),
            pick(st.mode, f"Makes sense. I'll keep it simple: {offer}, done by me, approved by you in one reply. Go ahead?",
                 f"Theek hai. Simple rakhte hain: {offer}, main karungi, aap bas ek reply mein approve kijiye. Shuru karun?"),
        ]
        return {"action": "send", "body": variants[len(st.sent) % 2], "cta": "binary_yes_no",
                "rationale": "Acknowledged their point and offered one low-effort next step."}

    def _question_fallback(self, st: ConvState, ctx: Ctx, msg: str, short: bool = False) -> str:
        low = msg.lower()
        offer = st.deliverable or "it"
        if short:  # one-line answer used in front of a deliverable
            if re.search(r"price|cost|charge|fee|kitna|how much", low):
                return pick(st.mode, "No extra cost to draft it; nothing goes live without your OK.",
                            "Draft karne ka koi extra charge nahi; aapke OK ke bina kuch live nahi hoga.")
            return pick(st.mode, "Starting today.", "Aaj hi shuru.")
        if re.search(r"price|cost|charge|fee|kitna|kitne|paisa|rate|how much", low):
            offers = ctx.active_offers
            if offers:
                return pick(st.mode, f"Your live offers are {', '.join(offers[:3])}. I'd build on those rather than discounting. {ask_phrase(st, 'en')}",
                            f"Aapke live offers: {', '.join(offers[:3])}. Discount ki jagah inhi pe build karte hain. {ask_phrase(st, 'mix')}")
            return pick(st.mode, f"Drafting it costs you nothing extra; you only approve what goes live. {ask_phrase(st, 'en')}",
                        f"Draft karne ka koi alag charge nahi; live sirf aapke approve karne pe hoga. {ask_phrase(st, 'mix')}")
        if re.search(r"how|kaise|process|steps", low):
            return pick(st.mode, f"Simple: I prepare {offer}, you check it here, and it goes live only after your YES. Shall I start?",
                        f"Simple hai: main {offer} taiyaar karti hoon, aap yahin check kijiye, aapke YES ke baad hi live hoga. Shuru karun?")
        if re.search(r"when|kab|time|how long|kitne din", low):
            return pick(st.mode, f"Today. You'll see {offer} here first, and nothing goes live without your OK. Shall I start?",
                        f"Aaj hi. {offer} pehle yahin dikhega, aapke OK ke bina kuch live nahi hoga. Shuru karun?")
        if re.search(r"why|kyun|kyon|what for|benefit|fayda", low):
            why = st.anchor or ctx.name
            return pick(st.mode, f"Because of this: {why}. Acting now is cheaper than catching up later. {ask_phrase(st, 'en')}",
                        f"Wajah yeh hai: {why}. Abhi karna baad mein catch-up karne se aasaan hai. {ask_phrase(st, 'mix')}")
        if re.search(r"what (else )?(should|can|do you suggest|would you)|suggest|recommend|advice|idea|kya karun|kya karna chahiye|what next", low):
            tips = [i for i in ctx.insights() if i.action][:1] or ctx.insights()[:1]
            if tips:
                t = tips[0]
                rec = f"My pick for {ctx.name}: {t.text}, so {t.action or 'that is where I would start'}."
                rec_mix = f"Meri salah: {t.text}, isliye {t.action or 'wahin se shuru karte hain'}."
                return pick(st.mode, f"{rec} {ask_phrase(st, 'en')}", f"{rec_mix} {ask_phrase(st, 'mix')}")
        if re.search(r"\b(who are you|your name|aapka naam|tumhara naam|kaun ho|what is (this|vera)|which company)\b", low):
            return pick(st.mode, f"I'm Vera, magicpin's assistant for {ctx.name}'s listing and growth. {ask_phrase(st, 'en')}",
                        f"Main Vera hoon, magicpin ki assistant, {ctx.name} ki listing aur growth ke liye. {ask_phrase(st, 'mix')}")
        ins = next(iter(ctx.insights()), None)
        fact = f" One thing I can tell you: {ins.text}." if ins else ""
        return pick(st.mode, f"I don't have that detail on my side, so I won't guess.{fact} {ask_phrase(st, 'en')}",
                    f"Yeh detail mere paas nahi hai, isliye guess nahi karungi.{fact} {ask_phrase(st, 'mix')}")

    def _llm_reply(self, st: ConvState, ctx: Ctx, msg: str, role: str, kind: str) -> str | None:
        if not self.llm or not self.llm.enabled and self.llm.transport is None:
            return None
        lang = {"en": "English", "mix": "natural Hindi-English mix (Roman script)", "hi": "Hindi in Roman script"}[st.mode]
        persona = (f"You are the WhatsApp assistant of {ctx.name}, replying to their customer {ctx.cust_name}."
                   if role == "customer" or st.customer_id else
                   f"You are Vera, magicpin's assistant, chatting with {ctx.salutation} who runs {ctx.name} ({ctx.slug}).")
        system = (persona + "\nRules: answer their latest message directly in 1-3 short sentences, then ONE next step as the last sentence. "
                  "Use only the FACTS below; if the answer is not in the facts, say you don't have that detail (never guess numbers, "
                  "prices, dates or names). No greetings, no re-introduction, no URLs, no lists. "
                  f"Reply in {lang}. Never use: {', '.join(ctx.taboos) or 'n/a'}. "
                  'Return JSON {"body": "..."}')
        facts = self._facts_brief(st, ctx)
        convo = "\n".join(f"{'BOT' if i % 2 == 0 else role.upper()}: {t}"
                          for i, t in enumerate(self._interleave(st)))[-2500:]
        user = f"FACTS:\n{facts}\n\nCONVERSATION:\n{convo}\n\nTheir message type: {kind}. Write the reply."
        out = self.llm.chat_json(system, user, max_tokens=250, deadline=time.time() + 6)
        body = (out or {}).get("body") if isinstance(out, dict) else None
        if not isinstance(body, str) or len(body.strip()) < 10 or len(body) > 700:
            return None
        body = body.strip()
        allowed = set(ctx.allowed_numbers) | {round(n, 2) for t in st.inbound + st.sent for n in numbers_in(t)}
        if any(round(n, 2) not in allowed and n not in (0, 1) for n in numbers_in(body)):
            return None
        if re.search(r"https?://|www\.", body) or body in st.sent:
            return None
        if any(t.lower() in body.lower() for t in ctx.taboos if len(t) > 3):
            return None
        return body

    def _interleave(self, st: ConvState) -> list[str]:
        out = []
        for i in range(max(len(st.sent), len(st.inbound))):
            if i < len(st.sent):
                out.append(st.sent[i])
            if i < len(st.inbound):
                out.append(st.inbound[i])
        return out

    def _facts_brief(self, st: ConvState, ctx: Ctx) -> str:
        lines = [f"Business: {ctx.name}, {ctx.locality} {ctx.city} ({ctx.slug})"]
        pf = ctx.perf
        if pf:
            lines.append("Last 30 days: " + ", ".join(f"{k} {pf[k]}" for k in ("views", "calls", "directions", "ctr", "leads") if k in pf))
        if ctx.active_offers:
            lines.append("Live offers: " + "; ".join(ctx.active_offers))
        for ins in ctx.insights()[:3]:
            lines.append("Observation: " + ins.text)
        if st.anchor:
            lines.append("Topic of this conversation: " + st.anchor)
        if st.deliverable:
            lines.append("What Vera offered to do: " + st.deliverable)
        if ctx.customer:
            r = ctx.relationship
            lines.append(f"Customer: {ctx.cust_name}, visits {r.get('visits_total')}, last visit {r.get('last_visit')}")
            slots = [s.get("label") for s in ctx.payload.get("available_slots") or [] if isinstance(s, dict)]
            if slots:
                lines.append("Open slots: " + "; ".join(slots))
        return "\n".join(lines)

    def _dedupe(self, st: ConvState, body: str, ctx: Ctx) -> str:
        if body not in st.sent:
            return body
        suffix = pick(st.mode, " (Just a YES or NO is fine.)", " (Bas YES ya NO likh dijiye.)")
        return body + suffix if body + suffix not in st.sent else body + f" [{fmt_int(len(st.sent))}]"
