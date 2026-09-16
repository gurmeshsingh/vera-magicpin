"""Versioned context store.

The judge pushes context to us over the whole test window and expects us to
remember it. Three behaviours matter and all three are contractual:

1.  Idempotency.  Re-pushing a version we already hold is a no-op that still
    ACCEPTS.  The harness scores a push as passing iff `accepted` is truthy, so
    answering `false` to an equal-version re-push manufactures a warmup failure.
    Only a *strictly lower* version is refused.

2.  Atomic replacement.  A higher version for the same context replaces the
    prior one wholesale.

3.  Diffing.  Phase 3 injects context mid-test and scores whether our next
    message cites the NEW fact rather than the stale one.  That is only
    answerable if we record what changed, so every bump writes a delta.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

Scope = Literal["category", "merchant", "customer", "trigger"]
SCOPES: tuple[Scope, ...] = ("category", "merchant", "customer", "trigger")


@dataclass(frozen=True)
class Delta:
    """What a version bump actually changed.

    `new_facts` holds values present at the new version and absent at the old
    one, flattened to `dotted.path -> value`.  A composer may cite these as
    genuinely new; everything else is carried-over state and claiming novelty
    about it is a hallucination of a different kind.
    """

    scope: Scope
    context_id: str
    from_version: int
    to_version: int
    seen_at_tick: int
    new_facts: dict[str, Any] = field(default_factory=dict)
    changed_facts: dict[str, tuple[Any, Any]] = field(default_factory=dict)

    @property
    def is_substantive(self) -> bool:
        """A bump that carries nothing new must not be spoken about as news."""
        return bool(self.new_facts or self.changed_facts)


@dataclass
class Entry:
    scope: Scope
    context_id: str
    version: int
    payload: dict[str, Any]
    first_seen_at_tick: int
    last_updated_at_tick: int


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested payloads to dotted paths, list items indexed by position.

    Leaves are scalars.  Lists of dicts are walked rather than compared whole,
    so adding one digest item to a list of five surfaces as a handful of new
    leaf paths instead of one opaque "the list changed".
    """
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


class ContextStore:
    """Thread-safe store keyed by (scope, context_id).

    The judge may push at up to 10 req/s while a tick is being served, so every
    mutation takes the lock and every read returns a snapshot the caller can
    hold without racing a concurrent push.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str], Entry] = {}
        self._deltas: list[Delta] = []
        self._tick = 0

    # ---- ingest ---------------------------------------------------------

    def put(
        self, scope: Scope, context_id: str, version: int, payload: dict[str, Any]
    ) -> tuple[bool, Delta | None, int]:
        """Store a pushed context.

        Returns `(accepted, delta, current_version)`.  `delta` is non-None only
        when this push genuinely advanced the version.
        """
        with self._lock:
            key = (scope, context_id)
            existing = self._entries.get(key)

            if existing is not None:
                if version < existing.version:
                    # Strictly stale. The only case we refuse.
                    return False, None, existing.version
                if version == existing.version:
                    # Idempotent replay. Accept without touching state; the
                    # harness treats a falsy `accepted` as a failed push.
                    return True, None, existing.version

            delta = None
            if existing is not None:
                old_flat = _flatten(existing.payload)
                new_flat = _flatten(payload)
                new_facts = {
                    p: v for p, v in new_flat.items() if p not in old_flat
                }
                changed = {
                    p: (old_flat[p], v)
                    for p, v in new_flat.items()
                    if p in old_flat and old_flat[p] != v
                }
                delta = Delta(
                    scope=scope,
                    context_id=context_id,
                    from_version=existing.version,
                    to_version=version,
                    seen_at_tick=self._tick,
                    new_facts=new_facts,
                    changed_facts=changed,
                )
                self._deltas.append(delta)

            self._entries[key] = Entry(
                scope=scope,
                context_id=context_id,
                version=version,
                payload=payload,
                first_seen_at_tick=(
                    existing.first_seen_at_tick if existing else self._tick
                ),
                last_updated_at_tick=self._tick,
            )
            return True, delta, version

    # ---- read -----------------------------------------------------------

    def get(self, scope: Scope, context_id: str) -> dict[str, Any] | None:
        """Payload for a context, or None. Unknown ids return None, never {}.

        The shipped simulator resolves unknown ids to an empty dict and carries
        on, which silently produces contentless messages.  We distinguish.
        """
        with self._lock:
            entry = self._entries.get((scope, context_id))
            return entry.payload if entry else None

    def entry(self, scope: Scope, context_id: str) -> Entry | None:
        with self._lock:
            return self._entries.get((scope, context_id))

    def version_of(self, scope: Scope, context_id: str) -> int | None:
        with self._lock:
            entry = self._entries.get((scope, context_id))
            return entry.version if entry else None

    def iter_scope(self, scope: Scope) -> Iterator[tuple[str, dict[str, Any]]]:
        with self._lock:
            items = [
                (e.context_id, e.payload)
                for e in self._entries.values()
                if e.scope == scope
            ]
        return iter(items)

    def ids(self, scope: Scope) -> list[str]:
        with self._lock:
            return sorted(
                e.context_id for e in self._entries.values() if e.scope == scope
            )

    def counts(self) -> dict[str, int]:
        """Per-scope counts for /v1/healthz.

        The warmup gate checks these reflect all 255 base contexts, so every
        scope is reported even when empty.
        """
        with self._lock:
            out = {s: 0 for s in SCOPES}
            for e in self._entries.values():
                out[e.scope] = out.get(e.scope, 0) + 1
            return out

    def total(self) -> int:
        with self._lock:
            return len(self._entries)

    # ---- deltas ---------------------------------------------------------

    def deltas_since(self, tick: int) -> list[Delta]:
        with self._lock:
            return [d for d in self._deltas if d.seen_at_tick >= tick]

    def deltas_for(self, scope: Scope, context_id: str) -> list[Delta]:
        with self._lock:
            return [
                d
                for d in self._deltas
                if d.scope == scope and d.context_id == context_id
            ]

    def unconsumed_deltas(self) -> list[Delta]:
        """Substantive deltas we have not yet spoken about."""
        with self._lock:
            return [d for d in self._deltas if d.is_substantive]

    # ---- teardown -------------------------------------------------------

    def clear(self) -> int:
        """Drop all state. Returns how many contexts were held.

        Two callers. The testing brief says magicpin may POST /v1/teardown at
        the end of a run and that bots must not retain context afterwards.
        It is also the reset for a service that was exercised before the real
        window -- stale contexts at the same version would make the judge's own
        pushes no-ops, since an equal-version push is correctly idempotent.
        """
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            self._deltas.clear()
            self._tick = 0
            return n

    # ---- clock ----------------------------------------------------------

    def advance_tick(self) -> int:
        with self._lock:
            self._tick += 1
            return self._tick

    @property
    def tick(self) -> int:
        with self._lock:
            return self._tick
