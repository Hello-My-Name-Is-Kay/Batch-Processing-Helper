#!/usr/bin/env python3
"""batch-gateway: an OpenAI-compatible endpoint that answers every chat request with a Groq batch.

Anything that speaks the OpenAI Chat Completions protocol (Pi, the OpenAI SDKs, curl, your own
agent runners) can use batch models by pointing at this server:

    base URL   http://127.0.0.1:8787/v1
    API key    a gateway key (see `token`), NOT a provider key

The provider key (GROQ_API_KEY) stays inside the gateway. Each client gets its own gateway key,
which can carry a token budget and a model allow-list, and every call is written to a ledger.

Requests that arrive close together are merged into ONE batch (default window: 1 second), so a
team of agents calling at once costs one batch, not one batch each.

Usage:
    batch_gateway.py serve [--port 8787] [--window 1.0]
    batch_gateway.py token                         # print the default gateway key
    batch_gateway.py token new NAME [--budget N] [--models a,b] [--admin]
    batch_gateway.py stats                         # per-key totals from the ledger

Endpoints: POST /v1/chat/completions, GET /v1/models, GET /v1/gateway/stats (admin), GET /health.
Not supported: embeddings, images, audio, n>1. `stream` is accepted and emulated (the reply is
sent in one piece, with keep-alive pings while the batch runs), because batches cannot stream.

Needs Python 3.9+ and `requests`.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import queue
import secrets
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("BATCH_GATEWAY_HOME") or Path.home() / ".config" / "batch-gateway")
STATE_DIR = Path(os.environ.get("BATCH_GATEWAY_STATE") or Path.home() / ".local" / "state" / "batch-gateway")
BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
DEFAULT_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b", "qwen/qwen3.8-27b"]
DEFAULT_MODEL = os.environ.get("BATCH_GATEWAY_MODEL", "openai/gpt-oss-20b")
MAX_BODY = 2_000_000
DEFAULT_MAX_COMPLETION = 4096
OPENROUTER_VISIBILITY_GRACE_S = 60
DROP_FIELDS = ("stream", "stream_options", "n")
NO_DATA = "NO DATA YET"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Provider key (never printed, never returned to clients)
# --------------------------------------------------------------------------

def find_provider_key():
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        return key, "environment"
    helper = os.environ.get("BATCH_HELPER_DIR") or str(Path.home() / "Projects/tools/Batch-Processing-Helper")
    for path in (CONFIG_DIR / ".env", Path.home() / ".config" / "batch-orchestrator" / ".env",
                 Path(helper).expanduser() / ".env"):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                name, _, value = line.strip().partition("=")
                if name == "GROQ_API_KEY" and value.strip():
                    return value.strip().strip("\"'"), str(path)
        except OSError:
            continue
    return "", ""


class ApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class GroqClient:
    """Minimal Groq batch client with retries (uploads are re-sendable bytes)."""

    def __init__(self, key, base_url=BASE_URL):
        import requests
        self._requests = requests
        self.base_url, self._key = base_url, key
        self.session = requests.Session()

    def _req(self, method, path, retries=4, timeout=(10, 120), **kw):
        headers = {"Authorization": f"Bearer {self._key}"}
        last = None
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.request(method, self.base_url + path, headers=headers, timeout=timeout, **kw)
            except self._requests.RequestException as e:
                last = ApiError(f"{method} {path}: {type(e).__name__}")
            else:
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                    last = ApiError(f"{method} {path}: HTTP {resp.status_code}", resp.status_code)
                elif resp.status_code >= 400:
                    raise ApiError(f"{method} {path}: HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
                else:
                    return resp
            time.sleep(min(2 ** attempt, 20))
        raise last

    def submit(self, jsonl_bytes):
        up = self._req("POST", "/files", files={"file": ("batch_input.jsonl", jsonl_bytes)},
                       data={"purpose": "batch"}, timeout=(10, 300)).json()
        return self._req("POST", "/batches", json={"input_file_id": up["id"], "endpoint": "/v1/chat/completions",
                                                   "completion_window": "24h"}).json()["id"]

    def poll(self, batch_id):
        return self._req("GET", f"/batches/{batch_id}").json()

    def download(self, file_id):
        return self._req("GET", f"/files/{file_id}/content", timeout=(10, 300)).content

    def models(self):
        return [m["id"] for m in self._req("GET", "/models").json().get("data", [])]

    def results(self, info):
        results = {}
        for key in ("output_file_id", "error_file_id"):
            if info.get(key):
                for line in self.download(info[key]).decode("utf-8", "replace").splitlines():
                    if line.strip():
                        obj = json.loads(line)
                        results[obj.get("custom_id")] = obj
        return results


class OpenRouterClient(GroqClient):
    """OpenRouter JSON batch API; never falls back to synchronous completions."""

    def __init__(self, key):
        super().__init__(key, "https://openrouter.ai/api/v1")

    def catalog(self):
        data = self._req("GET", "/models").json()["data"]
        return [m for m in data if m["id"].endswith(":batch")
                and "text" in m.get("architecture", {}).get("output_modalities", ["text"])]

    def submit(self, jsonl_bytes):
        lines = [json.loads(line) for line in jsonl_bytes.decode().splitlines() if line.strip()]
        for line in lines:
            body = line["body"]
            body["model"] = body["model"].removeprefix("openrouter/").removesuffix(":batch")
            if "max_completion_tokens" in body:
                body["max_tokens"] = body.pop("max_completion_tokens")
        models = {line["body"]["model"] for line in lines}
        if len(models) != 1:
            raise ValueError("OpenRouter batches must contain a single model")
        payload = {"endpoint": "/v1/chat/completions", "model": next(iter(models)), "requests": lines}
        # Submission is non-idempotent: do not retry and accidentally duplicate a paid batch.
        return self._req("POST", "/batches", retries=1, json=payload).json()["id"]

    def results(self, info):
        rows = info.get("results")
        if not isinstance(rows, list):
            raise ApiError("Completed OpenRouter batch did not contain embedded results")
        return {row["custom_id"]: row for row in rows}


def openrouter_key():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    try:
        result = subprocess.run(["pi", "auth", "print-api-key", "--provider", "openrouter"],
                                capture_output=True, text=True, timeout=20)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# --------------------------------------------------------------------------
# Gateway keys and ledger
# --------------------------------------------------------------------------

class KeyStore:
    """Gateway (virtual) keys: token -> {name, admin, token_budget, models}."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.keys = self._load()
        if not self.keys:
            self.create("local", admin=True)

    def _load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.keys, fh, indent=1)
        os.replace(tmp, self.path)
        self._mtime = self.path.stat().st_mtime_ns

    def create(self, name, budget=None, models=None, admin=False):
        token = "gw-" + secrets.token_urlsafe(24)
        with self.lock:
            self.keys[token] = {"name": name, "admin": admin, "token_budget": budget, "models": models}
            self._save()
        return token

    def _refresh(self):
        """Pick up keys added by `token new` while the server is running."""
        try:
            mtime = self.path.stat().st_mtime_ns
        except OSError:
            return
        if mtime != getattr(self, "_mtime", None):
            with self.lock:
                loaded = self._load()
                if loaded:
                    self.keys = loaded
                self._mtime = mtime

    def lookup(self, token):
        self._refresh()
        found = None
        for candidate, info in self.keys.items():  # compare every key: no early exit on a match
            if hmac.compare_digest(candidate.encode(), (token or "").encode()):
                found = info
        return found

    def default_token(self):
        for token, info in self.keys.items():
            if info.get("name") == "local":
                return token
        return next(iter(self.keys))


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.tokens = {}
        for entry in self.read():
            self.tokens[entry["key"]] = self.tokens.get(entry["key"], 0) + (entry.get("total_tokens") or 0)

    def read(self):
        try:
            return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        except (OSError, ValueError):
            return []

    def add(self, entry):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
            self.tokens[entry["key"]] = self.tokens.get(entry["key"], 0) + (entry.get("total_tokens") or 0)

    def summary(self):
        entries = self.read()
        if not entries:
            return {"keys": NO_DATA, "batches": NO_DATA, "requests_per_batch": NO_DATA}
        out = {}
        for e in entries:
            s = out.setdefault(e["key"], {"requests": 0, "ok": 0, "errors": 0, "prompt_tokens": 0,
                                          "completion_tokens": 0, "total_tokens": 0, "latency_s": 0.0})
            s["requests"] += 1
            s["ok" if e.get("status") == 200 else "errors"] += 1
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                s[k] += e.get(k) or 0
            s["latency_s"] += e.get("latency_s") or 0
        for s in out.values():
            s["avg_latency_s"] = round(s.pop("latency_s") / max(s["requests"], 1), 2)
        batches = {}
        for e in entries:
            if e.get("batch_id"):
                batches[e["batch_id"]] = batches.get(e["batch_id"], 0) + 1
        return {"keys": out, "batches": len(batches) or NO_DATA,
                "requests_per_batch": round(sum(batches.values()) / len(batches), 2) if batches else NO_DATA}


# --------------------------------------------------------------------------
# Batching dispatcher
# --------------------------------------------------------------------------

def error_body(message, etype="invalid_request_error", code=None):
    return {"error": {"message": message, "type": etype, "code": code}}


class Pending:
    def __init__(self, body, key_name):
        self.body, self.key_name = body, key_name
        self.event = threading.Event()
        self.status, self.payload, self.batch_id, self.batch_size = 500, None, None, 1
        self.t0 = time.time()


class Dispatcher:
    """Merges requests that arrive within `window` seconds into one batch."""

    def __init__(self, client, window=1.0, max_batch=100, max_wait_s=900):
        self.client, self.window, self.max_batch, self.max_wait_s = client, window, max_batch, max_wait_s
        self.q = queue.Queue()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def submit(self, pending):
        self.q.put(pending)

    def _loop(self):
        while True:
            items = [self.q.get()]
            deadline = time.time() + self.window
            while len(items) < self.max_batch:
                left = deadline - time.time()
                if left <= 0:
                    break
                try:
                    items.append(self.q.get(timeout=left))
                except queue.Empty:
                    break
            threading.Thread(target=self._run, args=(items,), daemon=True).start()

    def _fail(self, items, status, message, code):
        for p in items:
            p.status, p.payload = status, error_body(message, "api_error", code)
            p.event.set()

    def _run(self, items):
        ids = {f"gw-{uuid.uuid4().hex[:16]}": p for p in items}
        lines = [{"custom_id": cid, "method": "POST", "url": "/v1/chat/completions", "body": p.body}
                 for cid, p in ids.items()]
        try:
            batch_id = self.client.submit("".join(json.dumps(l) + "\n" for l in lines).encode("utf-8"))
        except Exception as e:  # noqa: BLE001 - every failure must reach the waiting clients
            return self._fail(items, 502, f"could not submit the batch: {e}", "batch_submit_failed")
        for p in items:
            p.batch_id, p.batch_size = batch_id, len(items)
        log(f"batch {batch_id}: {len(items)} request(s)")
        started = time.monotonic()
        deadline, interval = started + self.max_wait_s, 1.0
        visibility_deadline = started + min(OPENROUTER_VISIBILITY_GRACE_S, self.max_wait_s)
        try:
            while True:
                if time.monotonic() >= deadline:
                    return self._fail(items, 504, f"batch {batch_id} did not finish in time", "batch_timeout")
                try:
                    info = self.client.poll(batch_id)
                except ApiError as exc:
                    # OpenRouter can acknowledge creation before its status endpoint
                    # sees the job. Only retry this known, newly submitted batch;
                    # never re-submit paid work or mask other HTTP errors.
                    if (isinstance(self.client, OpenRouterClient) and exc.status == 404
                            and time.monotonic() < visibility_deadline):
                        log(f"batch {batch_id}: status not visible yet (404); retrying same batch")
                        time.sleep(min(interval, max(0, visibility_deadline - time.monotonic())))
                        interval = min(interval * 1.5, 5.0)
                        continue
                    raise
                status = info.get("status")
                if status == "completed":
                    break
                if status in ("failed", "expired", "cancelled"):
                    return self._fail(items, 502, f"batch {status}: {json.dumps(info.get('errors'))[:200]}",
                                      "batch_" + status)
                if time.monotonic() >= deadline:
                    return self._fail(items, 504, f"batch {batch_id} did not finish in time", "batch_timeout")
                time.sleep(min(interval, max(0, deadline - time.monotonic())))
                interval = min(interval * 1.5, 5.0)
            results = self.client.results(info)
        except Exception as e:  # noqa: BLE001
            return self._fail(items, 502, f"batch {batch_id} failed: {e}", "batch_error")
        for cid, p in ids.items():
            obj = results.get(cid)
            resp = (obj or {}).get("response") or {}
            body = resp.get("body") or {}
            if obj is None:
                p.status, p.payload = 502, error_body("no result returned for this request", "api_error", "missing_result")
            elif resp.get("status_code") == 200 and body.get("choices"):
                p.status, p.payload = 200, body
            else:
                err = obj.get("error") or body.get("error") or {"message": f"HTTP {resp.get('status_code')}"}
                if isinstance(err, str):
                    err = {"message": err}
                p.status = resp.get("status_code") or 502
                p.payload = {"error": {"message": err.get("message", "request failed"),
                                       "type": err.get("type", "api_error"), "code": err.get("code")}}
            p.event.set()


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------

def build_batch_body(req, default_model, reasoning_default):
    body = {k: v for k, v in req.items() if k not in DROP_FIELDS}
    body.setdefault("model", default_model)
    if "max_tokens" not in body and "max_completion_tokens" not in body:
        body["max_completion_tokens"] = DEFAULT_MAX_COMPLETION
    if str(body["model"]).startswith("openai/gpt-oss") and "reasoning_effort" not in body and reasoning_default:
        body["reasoning_effort"] = reasoning_default
    return body


def sse_chunks(payload, include_usage):
    """Turn a finished chat completion into OpenAI-style streaming chunks."""
    choice = payload["choices"][0]
    msg = choice.get("message") or {}
    base = {"id": payload.get("id", "chatcmpl-" + uuid.uuid4().hex[:12]), "object": "chat.completion.chunk",
            "created": payload.get("created", int(time.time())), "model": payload.get("model")}
    delta = {"role": "assistant", "content": msg.get("content") or ""}
    if msg.get("tool_calls"):
        delta["tool_calls"] = [{"index": i, **tc} for i, tc in enumerate(msg["tool_calls"])]
    yield {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
    yield {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason") or "stop"}]}
    if include_usage and payload.get("usage"):
        yield {**base, "choices": [], "usage": payload["usage"]}


class Handler(BaseHTTPRequestHandler):
    server_version = "batch-gateway"

    def log_message(self, *args):
        pass

    # -- helpers --
    def _send(self, status, obj, headers=None):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _auth(self):
        header = self.headers.get("Authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        info = self.server.keys.lookup(token)
        if info is None:
            self._send(401, error_body("invalid or missing gateway key", "invalid_request_error", "invalid_api_key"))
        return info

    # -- routes --
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            return self._send(200, {"ok": True})
        info = self._auth()
        if info is None:
            return
        if path == "/v1/models":
            allowed = [m for m in self.server.models if not info.get("models") or m in info["models"]]
            return self._send(200, {"object": "list", "data": [
                {"id": m, "object": "model", "created": 0, "owned_by": "openrouter-batch" if m.startswith("openrouter/") else "groq-batch"} for m in allowed]})
        if path == "/v1/gateway/stats":
            if not info.get("admin"):
                return self._send(403, error_body("admin key required", "invalid_request_error", "forbidden"))
            return self._send(200, self.server.ledger.summary())
        self._send(404, error_body(f"unknown path {path}", "invalid_request_error", "not_found"))

    def do_POST(self):
        if not self.server.begin():
            return self._send(503, error_body("gateway is paused: no new requests are accepted",
                                              "api_error", "paused"))
        try:
            self._handle_post()
        finally:
            self.server.end()

    def _handle_post(self):
        if self.path.split("?")[0] != "/v1/chat/completions":
            return self._send(404, error_body("unknown path", "invalid_request_error", "not_found"))
        info = self._auth()
        if info is None:
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            return self._send(413 if length > MAX_BODY else 400,
                              error_body("request body missing or too large", "invalid_request_error", "bad_body"))
        try:
            req = json.loads(self.rfile.read(length))
            assert isinstance(req, dict) and isinstance(req.get("messages"), list) and req["messages"]
        except (ValueError, AssertionError):
            return self._send(400, error_body("body must be JSON with a non-empty 'messages' list",
                                              "invalid_request_error", "bad_request"))
        srv = self.server
        body = build_batch_body(req, srv.default_model, srv.reasoning_default)
        model = body["model"]
        allowed = [m for m in srv.models if not info.get("models") or m in info["models"]]
        if model not in allowed:
            return self._send(404, error_body(f"model '{model}' is not available through this gateway",
                                              "invalid_request_error", "model_not_found"))
        budget = info.get("token_budget")
        if budget is not None and srv.ledger.tokens.get(info["name"], 0) >= budget:
            return self._send(429, error_body(f"token budget of {budget} used up for key '{info['name']}'",
                                              "insufficient_quota", "budget_exhausted"))
        stream = bool(req.get("stream"))
        pending = Pending(body, info["name"])
        srv.dispatchers.get(model, srv.dispatcher).submit(pending)
        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while not pending.event.wait(5):
                    self.wfile.write(b": waiting for batch\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            pending.event.wait(srv.dispatcher.max_wait_s + 120)
        self._record(info["name"], model, pending)
        headers = {"x-batch-id": pending.batch_id or "", "x-batch-size": str(pending.batch_size)}
        if not stream:
            return self._send(pending.status, pending.payload or error_body("no result", "api_error", "timeout"),
                              headers)
        try:
            if pending.status == 200:
                include = bool((req.get("stream_options") or {}).get("include_usage"))
                for chunk in sse_chunks(pending.payload, include):
                    self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            else:
                self.wfile.write(b"data: " + json.dumps(pending.payload).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _record(self, key_name, model, pending):
        usage = (pending.payload or {}).get("usage") or {} if pending.status == 200 else {}
        err = None if pending.status == 200 else ((pending.payload or {}).get("error") or {}).get("message")
        self.server.ledger.add({
            "ts": int(time.time()), "key": key_name, "model": model, "status": pending.status,
            "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0), "latency_s": round(time.time() - pending.t0, 2),
            "batch_id": pending.batch_id, "batch_size": pending.batch_size, "error": err})
        log(f"{key_name} {model} -> {pending.status} in {time.time() - pending.t0:.1f}s")


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def setup_drain(self):
        self.draining = False
        self.inflight = 0
        self.inflight_lock = threading.Lock()
        self.idle = threading.Event()
        self.idle.set()

    def begin(self):
        with self.inflight_lock:
            if self.draining:
                return False
            self.inflight += 1
            self.idle.clear()
            return True

    def end(self):
        with self.inflight_lock:
            self.inflight -= 1
            if self.inflight == 0:
                self.idle.set()

    def drain(self):
        """Refuse new requests; requests already sent keep going."""
        with self.inflight_lock:
            self.draining = True
            if self.inflight == 0:
                self.idle.set()

    def wait_idle(self):
        self.idle.wait()


def make_server(host, port, client, keys, ledger, models, window=1.0, max_wait_s=900,
                default_model=DEFAULT_MODEL, reasoning_default="low"):
    srv = Server((host, port), Handler)
    srv.keys, srv.ledger, srv.models = keys, ledger, models
    srv.default_model, srv.reasoning_default = default_model, reasoning_default
    srv.dispatcher = Dispatcher(client, window=window, max_wait_s=max_wait_s)
    srv.dispatchers = {}
    srv.setup_drain()
    return srv


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _drain_then_exit(srv):
    srv.drain()
    log("paused: no new requests; finishing the requests already sent")
    srv.wait_idle()
    log("paused: all sent requests finished; exiting")
    srv.shutdown()


def cmd_serve(args):
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        print("error: refusing to listen on a non-local address without --allow-remote", file=sys.stderr)
        return 1
    try:
        from batch_credentials import load_credentials
        load_credentials()
    except ImportError:
        pass
    key, source = find_provider_key()
    if not key:
        print("error: no GROQ_API_KEY (environment, ~/.config/batch-gateway/.env)", file=sys.stderr)
        return 1
    client = GroqClient(key)
    try:
        live = client.models()
        models = [m for m in DEFAULT_MODELS if m in live] or [m for m in live if "whisper" not in m]
    except Exception as e:  # noqa: BLE001
        log(f"could not list Groq models ({e}); using the built-in list")
        models = list(DEFAULT_MODELS)
    keys = KeyStore(CONFIG_DIR / "keys.json")
    ledger = Ledger(STATE_DIR / "ledger.jsonl")
    srv = make_server(args.host, args.port, client, keys, ledger, models, window=args.window,
                      max_wait_s=int(args.max_wait * 60))
    router_key = openrouter_key()
    if router_key:
        try:
            router = OpenRouterClient(router_key)
            catalog = router.catalog()
            for entry in catalog:
                model_id = "openrouter/" + entry["id"]
                # Separate queues prevent mixing models in OpenRouter's single-model batches.
                srv.dispatchers[model_id] = Dispatcher(router, window=args.window,
                                                       max_wait_s=int(args.max_wait * 60))
                srv.models.append(model_id)
            log(f"OpenRouter: {len(catalog)} batch models registered")
        except Exception as exc:
            log(f"OpenRouter unavailable: {exc}")
    else:
        log("OpenRouter disabled: no credentials (environment, MCP setup, or Pi auth)")
    log(f"provider key found ({source}); models: {', '.join(models)}")
    log(f"listening on http://{args.host}:{srv.server_address[1]}/v1  (batch window {args.window}s)")
    log(f"gateway keys: {keys.path}   ledger: {ledger.path}")
    def pause_and_exit(*_):
        threading.Thread(target=_drain_then_exit, args=(srv,), daemon=True).start()

    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, pause_and_exit)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("stopped")
    finally:
        if _read_pid() == os.getpid():
            PID_FILE.unlink(missing_ok=True)
    return 0


def cmd_token(args):
    keys = KeyStore(CONFIG_DIR / "keys.json")
    if args.action == "new":
        models = [m.strip() for m in args.models.split(",")] if args.models else None
        print(keys.create(args.name, budget=args.budget, models=models, admin=args.admin))
    else:
        print(keys.default_token())
    return 0


def cmd_stats(args):
    print(json.dumps(Ledger(STATE_DIR / "ledger.jsonl").summary(), indent=1))
    return 0


PID_FILE = STATE_DIR / "gateway.pid"
LOG_FILE = STATE_DIR / "gateway.log"
PAUSE_WARNING = ("WARNING (placeholder): pause refuses new requests and exits when the requests already "
                 "sent have finished. It cannot resume a paused gateway; run `batch-gateway start` instead.")


def _read_pid():
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def _running_pid():
    """The gateway's pid if it is running, else None (cleans up a stale pid file)."""
    pid = _read_pid()
    if pid is None:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        PID_FILE.unlink(missing_ok=True)
        return None
    return pid


def cmd_start(args):
    if _running_pid():
        print(f"already running (pid {_running_pid()}) on http://127.0.0.1:{args.port}/v1")
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    script = str(Path(__file__).resolve())
    with open(LOG_FILE, "a", encoding="utf-8") as log_fh:
        proc = subprocess.Popen(
            [sys.executable, script, "serve", "--port", str(args.port), "--window", str(args.window)],
            stdin=subprocess.DEVNULL, stdout=log_fh, stderr=subprocess.STDOUT, start_new_session=True)
    PID_FILE.write_text(str(proc.pid))
    time.sleep(1.5)
    if proc.poll() is not None:
        PID_FILE.unlink(missing_ok=True)
        print(f"failed to start; see {LOG_FILE}", file=sys.stderr)
        return 1
    print(f"started (pid {proc.pid}) on http://127.0.0.1:{args.port}/v1; log: {LOG_FILE}")
    return 0


def cmd_stop(args):
    pid = _running_pid()
    if pid is None:
        print("not running")
        return 0
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        if _running_pid() is None:
            break
        time.sleep(0.1)
    print("stopped" if _running_pid() is None else "stop sent; still shutting down")
    return 0


def cmd_restart(args):
    cmd_stop(args)
    return cmd_start(args)


def cmd_pause(args):
    print(PAUSE_WARNING)
    pid = _running_pid()
    if pid is None:
        print("not running")
        return 0
    os.kill(pid, signal.SIGUSR1)
    for _ in range(600):
        if _running_pid() is None:
            print("paused: exited after the requests already sent finished")
            return 0
        time.sleep(0.1)
    print("still finishing the requests already sent; see the log")
    return 0


def cmd_gui(args):
    """Launch the desktop UI. Requires PySide6 and gateway_ui module."""
    try:
        # Add the gateway installation directory to sys.path so gateway_ui can be found
        ui_path = Path.home() / ".local" / "share" / "batch-gateway"
        sys.path.insert(0, str(ui_path))
        from gateway_ui.cli import main as gui_main
        gui_main([])
    except ImportError as e:
        log(f"Desktop UI not available: {e}")
        log("Ensure PySide6 is installed: pip install PySide6")
        return 1
    except Exception as e:
        log(f"Error launching UI: {e}")
        return 1
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="OpenAI-compatible gateway that answers chat requests with Groq batches")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--window", type=float, default=1.0, help="seconds to merge requests into one batch")
    s.add_argument("--max-wait", type=float, default=15, help="minutes before a batch is given up on")
    s.add_argument("--allow-remote", action="store_true")
    t = sub.add_parser("token", help="print the default gateway key, or create a new one")
    t.add_argument("action", nargs="?", choices=["new"], default=None)
    t.add_argument("name", nargs="?", default=None)
    t.add_argument("--budget", type=int, default=None, help="token budget for the key")
    t.add_argument("--models", default=None, help="comma-separated allow-list")
    t.add_argument("--admin", action="store_true")
    sub.add_parser("stats")
    sub.add_parser("gui", help="launch the desktop control panel (requires PySide6)")
    for name, text in (("start", "run the gateway in the background"),
                       ("restart", "stop, then start"),
                       ("stop", "stop now; requests in progress fail"),
                       ("pause", "refuse new requests, exit when sent ones finish (placeholder)")):
        svc = sub.add_parser(name, help=text)
        if name in ("start", "restart"):
            svc.add_argument("--port", type=int, default=8787)
            svc.add_argument("--window", type=float, default=1.0)
    args = p.parse_args(argv)
    if args.cmd == "token" and args.action == "new" and not args.name:
        p.error("token new needs a NAME")
    return {"serve": cmd_serve, "token": cmd_token, "stats": cmd_stats, "start": cmd_start,
            "stop": cmd_stop, "restart": cmd_restart, "pause": cmd_pause, "gui": cmd_gui}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
