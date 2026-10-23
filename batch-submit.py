#!/usr/bin/env python3
"""Submit a request to the batch pipeline."""

import json
import sys
import uuid
import os
from pathlib import Path
from datetime import datetime
import anthropic

def load_config():
    """Load batch configuration from environment."""
    return {
        'requests_dir': os.environ.get('BATCH_REQUESTS_DIR'),
        'state_file': os.environ.get('BATCH_STATE'),
        'model': os.environ.get('BATCH_MODEL', 'claude-haiku-4-5-20251001'),
    }

def submit_batch_request(user_message, system_message=None, request_id=None):
    """Submit a request to the Anthropic Batch API and write tracking file."""

    config = load_config()
    request_id = request_id or str(uuid.uuid4())

    if not system_message:
        system_message = """You are an AI assistant helping with Freedom-OS development.
Read the context provided and respond concisely.
Follow the project rules: no commits without explicit approval, leak-safe code, measure before building."""

    # Create batch request in Anthropic format
    batch_request = {
        "custom_id": request_id,
        "params": {
            "model": config['model'],
            "max_tokens": 2048,
            "system": system_message,
            "messages": [
                {"role": "user", "content": user_message}
            ]
        }
    }

    # Initialize Anthropic client
    client = anthropic.Anthropic()

    # Submit batch (single request wrapped in a batch)
    requests_file = [batch_request]

    response = client.beta.messages.batches.create(
        requests=requests_file,
    )

    batch_id = response.id

    # Write request tracking file with timing
    request_file = Path(config['requests_dir']) / f"{request_id}.jsonl"
    submission_time = datetime.now()
    with open(request_file, 'w', encoding='utf-8') as f:
        json.dump({
            "custom_id": request_id,
            "batch_id": batch_id,
            "submitted_at": submission_time.isoformat(),
            "submitted_at_unix": submission_time.timestamp(),
            "user_message": user_message[:200],  # brief preview
            "status": "submitted",
            "model": config['model']
        }, f)

    # Update state file with batch ID mapping
    state_file = Path(config['state_file'])
    state = {}
    if state_file.exists():
        with open(state_file) as f:
            state = json.load(f)

    state[batch_id] = {
        "custom_id": request_id,
        "submitted_at": datetime.now().isoformat(),
        "submitted_at_unix": submission_time.timestamp(),
        "status": "running"
    }

    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)

    print(f"✓ Batch submitted: {batch_id}", file=sys.stderr)
    print(f"✓ Request ID: {request_id}", file=sys.stderr)
    print(f"✓ Tracking: {request_file}", file=sys.stderr)

    return batch_id, request_id

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: batch-submit.py '<message>' [system_message]", file=sys.stderr)
        sys.exit(1)

    user_msg = sys.argv[1]
    system_msg = sys.argv[2] if len(sys.argv) > 2 else None

    batch_id, req_id = submit_batch_request(user_msg, system_msg)
    print(json.dumps({"batch_id": batch_id, "request_id": req_id}))
