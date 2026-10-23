#!/usr/bin/env python3
"""Submit a request to the batch pipeline.

Supports multiple providers (Anthropic, OpenRouter, etc.)
via the providers/ abstraction layer.

Usage:
    python3 batch-submit.py "Your task description"
    python3 batch-submit.py "Task" "System message"
    python3 batch-submit.py --provider openrouter "Task"
    python3 batch-submit.py --file prompts.txt          # many prompts, one batch
"""

import json
import sys
import uuid
import os
import argparse
from pathlib import Path
from datetime import datetime

from batch_common import resolve_paths, update_state, validate_custom_id, write_json_atomic
from providers import get_provider, list_providers

DEFAULT_SYSTEM_MESSAGE = (
    "You are an AI assistant helping with automated batch processing. "
    "Read the context provided and respond concisely."
)


def load_config():
    """Load batch configuration from environment (project defaults for anything unset)."""
    paths = resolve_paths()
    return {
        'requests_dir': paths['requests_dir'],
        'state_file': paths['state_file'],
        'provider': os.environ.get('BATCH_PROVIDER') or 'anthropic',
    }


def read_prompts(path):
    """Read prompts for a multi-request batch from a file.

    A .jsonl file has one JSON value per line: either a string (the prompt) or
    an object with "message" and, optionally, "system" and "id". Any other file
    is plain text with one prompt per line. Blank lines are ignored.

    Returns a list of {"message", "system"?, "id"?} dicts.
    """
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    as_json = Path(path).suffix.lower() == '.jsonl'

    prompts = []
    for number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        if not as_json:
            prompts.append({"message": line})
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}, line {number}: not valid JSON ({e.msg})") from e
        if isinstance(value, str):
            value = {"message": value}
        if not isinstance(value, dict) or not isinstance(value.get("message"), str) or not value["message"].strip():
            raise ValueError(f'{path}, line {number}: expected a string or an object with a "message"')
        prompts.append(value)

    if not prompts:
        raise ValueError(f"{path} contains no prompts")
    return prompts


def submit_batch(items, system_message=None, request_id=None,
                 provider_name=None, model=None, source=None):
    """Submit one batch holding one request per item, and track it.

    items: list of {"message", "system"?, "id"?} dicts. With a single item the
    request id is the batch's own id, as before; with several, each request is
    "<batch id>-0001", "-0002", ... unless the item brings its own id.

    Everything that can fail locally (ids, credentials, writable folders) is
    checked before the batch is created, so a failed setup never leaves a billed
    batch behind with no tracking record.

    Returns a dict with batch_id, request_id (the batch's tracking id),
    provider, the model used and the number of requests.
    """

    config = load_config()
    group_id = validate_custom_id(request_id or str(uuid.uuid4()))
    provider_name = provider_name or config['provider']

    if not items:
        raise ValueError("Nothing to submit: no requests given.")

    # One id per request: the item's own, else the batch id (single) or batch id + counter
    custom_ids = []
    for number, item in enumerate(items, start=1):
        default_id = group_id if len(items) == 1 else f"{group_id}-{number:04d}"
        custom_ids.append(validate_custom_id(item.get("id") or default_id))
    if len(set(custom_ids)) != len(custom_ids):
        raise ValueError("Request ids must be unique within a batch.")

    requests_dir = Path(config['requests_dir'])
    state_file = Path(config['state_file'])
    for folder in (requests_dir, state_file.parent):
        folder.mkdir(parents=True, exist_ok=True)
        if not os.access(folder, os.W_OK):
            raise PermissionError(
                f"Cannot write to {folder}; not submitting a batch that could not be tracked."
            )

    # Raises if the provider is unknown or its API key is missing
    provider = get_provider(provider_name)
    model = model or provider.default_model()

    # Build provider-specific requests
    batch_requests = [
        provider.build_request(
            custom_id=custom_id,
            user_message=item["message"],
            system_message=item.get("system") or system_message or DEFAULT_SYSTEM_MESSAGE,
            model=model,
        )
        for custom_id, item in zip(custom_ids, items)
    ]

    # Submit batch
    batch_id = provider.create_batch(batch_requests)

    # From here on the batch exists at the provider: if local bookkeeping
    # fails, say which batch it was so it can be recovered by hand.
    try:
        request_file = requests_dir / f"{group_id}.jsonl"
        submission_time = datetime.now()

        tracking_data = {
            "custom_id": group_id,
            "batch_id": batch_id,
            "provider": provider_name,
            "submitted_at": submission_time.isoformat(),
            "submitted_at_unix": submission_time.timestamp(),
            "user_message": items[0]["message"][:200],  # brief preview
            "request_count": len(items),
            "status": "submitted",
            "model": model,
        }
        if source:
            tracking_data["source_file"] = str(source)
        write_json_atomic(request_file, tracking_data)

        # Update state file with batch ID mapping
        def add_batch(state):
            state[batch_id] = {
                "custom_id": group_id,
                "provider": provider_name,
                "submitted_at": submission_time.isoformat(),
                "submitted_at_unix": submission_time.timestamp(),
                "status": "running",
                "model": model,
                "request_counts": {"total": len(items), "completed": 0},
            }
        update_state(state_file, add_batch)
    except OSError as e:
        raise RuntimeError(
            f"Batch {batch_id} was created at {provider_name} (request {group_id}) "
            f"but could not be recorded locally: {e}"
        ) from e

    print(f"✓ Batch submitted via {provider.get_endpoint_name()}: {batch_id}", file=sys.stderr)
    print(f"✓ Request ID: {group_id}", file=sys.stderr)
    if len(items) > 1:
        print(f"✓ Requests in batch: {len(items)}", file=sys.stderr)
    print(f"✓ Model: {model}", file=sys.stderr)
    print(f"✓ Tracking: {request_file}", file=sys.stderr)

    return {
        "batch_id": batch_id,
        "request_id": group_id,
        "provider": provider_name,
        "model": model,
        "count": len(items),
    }


def submit_request(user_message, system_message=None, request_id=None,
                   provider_name=None, model=None):
    """Submit a single request as its own batch (see submit_batch)."""
    return submit_batch(
        [{"message": user_message}], system_message=system_message,
        request_id=request_id, provider_name=provider_name, model=model,
    )


def submit_batch_request(*args, **kwargs):
    """Like submit_request(), returning just (batch_id, request_id)."""
    result = submit_request(*args, **kwargs)
    return result["batch_id"], result["request_id"]


def main():
    parser = argparse.ArgumentParser(
        description="Submit a batch request to the batch pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  batch-submit.py 'Write a summary'\n"
            "  batch-submit.py 'Task' 'System message'\n"
            "  batch-submit.py --provider openrouter 'Task'\n"
            "  batch-submit.py --provider openrouter --model 'openai/gpt-4o' 'Task'\n"
            "  batch-submit.py --file prompts.txt --system 'Answer in one line'\n"
            f"\nAvailable providers: {', '.join(list_providers())}"
        )
    )
    parser.add_argument(
        "message",
        nargs="?",
        help="User message / task description"
    )
    parser.add_argument(
        "system_message",
        nargs="?",
        default=None,
        help="Optional system message"
    )
    parser.add_argument(
        "--file", "-f",
        default=None,
        help="Submit every prompt in this file as one batch (one prompt per line; "
             ".jsonl files may use {\"message\", \"system\", \"id\"} objects)"
    )
    parser.add_argument(
        "--system", "-s",
        default=None,
        help="System message (for --file, the default for prompts that bring none)"
    )
    parser.add_argument(
        "--provider", "-p",
        default=None,
        choices=list_providers(),
        help="Batch provider to use (default: from BATCH_PROVIDER env or 'anthropic')"
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="Model name (provider-specific, overrides BATCH_MODEL)"
    )
    parser.add_argument(
        "--request-id",
        default=None,
        help="Custom request ID (auto-generated UUID if not provided)"
    )

    args = parser.parse_args()

    try:
        if args.file:
            if args.message or args.system_message:
                parser.error("--file cannot be combined with a message; use --system for a shared system message")
            items = read_prompts(args.file)
            system_message = args.system
            source = args.file
        else:
            if not args.message:
                parser.print_help()
                sys.exit(1)
            items = [{"message": args.message}]
            system_message = args.system or args.system_message
            source = None

        result = submit_batch(
            items,
            system_message=system_message,
            request_id=args.request_id,
            provider_name=args.provider,
            model=args.model,
            source=source,
        )
    except (ValueError, OSError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
