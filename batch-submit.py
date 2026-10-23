#!/usr/bin/env python3
"""
Submit one or more requests to the batch pipeline.

Supports multiple providers (Anthropic, OpenRouter, etc.)
via the providers/ abstraction layer.

Usage:
    # Single request
    python3 batch-submit.py "Your task description"

    # Multiple requests in ONE batch (R1: multi-request batches)
    python3 batch-submit.py "Task 1" "Task 2" "Task 3"

    # With system message (applied to ALL requests in the batch)
    python3 batch-submit.py "Task 1" "Task 2" --system "Be concise"

    # With agent/source ownership (R3)
    python3 batch-submit.py "Task" --agent "pi-session-abc"

    # Dry-run: preview batch before sending (R4)
    python3 batch-submit.py "Task" --dry-run

    # Read tasks from stdin (one per line)
    cat tasks.txt | python3 batch-submit.py --from-stdin

    # Specify provider and model
    python3 batch-submit.py --provider openrouter --model deepseek/deepseek-v4.1-flash "Task"
"""

import json
import sys
import uuid
import os
import argparse
from pathlib import Path
from datetime import datetime

# Ensure project root is on sys.path (works with python3 -I)
_HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(_HERE))

from providers import get_provider, list_providers


def load_config():
    """Load batch configuration from environment."""
    batch_dir = Path(os.environ.get('BATCH_DIR', _HERE / '.batch-data'))
    return {
        'requests_dir': os.environ.get('BATCH_REQUESTS_DIR', str(batch_dir / 'requests')),
        'state_file': os.environ.get('BATCH_STATE', str(batch_dir / '.batch-state')),
        'model': os.environ.get('BATCH_MODEL', 'claude-haiku-4-5-20251001'),
        'provider': os.environ.get('BATCH_PROVIDER', 'anthropic'),
    }


def submit_batch(messages, system_message=None, request_id=None,
                 provider_name=None, model=None, agent=None, dry_run=False):
    """Submit multiple messages as a single batch.

    Args:
        messages: list of (custom_id, user_message) tuples
        system_message: optional system prompt applied to all
        request_id: batch-level tracking ID (auto-generated)
        provider_name: provider to use
        model: model name
        agent: identifier for the submitting agent (R3)
        dry_run: if True, print the batch and exit without sending (R4)

    Returns:
        (batch_id, request_id, tracking_data)
    """
    config = load_config()
    batch_request_id = request_id or str(uuid.uuid4())

    provider_name = provider_name or config['provider']
    model = model or config['model']

    # Sensible default if the default Claude model is used with OpenRouter
    if provider_name == 'openrouter' and model == 'claude-haiku-4-5-20251001':
        model = 'deepseek/deepseek-v4.1-flash'

    if not system_message:
        system_message = (
            "You are an AI assistant helping with automated batch processing. "
            "Read the context provided and respond concisely."
        )

    provider = get_provider(provider_name)

    # ── Build all requests (R1: multi-request batch) ──
    batch_requests = []
    custom_ids = []
    for cid, msg in messages:
        req = provider.build_request(
            custom_id=cid,
            user_message=msg,
            system_message=system_message,
            model=model,
        )
        batch_requests.append(req)
        custom_ids.append(cid)

    # ── Dry-run: show the batch without sending (R4) ──
    if dry_run:
        print(json.dumps({
            "dry_run": True,
            "batch_request_id": batch_request_id,
            "provider": provider_name,
            "model": model,
            "request_count": len(batch_requests),
            "agent": agent,
            "requests": [{
                "custom_id": r.get("custom_id"),
                "preview": (r.get("body", r.get("params", {})).get("messages", [{}])[-1]
                           .get("content", "(no content)")[:80]),
            } for r in batch_requests],
            "system_message": system_message[:100],
        }, indent=2))
        return None, batch_request_id, None

    # ── Submit the batch ──
    batch_id = provider.create_batch(batch_requests)

    # ── Write tracking file ──
    request_file = Path(config['requests_dir']) / f"{batch_request_id}.jsonl"
    submission_time = datetime.now()

    tracking_data = {
        "batch_request_id": batch_request_id,
        "batch_id": batch_id,
        "provider": provider_name,
        "submitted_at": submission_time.isoformat(),
        "submitted_at_unix": submission_time.timestamp(),
        "request_count": len(batch_requests),
        "custom_ids": custom_ids,           # R2: all IDs tracked
        "agent": agent,                      # R3: agent ownership
        "status": "submitted",
        "model": model,
    }

    request_file.parent.mkdir(parents=True, exist_ok=True)
    with open(request_file, 'w', encoding='utf-8') as f:
        json.dump(tracking_data, f)

    # ── Update state file (R2: store list of custom_ids, R3: store agent) ──
    state_file = Path(config['state_file'])
    state = {}
    if state_file.exists():
        try:
            with open(state_file, encoding='utf-8') as f:
                state = json.load(f)
        except json.JSONDecodeError:
            state = {}

    state[batch_id] = {
        "batch_request_id": batch_request_id,
        "custom_ids": custom_ids,            # R2: all request IDs
        "custom_id": custom_ids[0] if len(custom_ids) == 1 else custom_ids,  # backward compat
        "provider": provider_name,
        "submitted_at": submission_time.isoformat(),
        "submitted_at_unix": submission_time.timestamp(),
        "status": "running",
        "model": model,
        "agent": agent,                      # R3: agent ownership
    }

    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

    print(f"✓ Batch submitted via {provider.get_endpoint_name()}: {batch_id}", file=sys.stderr)
    print(f"✓ Batch request ID: {batch_request_id}", file=sys.stderr)
    print(f"✓ Requests in batch: {len(batch_requests)}", file=sys.stderr)
    print(f"✓ Model: {model}", file=sys.stderr)
    if agent:
        print(f"✓ Agent: {agent}", file=sys.stderr)
    print(f"✓ Tracking: {request_file}", file=sys.stderr)

    return batch_id, batch_request_id, tracking_data


def main():
    parser = argparse.ArgumentParser(
        description="Submit one or more requests as a single batch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  batch-submit.py 'Write a summary'\n"
            "  batch-submit.py 'Task 1' 'Task 2' 'Task 3'    # multi-request (R1)\n"
            "  batch-submit.py --provider openrouter 'Task'\n"
            "  batch-submit.py --agent 'pi-session-1' 'Task'  # agent ownership (R3)\n"
            "  batch-submit.py --dry-run 'Task'               # preview (R4)\n"
            "  cat tasks.txt | batch-submit.py --from-stdin   # read from stdin\n"
            f"\nAvailable providers: {', '.join(list_providers())}"
        )
    )
    parser.add_argument(
        "messages",
        nargs="*",
        help="One or more task messages (each becomes one request in the batch)"
    )
    parser.add_argument(
        "--system", "-s",
        default=None,
        help="System message (applied to all requests in the batch)"
    )
    parser.add_argument(
        "--provider", "-p",
        default=None,
        choices=list_providers(),
        help="Batch provider (default: from BATCH_PROVIDER env)"
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="Model name (provider-specific)"
    )
    parser.add_argument(
        "--agent", "-a",
        default=None,
        help="Agent/source identifier for batch ownership (R3)"
    )
    parser.add_argument(
        "--request-id",
        default=None,
        help="Custom batch request ID (auto-generated if not provided)"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Preview the batch without submitting (R4)"
    )
    parser.add_argument(
        "--from-stdin",
        action="store_true",
        help="Read tasks from stdin (one per line)"
    )

    args = parser.parse_args()

    # Gather messages
    messages = list(args.messages)

    if args.from_stdin:
        stdin_lines = [line.rstrip("\n") for line in sys.stdin if line.strip()]
        messages.extend(stdin_lines)

    if not messages:
        parser.print_help()
        sys.exit(1)

    # Build (custom_id, message) tuples
    request_pairs = []
    for i, msg in enumerate(messages):
        cid = f"{args.request_id or 'batch'}-{i:04d}"
        request_pairs.append((cid, msg))

    batch_id, req_id, tracking = submit_batch(
        messages=request_pairs,
        system_message=args.system,
        request_id=args.request_id,
        provider_name=args.provider,
        model=args.model,
        agent=args.agent,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        print(json.dumps({
            "batch_id": batch_id,
            "request_id": req_id,
            "provider": args.provider or os.environ.get('BATCH_PROVIDER', 'anthropic'),
            "model": args.model or os.environ.get('BATCH_MODEL', 'default'),
            "request_count": len(request_pairs),
            "custom_ids": [cid for cid, _ in request_pairs],
            "agent": args.agent,
        }))


if __name__ == "__main__":
    main()