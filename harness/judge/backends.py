"""Pluggable LLM backends for the judge.

Two are wired:

*   `claude` -- the local `claude` CLI, using the operator's existing session
    credentials. No API key, but it spends Claude Code quota and runs one call
    at a time at roughly 40 s each.
*   `gemini` -- Google Generative Language REST, using a free-tier key read from
    `.env`. Fast, parallelisable, and free, at the cost of a weaker rubric
    follower.

Which to use is a real decision, not a preference. We measured an 18-point swing
on one message purely from changing the judge's context window, so the judge is
not a neutral instrument. Use `gemini` for iteration and volume; use `claude`
for the runs that actually trigger a decision rule.

Nothing here ships with the bot. The submitted service has no LLM dependency.
"""

from __future__ import annotations

import json
import os
import pathlib
import ssl
import subprocess
import time
import tempfile
import urllib.error
import urllib.request
from typing import Literal, Protocol

import certifi

Backend = Literal["claude", "gemini"]

_SSL = ssl.create_default_context(cafile=certifi.where())

# gemini-2.5-flash is closed to new keys -- the API redirects callers to the 3.x
# line. Flash tier is the right pick here: the judge does rubric-following and
# strict JSON, not open-ended reasoning, and we need volume.
GEMINI_DEFAULT_MODEL = "gemini-3.6-flash"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class BackendError(RuntimeError):
    """Transport or provider failure. Never silently substituted for a score."""


class LLM(Protocol):
    name: str

    def complete(self, system: str, prompt: str, timeout: int) -> str: ...


# ---------------------------------------------------------------------------
# secrets
# ---------------------------------------------------------------------------


def _load_env(path: pathlib.Path | None = None) -> dict[str, str]:
    path = path or pathlib.Path(__file__).resolve().parents[2] / ".env"
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or _load_env().get("GEMINI_API_KEY")
    if not key:
        raise BackendError(
            "GEMINI_API_KEY not found in environment or .env. "
            "Add it to vera-challenge/.env or export it."
        )
    return key


def _scrub(text: str, secret: str) -> str:
    """Never let a key reach a log line or an exception message."""
    return text.replace(secret, "<REDACTED>") if secret else text


# ---------------------------------------------------------------------------
# claude CLI
# ---------------------------------------------------------------------------


class ClaudeCLI:
    name = "claude"

    def complete(self, system: str, prompt: str, timeout: int = 180) -> str:
        # Run in a scratch dir so the CLI does not pick up this project's
        # CLAUDE.md or tooling and let it colour the scoring.
        with tempfile.TemporaryDirectory() as tmp:
            try:
                proc = subprocess.run(
                    ["claude", "-p", f"{system}\n\n{prompt}"],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=tmp,
                )
            except FileNotFoundError as exc:
                raise BackendError("claude CLI not on PATH") from exc
            except subprocess.TimeoutExpired as exc:
                raise BackendError(f"claude timed out after {timeout}s") from exc

        if proc.returncode != 0:
            raise BackendError(f"claude exited {proc.returncode}: {proc.stderr[:400]}")
        if not proc.stdout.strip():
            raise BackendError("claude returned empty output")
        return proc.stdout


# ---------------------------------------------------------------------------
# gemini REST
# ---------------------------------------------------------------------------


# Free-tier capacity is genuinely flaky -- we have seen 503 UNAVAILABLE twice
# in light use. Retry, then fall back down the flash line rather than failing a
# whole experiment run on transient load.
GEMINI_FALLBACKS = ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite")


class Gemini:
    def __init__(self, model: str = GEMINI_DEFAULT_MODEL) -> None:
        self.model = model
        self.name = f"gemini:{model}"

    def complete(self, system: str, prompt: str, timeout: int = 120) -> str:
        """Try the chosen model, then alternates, with backoff between rounds."""
        models = [self.model] + [m for m in GEMINI_FALLBACKS if m != self.model]
        last = ""
        for attempt in range(3):
            for model in models:
                try:
                    return self._once(model, system, prompt, timeout)
                except BackendError as exc:
                    last = str(exc)
                    if "503" not in last and "429" not in last:
                        raise
            time.sleep(2 * (attempt + 1))
        raise BackendError(f"gemini unavailable after retries: {last[:200]}")

    def _once(self, model: str, system: str, prompt: str, timeout: int) -> str:
        key = _gemini_key()
        url = GEMINI_ENDPOINT.format(model=model) + f"?key={key}"

        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                # Scoring must be as reproducible as the provider allows.
                "temperature": 0,
                # Generous: truncation is the failure mode that silently
                # inflates scores in the shipped simulator, and we refuse to
                # reproduce it.
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            body = _scrub(exc.read().decode()[:500], key)
            raise BackendError(f"gemini HTTP {exc.code}: {body}") from exc
        except Exception as exc:
            raise BackendError(
                f"gemini transport error: {_scrub(str(exc), key)}"
            ) from exc

        candidates = data.get("candidates") or []
        if not candidates:
            fb = data.get("promptFeedback", {})
            raise BackendError(f"gemini returned no candidates (feedback={fb})")

        cand = candidates[0]
        finish = cand.get("finishReason")
        if finish not in (None, "STOP"):
            # MAX_TOKENS here would mean a truncated, partially-parseable score.
            raise BackendError(f"gemini finishReason={finish}; treating as failure")

        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        if not text.strip():
            raise BackendError("gemini returned empty text")
        return text


# ---------------------------------------------------------------------------


def get_backend(name: Backend | str = "claude", **kwargs) -> LLM:
    if name == "claude":
        return ClaudeCLI()
    if name == "gemini" or str(name).startswith("gemini"):
        model = kwargs.get("model")
        if not model and ":" in str(name):
            model = str(name).split(":", 1)[1]
        return Gemini(model or GEMINI_DEFAULT_MODEL)
    raise BackendError(f"unknown backend {name!r}; expected 'claude' or 'gemini'")
