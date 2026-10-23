#!/usr/bin/env python3
"""Submit a request to the batch pipeline.

Supports multiple providers (Anthropic, OpenRouter, etc.)
via the providers/ abstraction layer.

Usage:
    python3 batch-submit.py "Your task description"
    python3 batch-submit.py "Task" "System message"
    python3 batch-submit.py --provider openrouter "Task"
"""

import json
import sys
import uuid
import os
import argparse
from pathlib import Path
from datetime import datetime

from providers import get_provider, list_providers


def load_config():
    """Load batch configuration from environment."""
    return {
        'requests_dir': os.environ.get('BATCH_REQUESTS_DIR'),
        'state_file': os.environ.get('BATCH_STATE'),
        'model': os.environ.get('BATCH_MODEL', 'claude-haiku-4-5-20251001'),
        'provider': os.environ.get('BATCH_PROVIDER', 'anthropic'),
    }


def submit_batch_request(user_message, system_message=None, request_id=None, 
                         provider_name=None, model=None):
    """Submit a request using the configured batch provider."""

    config = load_config()
    request_id = request_id or str(uuid.uuid4())

    provider_name = provider_name or config['provider']
    model = model or config['model']

    # Default system message if none provided
    if not system_message:
        system_message = (
            "You are an AI assistant helping with automated batch processing. "
            "Read the context provided and respond concisely."
        )

    # Get the provider
    provider = get_provider(provider_name)

    # Build provider-specific request
    batch_request = provider.build_request(
        custom_id=request_id,
        user_message=user_message,
        system_message=system_message,
        model=model,
    )

    # Submit batch
    batch_id = provider.create_batch([batch_request])

    # Write request tracking file with timing
    request_file = Path(config['requests_dir']) / f"{request_id}.jsonl"
    submission_time = datetime.now()
    
    tracking_data = {
        "custom_id": request_id,
        "batch_id": batch_id,
        "provider": provider_name,
        "submitted_at": submission_time.isoformat(),
        "submitted_at_unix": submission_time.timestamp(),
        "user_message": user_message[:200],  # brief preview
        "status": "submitted",
        "model": model,
    }
    
    with open(request_file, 'w', encoding='utf-8') as f:
        json.dump(tracking_data, f)

    # Update state file with batch ID mapping
    state_file = Path(config['state_file'])
    state = {}
    if state_file.exists():
        try:
            with open(state_file, encoding='utf-8') as f:
                state = json.load(f)
        except json.JSONDecodeError:
            state = {}

    state[batch_id] = {
        "custom_id": request_id,
        "provider": provider_name,
        "submitted_at": datetime.now().isoformat(),
        "submitted_at_unix": submission_time.timestamp(),
        "status": "running",
        "model": model,
    }

    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

    print(f"✓ Batch submitted via {provider.get_endpoint_name()}: {batch_id}", file=sys.stderr)
    print(f"✓ Request ID: {request_id}", file=sys.stderr)
    print(f"✓ Model: {model}", file=sys.stderr)
    print(f"✓ Tracking: {request_file}", file=sys.stderr)

    return batch_id, request_id


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

    if not args.message:
        parser.print_help()
        sys.exit(1)

    batch_id, req_id = submit_batch_request(
        args.message,
        args.system_message,
        request_id=args.request_id,
        provider_name=args.provider,
        model=args.model,
    )
    print(json.dumps({
        "batch_id": batch_id,
        "request_id": req_id,
        "provider": args.provider or os.environ.get('BATCH_PROVIDER', 'anthropic'),
        "model": args.model or os.environ.get('BATCH_MODEL', 'claude-haiku-4-5-20251001'),
    }))


if __name__ == "__main__":
    main()