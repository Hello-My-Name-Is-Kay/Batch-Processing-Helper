#!/usr/bin/env python3
"""Submit one or more requests to the batch pipeline as a single batch.

Supports multiple providers (Anthropic, OpenRouter, etc.)
via the providers/ abstraction layer.

Usage:
    # Single request
    python3 batch-submit.py "Your task description"

    # Several requests in ONE batch (R1)
    python3 batch-submit.py "Task 1" "Task 2" "Task 3"

    # Prompts from a file (one per line, or JSON Lines) or from stdin
    python3 batch-submit.py --file prompts.txt
    cat tasks.txt | python3 batch-submit.py --from-stdin

    # System message (applied to every request that brings none of its own)
    python3 batch-submit.py "Task 1" "Task 2" --system "Be concise"

    # Tag the batch with the agent or session that owns it (R3)
    python3 batch-submit.py "Task" --agent "pi-session-abc"

    # Preview the batch without sending anything (R4)
    python3 batch-submit.py "Task" --dry-run

    # Provider and model
    python3 batch-submit.py --provider openrouter --model deepseek/deepseek-v4.1-flash "Task"
"""

import json
import sys
import uuid
import os
import argparse
from pathlib import Path
from datetime import datetime

from batch_common import (
    load_provider_credentials, resolve_paths, update_state, validate_custom_id, write_json_atomic,
)
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


def read_stdin_prompts(stream=None):
    """Prompts from standard input: one per line, blank lines ignored."""
    return [{"message": line.strip()} for line in (stream or sys.stdin) if line.strip()]


def submit_batch(items, system_message=None, request_id=None, provider_name=None,
                 model=None, source=None, agent=None, dry_run=False,
                 max_tokens=None):
    """Submit one batch holding one request per item, and track it.

    items: list of {"message", "system"?, "id"?} dicts. With a single item the
    request id is the batch's own id; with several, each request is
    "<batch id>-0000", "-0001", ... unless the item brings its own id (R2).
    agent: who owns the batch (R3); it is kept in the state file, the tracking
    file and the history.
    max_tokens: cap on each reply's tokens (None: the provider's default, 2048).
    dry_run: build the requests and return a preview without contacting the
    provider or writing anything (R4).

    Everything that can fail locally (ids, credentials, writable folders) is
    checked before the batch is created, so a failed setup never leaves a billed
    batch behind with no tracking record.

    Returns a dict with batch_id, request_id (the batch's tracking id),
    provider, model, request_count, custom_ids and agent (a dry run returns
    dry_run=True, batch_id=None and a "requests" preview as well).
    """

    load_provider_credentials()
    config = load_config()
    group_id = validate_custom_id(request_id or str(uuid.uuid4()))
    provider_name = provider_name or config['provider']

    if not items:
        raise ValueError("Nothing to submit: no requests given.")

    # One id per request: the item's own, else the batch id (single) or batch id + counter
    custom_ids = []
    for number, item in enumerate(items):
        default_id = group_id if len(items) == 1 else f"{group_id}-{number:04d}"
        custom_ids.append(validate_custom_id(item.get("id") or default_id))
    if len(set(custom_ids)) != len(custom_ids):
        raise ValueError("Request ids must be unique within a batch.")

    # Raises if the provider is unknown or its API key is missing
    provider = get_provider(provider_name)
    model = model or provider.default_model()
    system_message = system_message or DEFAULT_SYSTEM_MESSAGE

    # Build provider-specific requests
    batch_requests = [
        provider.build_request(
            custom_id=custom_id,
            user_message=item["message"],
            system_message=item.get("system") or system_message,
            model=model,
            **({"max_tokens": max_tokens} if max_tokens else {}),
        )
        for custom_id, item in zip(custom_ids, items)
    ]

    result = {
        "batch_id": None,
        "request_id": group_id,
        "provider": provider_name,
        "model": model,
        "request_count": len(items),
        "custom_ids": custom_ids,
        "agent": agent,
    }
    if max_tokens:
        result["max_tokens"] = max_tokens

    if dry_run:
        result["dry_run"] = True
        result["system_message"] = system_message[:100]
        result["requests"] = [
            {"custom_id": custom_id, "preview": item["message"][:80]}
            for custom_id, item in zip(custom_ids, items)
        ]
        return result

    requests_dir = Path(config['requests_dir'])
    state_file = Path(config['state_file'])
    for folder in (requests_dir, state_file.parent):
        folder.mkdir(parents=True, exist_ok=True)
        if not os.access(folder, os.W_OK):
            raise PermissionError(
                f"Cannot write to {folder}; not submitting a batch that could not be tracked."
            )

    # Submit batch
    batch_id = provider.create_batch(batch_requests)
    result["batch_id"] = batch_id

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
            "custom_ids": custom_ids,
            "status": "submitted",
            "model": model,
        }
        if agent:
            tracking_data["agent"] = agent
        if source:
            tracking_data["source_file"] = str(source)
        write_json_atomic(request_file, tracking_data)

        # Update state file with batch ID mapping
        def add_batch(state):
            entry = {
                "custom_id": group_id,
                "custom_ids": custom_ids,
                "provider": provider_name,
                "submitted_at": submission_time.isoformat(),
                "submitted_at_unix": submission_time.timestamp(),
                "status": "running",
                "model": model,
                "request_counts": {"total": len(items), "completed": 0},
            }
            if agent:
                entry["agent"] = agent
            state[batch_id] = entry
        update_state(state_file, add_batch)
    except OSError as e:
        raise RuntimeError(
            f"Batch {batch_id} was created at {provider_name} (request {group_id}) "
            f"but could not be recorded locally: {e}"
        ) from e

    print(f"✓ Batch submitted via {provider.get_endpoint_name()}: {batch_id}", file=sys.stderr)
    print(f"✓ Batch request ID: {group_id}", file=sys.stderr)
    print(f"✓ Requests in batch: {len(items)}", file=sys.stderr)
    print(f"✓ Model: {model}", file=sys.stderr)
    if agent:
        print(f"✓ Agent: {agent}", file=sys.stderr)
    print(f"✓ Tracking: {request_file}", file=sys.stderr)

    return result


def submit_request(user_message, system_message=None, request_id=None,
                   provider_name=None, model=None, agent=None):
    """Submit a single request as its own batch (see submit_batch)."""
    return submit_batch(
        [{"message": user_message}], system_message=system_message,
        request_id=request_id, provider_name=provider_name, model=model, agent=agent,
    )


def submit_batch_request(*args, **kwargs):
    """Like submit_request(), returning just (batch_id, request_id)."""
    result = submit_request(*args, **kwargs)
    return result["batch_id"], result["request_id"]


def main():
    parser = argparse.ArgumentParser(
        description="Submit one or more requests as a single batch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  batch-submit.py 'Write a summary'\n"
            "  batch-submit.py 'Task 1' 'Task 2' 'Task 3'     # several requests, one batch\n"
            "  batch-submit.py --file prompts.txt --system 'Answer in one line'\n"
            "  cat tasks.txt | batch-submit.py --from-stdin   # one task per line\n"
            "  batch-submit.py --provider openrouter --model 'openai/gpt-4o' 'Task'\n"
            "  batch-submit.py --agent 'pi-session-1' 'Task'  # who owns the batch\n"
            "  batch-submit.py --dry-run 'Task'               # preview, send nothing\n"
            f"\nAvailable providers: {', '.join(list_providers())}"
        )
    )
    parser.add_argument(
        "messages",
        nargs="*",
        help="One or more task messages (each becomes one request in the batch)"
    )
    parser.add_argument(
        "--file", "-f",
        default=None,
        help="Also submit every prompt in this file (one prompt per line; "
             ".jsonl files may use {\"message\", \"system\", \"id\"} objects)"
    )
    parser.add_argument(
        "--from-stdin",
        action="store_true",
        help="Also read tasks from stdin (one per line)"
    )
    parser.add_argument(
        "--system", "-s",
        default=None,
        help="System message (applied to every request that has none of its own)"
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
        "--agent", "-a",
        default=None,
        help="Agent or session that owns the batch (kept in state, tracking file and history)"
    )
    parser.add_argument(
        "--request-id",
        default=None,
        help="Custom batch request ID (auto-generated UUID if not provided)"
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Cap on each reply's tokens (default: the provider's, 2048). Reasoning "
             "models count their thinking against it, so raise it for long answers"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Preview the batch without submitting it"
    )

    args = parser.parse_args()

    try:
        items = [{"message": message} for message in args.messages]
        if args.file:
            items.extend(read_prompts(args.file))
        if args.from_stdin:
            items.extend(read_stdin_prompts())
        if not items:
            parser.print_help()
            sys.exit(1)

        result = submit_batch(
            items,
            system_message=args.system,
            request_id=args.request_id,
            provider_name=args.provider,
            model=args.model,
            source=args.file,
            agent=args.agent,
            dry_run=args.dry_run,
            max_tokens=args.max_tokens,
        )
    except (ValueError, OSError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, indent=2 if args.dry_run else None))


if __name__ == "__main__":
    main()
