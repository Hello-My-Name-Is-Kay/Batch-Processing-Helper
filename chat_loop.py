#!/usr/bin/env python3
"""Dead-simple batch chat loop. One script, no history, no logs.

Usage:
    python3 chat_loop.py

Each line you type is submitted as its own single-request batch. It polls
until that batch completes, prints just the assistant reply, then waits
for the next line. Ctrl-D or Ctrl-C to quit.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from batch_common import resolve_paths, load_state
from providers import get_provider
from batch_submit import submit_batch

POLL_INTERVAL = 10   # seconds
MAX_WAIT_MIN  = 30   # give up on a single turn after this


def ask(message: str):
    """Submit one message as a batch, return the reply text or None."""
    try:
        result = submit_batch(
            [{"message": message}],
            system_message=None,
            agent=None,
            max_tokens=None,
            dry_run=False,
        )
    except Exception as e:
        print(f"\n  submit error: {e}", file=sys.stderr)
        return None

    if not result or result.get("dry_run"):
        return None

    batch_id     = result["batch_id"]
    provider_key = result["provider"]

    cfg        = resolve_paths()
    state_file = Path(cfg["state_file"])
    deadline   = time.time() + MAX_WAIT_MIN * 60

    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        try:
            state = load_state(state_file, repair=True)
        except Exception:
            state = {}

        info = state.get(batch_id)
        if not info:
            continue

        status = info.get("status", "")
        if status == "completed":
            try:
                results = get_provider(provider_key).get_results(batch_id)
            except Exception as e:
                print(f"\n  result error: {e}", file=sys.stderr)
                return None
            if not results:
                return None
            r = results[0]
            content = getattr(r, "content", None)
            if content is None and isinstance(r, dict):
                content = r.get("content")
            return content

        if status in ("failed", "cancelled"):
            return None

    print("\n  (timed out)", file=sys.stderr)
    return None


def main():
    print("batch chat — Ctrl-D to quit", file=sys.stderr)
    while True:
        try:
            line = input("\n> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line.strip():
            continue

        # Single stderr line so the user knows it isn't hung (batch is slow).
        print("  …", end="", file=sys.stderr, flush=True)
        reply = ask(line.strip())
        print("\r  \r", end="", file=sys.stderr, flush=True)  # erase the "…"

        if reply:
            print(reply)
        else:
            print("  (no response)", file=sys.stderr)


if __name__ == "__main__":
    main()