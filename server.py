"""HTTP server for the judge harness (Python standard library only).

    GET  /v1/healthz     liveness + counts of contexts the judge pushed
    GET  /v1/metadata    team / approach
    POST /v1/context     store a context (200 / 409 stale / 400 malformed)
    POST /v1/tick        proactive messages
    POST /v1/reply       answer a merchant/customer reply (send / wait / end)
    POST /v1/teardown    wipe state at the end of the test

Run:  python server.py            (PORT env var, default 8080)

Every handler is wrapped so that an internal error still returns valid JSON
of the right shape (empty actions, or a "wait"), never a crash or a 500.
Each request also has a watchdog: if work ever exceeds REQUEST_DEADLINE
seconds, a safe answer is returned instead of letting the judge time out.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from vera.bot import VERSION, Bot  # noqa: E402

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("vera")

BOT = Bot(data_dir=ROOT / "dataset",
          snapshot=os.environ.get("SNAPSHOT_PATH", str(Path(os.environ.get("TMPDIR", "/tmp")) / "vera_snapshot.json")))
REQUEST_DEADLINE = float(os.environ.get("REQUEST_DEADLINE", "12"))
WORKERS = cf.ThreadPoolExecutor(max_workers=16)

META = {
    "team_name": os.environ.get("TEAM_NAME", "Gurmesh Singh"),
    "team_members": [m.strip() for m in os.environ.get("TEAM_MEMBERS", "Gurmesh Singh").split(",")],
    "model": "",
    "approach": ("Deterministic decision engine (trigger playbooks + evidence synthesis from merchant data + "
                 "grounding guard) with optional LLM polish under strict number checks; rule-based reply router "
                 "for auto-replies, intent, opt-out, hostility and off-topic asks."),
    "contact_email": os.environ.get("CONTACT_EMAIL", "gurmeshsingh120@gmail.com"),
    "version": VERSION,
    "submitted_at": os.environ.get("SUBMITTED_AT", "2026-10-22T00:00:00Z"),
}


def _with_deadline(fn, fallback, *args):
    fut = WORKERS.submit(fn, *args)
    try:
        return fut.result(timeout=REQUEST_DEADLINE)
    except cf.TimeoutError:
        log.error("deadline hit in %s", getattr(fn, "__name__", fn))
        return fallback
    except Exception:
        log.error("handler error: %s", traceback.format_exc())
        return fallback


def handle_context(body: dict) -> tuple[int, dict]:
    scope, cid, version = body.get("scope"), body.get("context_id"), body.get("version")
    payload = body.get("payload")
    if not isinstance(cid, str) or not cid:
        return 400, {"accepted": False, "reason": "invalid_context_id", "details": "context_id must be a string"}
    try:
        version = int(version)
    except (TypeError, ValueError):
        return 400, {"accepted": False, "reason": "invalid_version", "details": "version must be an integer"}
    res = BOT.store.put(str(scope), cid, version, payload)
    if res["ok"]:
        return 200, {"accepted": True, "ack_id": res["ack_id"], "stored_at": res["stored_at"]}
    if res["status"] == 409:
        return 409, {"accepted": False, "reason": "stale_version", "current_version": res["current_version"]}
    return 400, {"accepted": False, "reason": res["reason"], "details": res.get("details", "")}


def handle_tick(body: dict) -> dict:
    ids = body.get("available_triggers")
    if not isinstance(ids, list):
        ids = []
    return BOT.tick(body.get("now"), ids)


def handle_reply(body: dict) -> dict:
    out = BOT.reply(body)
    if out.get("action") == "send" and not str(out.get("body", "")).strip():
        return {"action": "wait", "wait_seconds": 1800, "rationale": "Nothing useful to add right now."}
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "VeraBot/" + VERSION

    def log_message(self, fmt, *args):  # route through logging, keep it short
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict | None:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > 2_000_000:
            self.rfile.read(n)
            return None
        raw = self.rfile.read(n) if n else b""
        try:
            obj = json.loads(raw.decode("utf-8") or "{}")
            return obj if isinstance(obj, dict) else None
        except (ValueError, UnicodeDecodeError):
            return None

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")
        if path in ("/v1/healthz", "/healthz", ""):
            self._send(200, {"status": "ok", "uptime_seconds": int(time.time() - BOT.started),
                             "contexts_loaded": BOT.store.counts()})
        elif path == "/v1/metadata":
            meta = dict(META, model=BOT.llm.model_label)
            self._send(200, meta)
        else:
            self._send(404, {"error": "not_found"})

    def do_HEAD(self):  # noqa: N802  (monitors often use HEAD)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")
        t0 = time.time()
        body = self._body()
        if path == "/v1/context":
            if body is None:
                self._send(400, {"accepted": False, "reason": "malformed_json", "details": "body must be a JSON object"})
                return
            code, obj = _with_deadline(handle_context, (500, {"accepted": False, "reason": "internal_error"}), body)
            self._send(code, obj)
        elif path == "/v1/tick":
            obj = _with_deadline(handle_tick, {"actions": []}, body or {})
            log.info("tick: %d triggers -> %d actions in %.2fs", len((body or {}).get("available_triggers") or []),
                     len(obj.get("actions", [])), time.time() - t0)
            self._send(200, obj)
        elif path == "/v1/reply":
            fallback = {"action": "wait", "wait_seconds": 900, "rationale": "Taking a moment before replying."}
            obj = _with_deadline(handle_reply, fallback, body or {})
            log.info("reply %s: %s in %.2fs", (body or {}).get("conversation_id"), obj.get("action"), time.time() - t0)
            self._send(200, obj)
        elif path == "/v1/teardown":
            BOT.teardown()
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not_found"})


def _snapshot_loop():
    while True:
        time.sleep(3)
        BOT.store.flush_if_dirty()


def main():
    port = int(os.environ.get("PORT", "8080"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=_snapshot_loop, daemon=True).start()
    log.info("Vera bot %s on :%d | LLM: %s | seed contexts: %d", VERSION, port, BOT.llm.model_label, BOT.seeded)
    srv.serve_forever()


if __name__ == "__main__":
    main()
