"""The bot: ties the store, composer, LLM and reply engine together.

`Bot.tick()` is the proactive decision:

    for each active trigger:
        skip if already sent (suppression key), recipient opted out,
             contexts missing, or customer consent does not cover it
        build facts -> playbook -> deterministic draft (milliseconds)
    rank candidates (urgency + evidence strength), keep ONE per recipient per tick
    polish the winners with the LLM in parallel, under a hard deadline
    anything not polished in time ships as the deterministic draft

So /v1/tick always answers well inside 30 s, with or without an LLM.
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import os
import threading
import time
from pathlib import Path

from .compose import Composed, plan, polish
from .conversation import ReplyEngine
from .facts import Ctx
from .lang import customer_mode, merchant_mode
from .llm import LLM
from .store import ContextStore, load_seed_dataset

VERSION = "1.0.0"
MAX_ACTIONS = 20


class Bot:
    def __init__(self, data_dir: Path | None = None, snapshot: str | None = None) -> None:
        self.started = time.time()
        self.store = ContextStore(snapshot_path=snapshot)
        self.seeded = load_seed_dataset(self.store, data_dir) if data_dir and data_dir.exists() else 0
        self.llm = LLM()
        self.replies = ReplyEngine(self.store, self.llm)
        self.lock = threading.RLock()
        self.fired: set[str] = set()           # suppression keys + trigger ids already acted on
        self.tick_budget = float(os.environ.get("TICK_BUDGET_SECONDS", "8"))
        self.pool = cf.ThreadPoolExecutor(max_workers=int(os.environ.get("LLM_WORKERS", "4")))
        self.polish_enabled = os.environ.get("LLM_POLISH", "1") != "0"
        self._tick_cache: dict = {}

    # ------------------------------------------------------------------ helpers
    def _fresh_digest_ids(self, slug: str) -> set:
        cur = self.store.get("category", slug) or {}
        prev = self.store.previous("category", slug)
        if not prev:
            return set()
        old = {d.get("id") for d in prev.get("digest") or [] if isinstance(d, dict)}
        return {d.get("id") for d in cur.get("digest") or [] if isinstance(d, dict) and d.get("id") not in old}

    def build_ctx(self, trigger: dict, now: str | None) -> tuple[Ctx | None, str]:
        payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
        merchant_id = trigger.get("merchant_id") or payload.get("merchant_id")
        merchant = self.store.get("merchant", merchant_id)
        if not merchant:
            return None, f"merchant {merchant_id!r} not loaded"
        slug = merchant.get("category_slug") or payload.get("category")
        category = self.store.get("category", slug) or {"slug": slug or "business"}
        customer_id = trigger.get("customer_id") or payload.get("customer_id")
        customer = self.store.get("customer", customer_id) if customer_id else None
        ctx = Ctx(category, merchant, trigger, customer, now=now,
                  prev_merchant=self.store.previous("merchant", merchant_id),
                  fresh_digest_ids=self._fresh_digest_ids(slug) if slug else set())
        return ctx, ""

    # ------------------------------------------------------------------ tick
    def tick(self, now: str | None, trigger_ids: list) -> dict:
        key = (str(now), tuple(t for t in trigger_ids or [] if isinstance(t, str)))
        with self.lock:
            hit = self._tick_cache.get(key)
            if hit and time.time() - hit[0] < 120:
                return hit[1]  # duplicate request (judge retry): identical answer
        out = self._tick(now, trigger_ids)
        with self.lock:
            self._tick_cache[key] = (time.time(), out)
            if len(self._tick_cache) > 200:
                self._tick_cache.pop(next(iter(self._tick_cache)))
        return out

    def _tick(self, now: str | None, trigger_ids: list) -> dict:
        t0 = time.time()
        deadline = t0 + self.tick_budget
        candidates: list[tuple[float, str, dict, Ctx, Composed]] = []
        seen_ids = set()
        for tid in trigger_ids or []:
            if not isinstance(tid, str) or tid in seen_ids:
                continue
            seen_ids.add(tid)
            trig = self.store.get("trigger", tid)
            if not isinstance(trig, dict):
                continue
            skey = str(trig.get("suppression_key") or tid)
            with self.lock:
                if skey in self.fired or tid in self.fired:
                    continue
            ctx, why = self.build_ctx(trig, now)
            if ctx is None:
                continue
            mid = ctx.merchant.get("merchant_id") or trig.get("merchant_id")
            cid = (ctx.customer or {}).get("customer_id") if ctx.customer else None
            if self.replies.is_opted_out(mid) or (cid and self.replies.is_opted_out(mid, cid)):
                continue
            try:
                comp = plan(ctx, skey)
            except Exception:
                continue
            if comp.skip or not comp.body:
                with self.lock:
                    self.fired.add(skey)  # never retry a consent-blocked trigger
                continue
            urgency = trig.get("urgency") if isinstance(trig.get("urgency"), (int, float)) else 2
            score = urgency * 2 + comp.strength
            candidates.append((score, tid, trig, ctx, comp))

        # one message per recipient per tick, best first
        candidates.sort(key=lambda c: -c[0])
        chosen, recipients = [], set()
        for cand in candidates:
            _, tid, trig, ctx, comp = cand
            mid = ctx.merchant.get("merchant_id")
            rkey = f"{mid}|{(ctx.customer or {}).get('customer_id', '')}"
            if rkey in recipients:
                continue
            recipients.add(rkey)
            chosen.append(cand)
            if len(chosen) >= MAX_ACTIONS:
                break

        # polish in parallel within the deadline; unfinished ones keep their draft
        if self.llm.enabled and self.polish_enabled and chosen:
            futures = {}
            for cand in chosen:
                _, tid, trig, ctx, comp = cand
                mid = ctx.merchant.get("merchant_id")
                cid = (ctx.customer or {}).get("customer_id")
                sent = self.replies.bodies_sent_to(mid, cid)
                futures[self.pool.submit(polish, comp, ctx, self.llm, deadline - 1.0, sent)] = cand
            cf.wait(futures, timeout=max(0.5, deadline - time.time()))

        actions = []
        for _, tid, trig, ctx, comp in chosen:
            mid = ctx.merchant.get("merchant_id") or trig.get("merchant_id")
            cid = (ctx.customer or {}).get("customer_id") if ctx.customer else None
            conv_id = "conv_" + hashlib.sha1(f"{tid}|{mid}|{cid}".encode()).hexdigest()[:12]
            with self.lock:
                if conv_id in self.replies.convs:
                    conv_id += "_" + hashlib.sha1(str(time.time()).encode()).hexdigest()[:4]
                self.fired.add(comp.suppression_key)
                self.fired.add(tid)
            mode = comp.draft.mode if comp.send_as == "merchant_on_behalf" else merchant_mode(ctx.merchant, ctx.category)
            self.replies.register(conv_id, mid, cid, tid, comp.family, comp.draft.anchor, comp.draft.deliverable,
                                  comp.body, mode)
            actions.append({
                "conversation_id": conv_id, "merchant_id": mid, "customer_id": cid,
                "send_as": comp.send_as, "trigger_id": tid,
                "template_name": comp.template_name, "template_params": comp.template_params,
                "body": comp.body, "cta": comp.cta, "suppression_key": comp.suppression_key,
                "rationale": comp.rationale + (" Wording polished by LLM; facts checked." if comp.polished else ""),
            })
        return {"actions": actions}

    # ------------------------------------------------------------------ one-shot compose (submission / tests)
    def compose_one(self, category: dict, merchant: dict, trigger: dict, customer: dict | None,
                    now: str | None = None, use_llm: bool = True) -> dict:
        ctx = Ctx(category, merchant, trigger, customer, now=now)
        comp = plan(ctx, str(trigger.get("suppression_key") or trigger.get("id") or ""))
        if comp.skip:
            return {"body": "", "cta": "none", "send_as": "vera", "suppression_key": comp.suppression_key,
                    "rationale": f"No message: {comp.skip}"}
        if use_llm and self.llm.enabled and self.polish_enabled:
            polish(comp, ctx, self.llm, time.time() + 20)
        return {"body": comp.body, "cta": comp.cta, "send_as": comp.send_as,
                "suppression_key": comp.suppression_key, "rationale": comp.rationale,
                "template_name": comp.template_name, "template_params": comp.template_params}

    def reply(self, req: dict) -> dict:
        return self.replies.handle(req)

    def teardown(self) -> None:
        with self.lock:
            self.store.clear()
            self.fired.clear()
            self._tick_cache.clear()
            self.replies.clear()
