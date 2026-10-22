"""Tiny LLM client (standard library only).

Talks to any OpenAI-compatible chat endpoint (default: Groq).  Design rules:

* The bot NEVER depends on the LLM.  Every caller has a deterministic answer
  ready; the LLM only polishes it.  No key, a timeout, a 429 or bad JSON all
  simply mean "keep the deterministic version".
* A model chain spreads load across models.  Groq rate-limits each model
  separately, so when the first is out of budget the next one is tried.
* A local budget (requests/min and tokens/min per model) stops us from even
  sending a call that would be rate-limited, so we never wait on a 429.
* Hard per-call timeout, temperature 0 and a fixed seed for repeatability.
* Results are cached by prompt hash: the same input gives the same output.
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import deque

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODELS = "llama-3.3-70b-versatile,meta-llama/llama-4-scout-17b-16e-instruct,llama-3.1-8b-instant"
# Conservative per-model budgets (a little under the provider's published limits).
_TPM = {"llama-3.3-70b-versatile": 10_000, "meta-llama/llama-4-scout-17b-16e-instruct": 25_000,
        "llama-3.1-8b-instant": 5_000}
_RPM_DEFAULT = 25
_TPM_DEFAULT = 5_000


class _Budget:
    def __init__(self, rpm: int, tpm: int) -> None:
        self.rpm, self.tpm = rpm, tpm
        self.events: deque = deque()  # (timestamp, tokens)
        self.blocked_until = 0.0

    def _trim(self, now: float) -> None:
        while self.events and now - self.events[0][0] > 60:
            self.events.popleft()

    def try_take(self, tokens: int) -> bool:
        now = time.time()
        if now < self.blocked_until:
            return False
        self._trim(now)
        used = sum(t for _, t in self.events)
        if len(self.events) >= self.rpm or used + tokens > self.tpm:
            return False
        self.events.append((now, tokens))
        return True


class LLM:
    def __init__(self) -> None:
        self.api_key = os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY") or ""
        self.base_url = (os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.models = [m.strip() for m in (os.environ.get("LLM_MODELS") or DEFAULT_MODELS).split(",") if m.strip()]
        self.timeout = float(os.environ.get("LLM_TIMEOUT", "5"))
        self.enabled = bool(self.api_key) and os.environ.get("LLM_DISABLED", "0") != "1"
        self._lock = threading.Lock()
        self._budgets = {m: _Budget(_RPM_DEFAULT, _TPM.get(m, _TPM_DEFAULT)) for m in self.models}
        self._cache: dict[str, str] = {}
        self._ssl = ssl.create_default_context()
        self.stats = {"calls": 0, "ok": 0, "fail": 0, "skipped_budget": 0, "cache_hits": 0}
        self.transport = None  # tests can inject a fake: fn(model, messages) -> str

    @property
    def model_label(self) -> str:
        return self.models[0] if self.enabled and self.models else "deterministic (no LLM key)"

    def chat_json(self, system: str, user: str, max_tokens: int = 400, deadline: float | None = None) -> dict | None:
        """Return the parsed JSON object the model produced, or None."""
        if not self.enabled and self.transport is None:
            return None
        key = hashlib.sha256((system + "\x00" + user).encode()).hexdigest()
        with self._lock:
            if key in self._cache:
                self.stats["cache_hits"] += 1
                return _parse_json(self._cache[key])
        est_tokens = (len(system) + len(user)) // 3 + max_tokens
        for model in self.models:
            remaining = (deadline - time.time()) if deadline else self.timeout
            if remaining < 1.5:
                return None
            with self._lock:
                ok = self._budgets[model].try_take(est_tokens)
            if not ok:
                self.stats["skipped_budget"] += 1
                continue
            self.stats["calls"] += 1
            try:
                text = self._call(model, system, user, max_tokens, min(self.timeout, remaining))
            except _RateLimited as e:
                with self._lock:
                    self._budgets[model].blocked_until = time.time() + e.retry_after
                self.stats["fail"] += 1
                continue
            except Exception:
                self.stats["fail"] += 1
                continue
            parsed = _parse_json(text)
            if parsed is None:
                self.stats["fail"] += 1
                continue
            self.stats["ok"] += 1
            with self._lock:
                self._cache[key] = text
            return parsed
        return None

    def _call(self, model: str, system: str, user: str, max_tokens: int, timeout: float) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.transport is not None:
            return self.transport(model, messages)
        body = json.dumps({"model": model, "messages": messages, "temperature": 0, "seed": 7,
                           "max_tokens": max_tokens, "response_format": {"type": "json_object"}}).encode()
        req = urllib.request.Request(self.base_url + "/chat/completions", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {self.api_key}",
                                              "Content-Type": "application/json",
                                              "User-Agent": "vera-bot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self._ssl) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = e.headers.get("retry-after") if e.headers else None
                raise _RateLimited(float(ra) if ra and ra.replace(".", "").isdigit() else 20.0)
            raise
        return data["choices"][0]["message"]["content"]


class _RateLimited(Exception):
    def __init__(self, retry_after: float) -> None:
        super().__init__("rate limited")
        self.retry_after = min(max(retry_after, 2.0), 120.0)


def _parse_json(text: str) -> dict | None:
    if not isinstance(text, str):
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):] if "{" in t else t
    for candidate in (t, t[t.find("{"): t.rfind("}") + 1] if "{" in t and "}" in t else ""):
        if not candidate:
            continue
        try:
            v = json.loads(candidate)
            return v if isinstance(v, dict) else None
        except ValueError:
            continue
    return None
