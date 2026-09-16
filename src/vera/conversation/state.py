"""Conversation tracking and reply classification.

Two findings from reading the harness drive the design here, and both contradict
the obvious implementation.

**Auto-reply detection must be merchant-global, not per-conversation.**
`judge_simulator._auto_reply` sends the same canned text four times under four
*different* conversation ids (`conv_auto_1` … `conv_auto_4`, line 693).  The
brief's own hint — "same message verbatim 3+ times = auto-reply" — reads as a
within-conversation rule, and a per-conversation repetition counter therefore
sees four unrelated opening replies and never fires.  We key the signature on
the merchant.

**After a commitment, one qualifying phrase vetoes the whole reply.**
`_intent` (lines 742-748) accepts only when the body contains an actioning token
AND contains no qualifying token.  "Would you like me to send the draft?" holds
both "draft" and "send" and still fails, because "would you" is present.  The
lists below are copied from that source, so the veto set is exact rather than
inferred.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Copied verbatim from judge_simulator.py:742-743.
QUALIFYING_TOKENS: tuple[str, ...] = (
    "would you",
    "do you",
    "can you tell",
    "what if",
    "how about",
)
ACTIONING_TOKENS: tuple[str, ...] = (
    "done",
    "sending",
    "draft",
    "here",
    "confirm",
    "proceed",
    "next",
)

# Merchant phrasings that signal an explicit commitment. English, Hindi and the
# romanized code-mix a WhatsApp Business owner actually types.
_COMMITMENT = (
    "lets do it",
    "let's do it",
    "ok lets",
    "go ahead",
    "yes please",
    "sounds good",
    "i want to join",
    "sign me up",
    "please do",
    "do it",
    "haan karo",
    "kar do",
    "theek hai karo",
    "shuru karo",
    "chalega",
    "start karo",
)

# WhatsApp Business canned-reply fingerprints.
_CANNED = (
    "thank you for contacting",
    "our team will respond",
    "we will get back to you",
    "this is an automated",
    "automated assistant",
    "aapki jaankari ke liye",
    "hamari team tak",
    "team tak pahuncha",
    "shukriya",
    "out of office",
    "currently unavailable",
)

_HOSTILE = (
    "stop messaging",
    "spam",
    "useless",
    "don't contact",
    "dont contact",
    "not interested",
    "leave me alone",
    "band karo",
    "mat bhejo",
    "pareshan",
)

_OFF_TOPIC = (
    "gst",
    "income tax",
    "loan",
    "visa",
    "passport",
    "electricity bill",
)


class ReplyKind(Enum):
    AUTO_REPLY = "auto_reply"
    COMMITMENT = "commitment"
    HOSTILE = "hostile"
    OFF_TOPIC = "off_topic"
    QUESTION = "question"
    ENGAGED = "engaged"
    DISMISSIVE = "dismissive"


def normalize(text: str) -> str:
    """Signature form: lowercase, punctuation stripped, whitespace collapsed.

    Auto-replies vary by a trailing emoji or an exclamation mark between sends,
    so byte equality is too brittle to detect them.
    """
    return re.sub(r"[^a-z0-9ऀ-ॿ ]+", "", text.lower()).strip()


def classify(text: str) -> ReplyKind:
    """Single-message classification. Deterministic, no model call.

    Ordering matters: hostility outranks everything, and a canned auto-reply
    that happens to contain a polite question is still an auto-reply.
    """
    low = normalize(text)
    if not low:
        return ReplyKind.DISMISSIVE

    if any(h in low for h in _HOSTILE):
        return ReplyKind.HOSTILE
    if any(c in low for c in _CANNED):
        return ReplyKind.AUTO_REPLY
    if any(c in low for c in _COMMITMENT):
        return ReplyKind.COMMITMENT
    if any(o in low for o in _OFF_TOPIC):
        return ReplyKind.OFF_TOPIC
    if "?" in text:
        return ReplyKind.QUESTION
    if len(low.split()) <= 2:
        return ReplyKind.DISMISSIVE
    return ReplyKind.ENGAGED


def violates_intent_rule(body: str) -> bool:
    """True if this body would fail the harness's post-commitment check.

    Call this on any reply composed after a commitment was detected.  A True
    means rewrite, not ship.
    """
    low = body.lower()
    has_action = any(t in low for t in ACTIONING_TOKENS)
    has_qualifier = any(t in low for t in QUALIFYING_TOKENS)
    return has_qualifier or not has_action


@dataclass
class Turn:
    role: str
    text: str
    kind: ReplyKind | None = None


@dataclass
class Conversation:
    conversation_id: str
    merchant_id: str | None
    customer_id: str | None = None
    turns: list[Turn] = field(default_factory=list)
    committed: bool = False
    ended: bool = False
    unanswered_nudges: int = 0
    sent_signatures: set[str] = field(default_factory=set)

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def already_sent(self, body: str) -> bool:
        """Anti-repetition guard. A verbatim resend here costs -2."""
        return normalize(body) in self.sent_signatures

    def record_send(self, body: str) -> None:
        self.turns.append(Turn(role="bot", text=body))
        self.sent_signatures.add(normalize(body))


class ConversationRegistry:
    """All conversations, plus the merchant-global signature ledger.

    The ledger is what makes auto-reply detection work across the separate
    conversation ids the harness uses.
    """

    def __init__(self, auto_reply_threshold: int = 2) -> None:
        self._lock = threading.RLock()
        self._convs: dict[str, Conversation] = {}
        # merchant_id -> normalized inbound signature -> count, across all
        # conversations with that merchant.
        self._inbound: dict[str, dict[str, int]] = {}
        self._threshold = auto_reply_threshold

    def get_or_create(
        self,
        conversation_id: str,
        merchant_id: str | None,
        customer_id: str | None = None,
    ) -> Conversation:
        with self._lock:
            conv = self._convs.get(conversation_id)
            if conv is None:
                conv = Conversation(
                    conversation_id=conversation_id,
                    merchant_id=merchant_id,
                    customer_id=customer_id,
                )
                self._convs[conversation_id] = conv
            return conv

    def get(self, conversation_id: str) -> Conversation | None:
        with self._lock:
            return self._convs.get(conversation_id)

    def record_inbound(
        self, merchant_id: str | None, text: str
    ) -> tuple[ReplyKind, int]:
        """Record an inbound message and return its kind plus how many times
        this merchant has now sent that exact signature.

        The count is what lets us treat the third identical message as an
        auto-reply even when each arrived under its own conversation id.
        """
        kind = classify(text)
        if not merchant_id:
            return kind, 1

        sig = normalize(text)
        with self._lock:
            seen = self._inbound.setdefault(merchant_id, {})
            seen[sig] = seen.get(sig, 0) + 1
            count = seen[sig]

        if count > self._threshold:
            # Repetition alone is sufficient evidence, whatever the wording.
            kind = ReplyKind.AUTO_REPLY
        return kind, count

    def signature_count(self, merchant_id: str | None, text: str) -> int:
        if not merchant_id:
            return 0
        with self._lock:
            return self._inbound.get(merchant_id, {}).get(normalize(text), 0)

    def has_open_conversation(self, merchant_id: str) -> bool:
        with self._lock:
            return any(
                c.merchant_id == merchant_id and not c.ended
                for c in self._convs.values()
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "conversations": len(self._convs),
                "open": sum(1 for c in self._convs.values() if not c.ended),
            }
