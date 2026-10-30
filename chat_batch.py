#!/usr/bin/env python3
"""Simple chat interface using batch processing.

Submit ONE request as a batch, poll until completed, then show the response.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from batch_common import (
    resolve_paths,
    load_state,            # FIX: was missing → NameError
    )
from providers import get_provider
from batch_submit import submit_batch


DEFAULT_SYSTEM_MESSAGE = "You are an AI assistant. Be helpful and concise."


def chat_batch_interactive(items, system_message=None, agent=None,
                           max_tokens=None, poll_interval=30,
                           max_wait_minutes=120):
    if not items:
        print("❌ No items to submit.", file=sys.stderr)
        return None

    # Guard against runaway / crashy configs
    if poll_interval <= 0:
        print(f"❌ --poll-interval must be > 0 (got {poll_interval})", file=sys.stderr)
        return None
    if max_wait_minutes <= 0:
        print(f"❌ --max-wait must be > 0 (got {max_wait_minutes})", file=sys.stderr)
        return None

    result = submit_batch(
        items,
        system_message=system_message,
        agent=agent,
        max_tokens=max_tokens,
        dry_run=False,
    )
    if result.get('dry_run'):
        print("❌ Dry run - nothing submitted.", file=sys.stderr)
        return None

    batch_id    = result['batch_id']
    request_id  = result['request_id']
    provider_name = result['provider']
    model       = result['model']

    print(f"📤 Submitted batch to {provider_name}, model: {model}")
    print(f"   Batch ID: {batch_id}")
    print(f"   Request ID: {request_id}")
    print("⏳ Polling for completion...\n")

    config = resolve_paths()
    state_file = Path(config['state_file'])

    max_polls = max(1, max_wait_minutes * 60 // poll_interval)
    polls = 0
    status = ''            # FIX: defined before loop

    while polls < max_polls:
        polls += 1
        time.sleep(poll_interval)

        try:
            state = load_state(state_file, repair=True)
        except Exception as e:
            print(f"⚠️  load_state failed: {e}", file=sys.stderr)
            state = {}

        if batch_id not in state:
            if polls % 5 == 1:
                print(f"   ⏱  Batch not yet visible in state (poll {polls})...")
            continue

        info   = state[batch_id]
        status = info.get('status', '')

        if status == 'completed':
            try:
                provider = get_provider(provider_name)
                results  = provider.get_results(batch_id)
            except Exception as e:
                print(f"⚠️  Error getting results: {e}", file=sys.stderr)
                continue

            if not results:
                print("⚠️  Completed but no results returned.", file=sys.stderr)
                return None

            r = results[0]
            content = getattr(r, 'content', None)
            if content is None and isinstance(r, dict):
                content = r.get('content')

            if not content:
                print("⚠️  Completed but response was empty.", file=sys.stderr)
                return None

            print()
            print("=" * 60)
            print("🤖 ASSISTANT RESPONSE:")
            print("=" * 60)
            print(content)
            print("=" * 60)
            print()
            print(f"✅ Completed in {info.get('latency_minutes', '?')} minutes")
            print(f"   Tokens: {info.get('total_tokens', '?')}")
            return content

        if status in ('failed', 'cancelled'):
            print(f"❌ Batch {batch_id} ended with status: {status}", file=sys.stderr)
            if 'error' in info:
                print(f"   Error: {info['error']}", file=sys.stderr)
            return None

        remaining = max(0, max_wait_minutes - (polls * poll_interval / 60))
        if polls % 5 == 1 or status not in ('', 'processing'):
            print(f"   ⏱  Polled {polls} times, ~{remaining:.0f} min remaining...")

    print(f"⏰  Timed out after {max_wait_minutes} minutes waiting for batch {batch_id}",
          file=sys.stderr)
    return None


def _parse_int(name, value):
    try:
        return int(value)
    except ValueError:
        print(f"❌ Invalid {name} value: {value}", file=sys.stderr)
        sys.exit(1)


def main():
    args = sys.argv[1:]
    system_message = None
    agent = None
    max_tokens = None
    polling_interval = 30
    max_wait = 120

    i = 0
    while i < len(args):
        a = args[i]
        if a == '--system' and i + 1 < len(args):
            system_message = args[i + 1]; i += 2
        elif a == '--agent' and i + 1 < len(args):
            agent = args[i + 1]; i += 2
        elif a == '--max-tokens' and i + 1 < len(args):
            max_tokens = _parse_int('--max-tokens', args[i + 1]); i += 2
        elif a == '--poll-interval' and i + 1 < len(args):
            polling_interval = _parse_int('--poll-interval', args[i + 1]); i += 2
        elif a == '--max-wait' and i + 1 < len(args):
            max_wait = _parse_int('--max-wait', args[i + 1]); i += 2
        elif a == '--':
            i += 1
            break
        else:
            break

    if i >= len(args):
        print(
            "Usage: python3 chat_batch.py [--system TEXT] [--agent NAME] "
            "[--max-tokens N] [--poll-interval SEC] [--max-wait MIN] 'MESSAGE'",
            file=sys.stderr,
        )
        sys.exit(1)

    message = args[i]

    if not sys.stdin.isatty():
        try:
            pipe_message = sys.stdin.read().strip()
        except Exception:
            pipe_message = ""
        if pipe_message:
            message = pipe_message

    result = chat_batch_interactive(
        items=[{"message": message}],
        system_message=system_message,
        agent=agent,
        max_tokens=max_tokens,
        poll_interval=polling_interval,
        max_wait_minutes=max_wait,
    )

    if result is None:
        print("\n❌ No response received. Try again or check your API keys.",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()