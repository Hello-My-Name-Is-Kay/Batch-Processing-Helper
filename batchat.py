#!/usr/bin/env python3
"""Groq batch chat — one request per turn, polled to completion.

Setup:
    export GROQ_API_KEY=...
    pip install requests

Run:
    python3 groq_batch_chat.py                 # interactive loop
    python3 groq_batch_chat.py -m "hello"      # one-shot
"""

import argparse
import json
import os
import sys
import tempfile
import time
import uuid

try:
    import requests
except ImportError:
    sys.exit("requests is required: pip install requests")

BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
DEFAULT_MODEL = os.environ.get("GROQ_BATCH_MODEL", "openai/gpt-oss-20b")
DEFAULT_SYSTEM = os.environ.get("GROQ_BATCH_SYSTEM") or None
DEFAULT_MAX_TOKENS = int(os.environ.get("GROQ_BATCH_MAX_TOKENS", "2048"))
DEFAULT_WINDOW = os.environ.get("GROQ_BATCH_WINDOW", "24h")
DEFAULT_POLL = float(os.environ.get("GROQ_BATCH_POLL", "10"))
DEFAULT_MAX_WAIT = float(os.environ.get("GROQ_BATCH_MAX_WAIT_MIN", "60"))

SESSION = requests.Session()


def _request(method, path, *, retries=3, timeout=(10, 120), **kwargs):
    url = BASE_URL + path
    headers = {"Authorization": f"Bearer {API_KEY}"}
    headers.update(kwargs.pop("headers", {}) or {})
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = SESSION.request(method, url, headers=headers, timeout=timeout, **kwargs)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(min(2 ** attempt, 15))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            if attempt < retries:
                time.sleep(min(2 ** attempt, 15))
    raise last


def upload_jsonl(path):
    with open(path, "rb") as fh:
        r = _request("POST", "/files",
                     files={"file": ("batch_input.jsonl", fh)},
                     data={"purpose": "batch"})
    return r.json()["id"]


def create_batch(file_id, window):
    r = _request("POST", "/batches", json={
        "input_file_id": file_id,
        "endpoint": "/v1/chat/completions",
        "completion_window": window,
    })
    return r.json()


def get_batch(batch_id):
    return _request("GET", f"/batches/{batch_id}").json()


def download_file(file_id):
    return _request("GET", f"/files/{file_id}/content").content


def build_jsonl(message, model, system, max_tokens, custom_id):
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": message})
    line = {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": msgs,
            "max_completion_tokens": max_tokens,
        },
    }
    return json.dumps(line, ensure_ascii=False) + "\n"


def extract_reply(raw, custom_id):
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("custom_id") != custom_id:
            continue
        if obj.get("error"):
            raise RuntimeError(f"request failed: {obj['error']}")
        body = (obj.get("response") or {}).get("body") or {}
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"no choices in response: {json.dumps(body)[:500]}")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            content = msg.get("reasoning") or ""
        return content.strip()
    raise RuntimeError(f"custom_id {custom_id} not found in output")


def ask(message, *, model, system, max_tokens, window, poll, max_wait, dry_run=False):
    custom_id = f"chat-{uuid.uuid4().hex[:12]}"
    payload = build_jsonl(message, model, system, max_tokens, custom_id)
    if dry_run:
        print(payload, end="")
        return ""

    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="groq_batch_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        file_id = upload_jsonl(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    batch = create_batch(file_id, window)
    batch_id = batch["id"]
    print(f"  submitted {batch_id}", file=sys.stderr)

    deadline = time.time() + max_wait * 60
    last = None
    while time.time() < deadline:
        time.sleep(poll)
        info = get_batch(batch_id)
        status = info.get("status")
        if status != last:
            print(f"  status: {status}", file=sys.stderr)
            last = status
        if status == "completed":
            out_id = info.get("output_file_id")
            if not out_id:
                raise RuntimeError(
                    f"completed without output_file_id "
                    f"(error_file_id={info.get('error_file_id')})")
            return extract_reply(download_file(out_id), custom_id)
        if status in ("failed", "expired", "cancelled"):
            raise RuntimeError(f"batch {status}: {info.get('errors') or info.get('error')}")
    raise TimeoutError(f"batch {batch_id} still running after {max_wait} min")


def _loop(args):
    while True:
        try:
            line = input("\n> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line.strip():
            continue
        try:
            reply = ask(line.strip(), model=args.model, system=args.system,
                        max_tokens=args.max_tokens, window=args.window,
                        poll=args.poll, max_wait=args.max_wait)
        except Exception as e:
            print(f"  error: {e}", file=sys.stderr)
            continue
        if reply:
            print(reply)


def main():
    p = argparse.ArgumentParser(description="Groq batch chat")
    p.add_argument("-m", "--message", help="send one message and exit")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--system", default=DEFAULT_SYSTEM)
    p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p.add_argument("--window", default=DEFAULT_WINDOW, help="e.g. 24h, 48h, 7d")
    p.add_argument("--poll", type=float, default=DEFAULT_POLL, help="seconds between status checks")
    p.add_argument("--max-wait", type=float, default=DEFAULT_MAX_WAIT, help="minutes to wait per turn")
    p.add_argument("--dry-run", action="store_true", help="print JSONL, do not submit")
    args = p.parse_args()

    if not args.dry_run and not API_KEY:
        sys.exit("GROQ_API_KEY is not set")

    if args.message is not None:
        reply = ask(args.message, model=args.model, system=args.system,
                    max_tokens=args.max_tokens, window=args.window,
                    poll=args.poll, max_wait=args.max_wait, dry_run=args.dry_run)
        if reply:
            print(reply)
    else:
        _loop(args)


if __name__ == "__main__":
    main()