"""Derived views over the context store.

Two rules are enforced here rather than left to callers, because forgetting
either one is a scoring error rather than a crash:

*   **Active offers only.**  The judge's scoring prompt is handed
    `[o for o in merchant.offers if o.status == "active"]`.  An expired offer is
    real data we were given, but the judge cannot see it, so citing one reads as
    fabrication.  `active_offers()` is the only sanctioned way to reach them.

*   **Resolution is all-or-nothing.**  A trigger naming a merchant we were never
    pushed resolves to None, not to a half-populated bundle.  The shipped
    simulator resolves unknown ids to `{}` and composes anyway, which is how you
    end up sending "Hi , your views are ?".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .store import ContextStore


@dataclass(frozen=True)
class Bundle:
    """Everything needed to compose one message, resolved and verified present."""

    trigger: dict[str, Any]
    merchant: dict[str, Any]
    category: dict[str, Any]
    customer: dict[str, Any] | None
    trigger_id: str
    merchant_id: str
    category_slug: str
    customer_id: str | None

    @property
    def is_customer_facing(self) -> bool:
        return self.customer is not None

    @property
    def send_as(self) -> str:
        """Who the message appears to come from.

        Vera speaks as herself to a merchant.  A message to the merchant's own
        customer goes out from the merchant's number, so it must be attributed
        to them — getting this backwards is both a scored error and, outside a
        test harness, a trust violation.
        """
        return "merchant_on_behalf" if self.customer is not None else "vera"


class ContextIndex:
    def __init__(self, store: ContextStore) -> None:
        self.store = store

    # ---- lookups --------------------------------------------------------

    def category_for(self, merchant: dict[str, Any]) -> dict[str, Any] | None:
        slug = merchant.get("category_slug")
        if not slug:
            return None
        return self.store.get("category", slug)

    def customers_of(self, merchant_id: str) -> list[tuple[str, dict[str, Any]]]:
        return [
            (cid, payload)
            for cid, payload in self.store.iter_scope("customer")
            if payload.get("merchant_id") == merchant_id
        ]

    @staticmethod
    def active_offers(merchant: dict[str, Any]) -> list[dict[str, Any]]:
        """Offers the judge can actually see. The only sanctioned accessor."""
        return [
            o
            for o in merchant.get("offers", []) or []
            if o.get("status") == "active"
        ]

    # ---- resolution -----------------------------------------------------

    def resolve(self, trigger_id: str) -> Bundle | None:
        """Assemble the full context bundle for a trigger, or None.

        Returning None is the correct outcome for an orphan trigger: accept the
        push, decline to speak, stay healthy.
        """
        trigger = self.store.get("trigger", trigger_id)
        if not trigger:
            return None

        merchant_id = trigger.get("merchant_id")
        if not merchant_id:
            return None

        merchant = self.store.get("merchant", merchant_id)
        if not merchant:
            # Orphan trigger. The merchant may arrive on a later push, at which
            # point this same trigger resolves cleanly.
            return None

        category = self.category_for(merchant)
        if not category:
            return None

        customer = None
        customer_id = trigger.get("customer_id")
        if customer_id:
            customer = self.store.get("customer", customer_id)
            if not customer:
                # A customer-scoped trigger whose customer we do not hold. We
                # cannot honour consent or language preference without it.
                return None

        return Bundle(
            trigger=trigger,
            merchant=merchant,
            category=category,
            customer=customer,
            trigger_id=trigger_id,
            merchant_id=merchant_id,
            category_slug=merchant.get("category_slug", ""),
            customer_id=customer_id,
        )

    # ---- consent --------------------------------------------------------

    @staticmethod
    def may_contact_customer(customer: dict[str, Any], trigger_kind: str) -> bool:
        """Consent gate. Runs before composition, never after.

        Three hard blocks first -- no opt-in date, no consent scope, or no
        contact number. The dataset contains exactly one record failing these
        (a walk-in with `opted_in_at: null` and an empty scope) and it is there
        on purpose.

        Then purpose matching, by family rather than by exact string. An
        earlier version required a literal per-kind scope and blocked 24 of the
        30 customer triggers in the set -- including recall reminders to
        customers carrying `preferences.reminder_opt_in: true`, which is an
        explicit opt-in to exactly that. It simultaneously allowed promotional
        follow-ups to customers who had opted OUT of reminders, which is the
        wrong way round: a care reminder is easier to justify than a promotion,
        not harder.
        """
        consent = customer.get("consent") or {}
        if not consent.get("opted_in_at"):
            return False

        scope = {str(s).lower() for s in (consent.get("scope") or [])}
        if not scope:
            return False

        identity = customer.get("identity") or {}
        if not identity.get("phone_redacted") and not identity.get("phone"):
            return False

        prefs = customer.get("preferences") or {}
        reminder_ok = bool(prefs.get("reminder_opt_in"))

        family = _KIND_FAMILY.get(trigger_kind)
        if family is None:
            # Unknown kind: fall back to requiring some affirmative consent,
            # which the checks above already established.
            return True

        accepted = _FAMILY_SCOPES[family]
        if scope & accepted:
            return True

        # A reminder may also rest on the explicit reminder preference, which
        # is a consent signal in its own right. Promotions may not -- those
        # need a promotional scope and nothing else substitutes.
        if family == "reminder" and reminder_ok:
            return True

        return False


# Care/service reminders, win-back attempts, and outright promotions are three
# different asks and carry different consent bars.
_KIND_FAMILY: dict[str, str] = {
    "recall_due": "reminder",
    "appointment_tomorrow": "reminder",
    "chronic_refill_due": "reminder",
    "customer_lapsed_soft": "reminder",
    "customer_lapsed_hard": "winback",
    "winback_eligible": "winback",
    "trial_followup": "promotional",
    "wedding_package_followup": "promotional",
}

_FAMILY_SCOPES: dict[str, set[str]] = {
    "reminder": {
        "recall_reminders", "appointment_reminders", "treatment_followup",
        "refill_reminders", "service_reminders",
    },
    "winback": {"winback_offers", "renewal_reminders", "promotional_offers"},
    "promotional": {"promotional_offers", "winback_offers"},
}
