#!/usr/bin/env python3
"""Poll for completed batch jobs and write results.

Supports multiple providers via the providers/ abstraction layer.
Logs completions to persistent history for metrics and analytics.
"""

import copy
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime

from batch_common import (
    load_state, resolve_paths, state_lock, update_state, write_json_atomic,
)
from batch_history import log_completion, make_history_entry
from providers import get_provider, list_providers, BatchStatus


def _sum_usage(results):
    """Total token usage across results.

    Providers name the counters differently (input/output vs prompt/completion),
    and Anthropic does not put usage on the batch object at all.
    """
    prompt = completion = 0
    found = False
    for result in results:
        usage = result.usage or {}
        p = usage.get('prompt_tokens', usage.get('input_tokens'))
        c = usage.get('completion_tokens', usage.get('output_tokens'))
        if p is not None or c is not None:
            found = True
            prompt += p or 0
            completion += c or 0
    if not found:
        return {}
    return {
        'prompt_tokens': prompt,
        'completion_tokens': completion,
        'total_tokens': prompt + completion,
    }


# Batches in these states are finished: they are not asked about again.
TERMINAL_STATES = ('completed', 'failed', 'cancelled')


def _log(logs_dir, message):
    """Print a poll event and append it to poll.log."""
    line = f"[{datetime.now().isoformat()}] {message}"
    print(line, file=sys.stderr)
    with open(logs_dir / "poll.log", 'a', encoding='utf-8') as f:
        f.write(line + "\n")


def poll_batches(only_provider=None):
    """Check pending batches for completion.

    Looks at every provider's batches, or only `only_provider`'s if given. Batches
    that already finished (completed, failed or cancelled) are skipped.

    The state file is read once and the batches' answers are collected, then
    merged back under the state lock, so a batch submitted while this poll was
    talking to the providers is not lost.
    """

    config = resolve_paths()
    state_file = Path(config['state_file'])
    responses_dir = Path(config['responses_dir'])
    logs_dir = Path(config['logs_dir'])
    responses_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    if not state_file.exists():
        return 0

    with state_lock(state_file):
        state = load_state(state_file, repair=True)
    original = copy.deepcopy(state)

    completed_count = 0

    # Group batches by provider for efficient polling
    batches_by_provider = {}
    for batch_id, batch_info in list(state.items()):
        if batch_info.get('status') in TERMINAL_STATES:
            continue
        provider_name = batch_info.get('provider', 'anthropic')
        if only_provider and provider_name != only_provider:
            continue
        if provider_name not in batches_by_provider:
            batches_by_provider[provider_name] = {}
        batches_by_provider[provider_name][batch_id] = batch_info

    # Check each provider's batches
    for provider_name, provider_batches in batches_by_provider.items():
        try:
            provider = get_provider(provider_name)
        except ValueError as e:
            print(f"Error getting provider '{provider_name}': {e}", file=sys.stderr)
            continue

        for batch_id, batch_info in provider_batches.items():
            try:
                batch_status = provider.retrieve_batch(batch_id)
                
                if batch_status['status'] == BatchStatus.COMPLETED:
                    # Batch is done; fetch results
                    results = provider.get_results(batch_id)

                    request_id = batch_info['custom_id']
                    response_file = responses_dir / f"{request_id}.result"

                    # Write results in a provider-agnostic format
                    result_data = []
                    for result in results:
                        result_data.append({
                            "custom_id": result.custom_id,
                            "provider": provider_name,
                            "status": result.status,
                            "result": {
                                "content": result.content,
                                "finish_reason": result.finish_reason,
                                "usage": result.usage,
                            },
                            "error": result.error,
                        })

                    write_json_atomic(response_file, result_data, indent=2)

                    # Update state with timing
                    completion_time = datetime.now()
                    state[batch_id]['status'] = 'completed'
                    state[batch_id]['completed_at'] = completion_time.isoformat()
                    state[batch_id]['completed_at_unix'] = completion_time.timestamp()

                    # Calculate latency
                    if 'submitted_at_unix' in state[batch_id]:
                        latency_seconds = completion_time.timestamp() - state[batch_id]['submitted_at_unix']
                        state[batch_id]['latency_seconds'] = latency_seconds
                        state[batch_id]['latency_minutes'] = round(latency_seconds / 60, 2)

                    completed_count += 1

                    counts = batch_status.get('request_counts')
                    if isinstance(counts, dict) and counts:
                        state[batch_id]['request_counts'] = counts

                    # Log with latency
                    latency_str = f"{state[batch_id].get('latency_minutes', '?')} min"
                    _log(logs_dir, f"[{provider_name}] {batch_id} completed in {latency_str} → {response_file}")

                    # ── Persist to history ──
                    try:
                        # Try to get richer data from batch_status;
                        # fall back to the submitted model and the
                        # results' own token counts.
                        usage = batch_status.get('usage') or _sum_usage(results)
                        entry = make_history_entry(
                            batch_id=batch_id,
                            provider=provider_name,
                            model=batch_info.get('model', ''),
                            raw_model=(batch_status.get('raw_model')
                                       or batch_status.get('model')
                                       or batch_info.get('model', '')),
                            status='completed',
                            created_at=batch_status.get('created_at') or 0,
                            finalized_at=batch_status.get('ended_at') or completion_time.timestamp(),
                            total_requests=batch_status.get('request_counts', {}).get('total', len(results)),
                            completed_requests=batch_status.get('request_counts', {}).get('completed', len(results)),
                            failed_requests=batch_status.get('request_counts', {}).get('failed', 0),
                            prompt_tokens=usage.get('prompt_tokens'),
                            completion_tokens=usage.get('completion_tokens'),
                            total_tokens=usage.get('total_tokens'),
                            cost=usage.get('cost'),
                            submitted_at_unix=batch_info.get('submitted_at_unix'),
                            provider_backend=batch_status.get('provider_backend', batch_status.get('provider', '')),
                        )
                        log_completion(entry)
                    except Exception as hist_err:
                        print(f"  (history logging skipped: {hist_err})", file=sys.stderr)

                elif batch_status['status'] == BatchStatus.FAILED:
                    state[batch_id]['status'] = 'failed'
                    state[batch_id]['error'] = str(batch_status.get('errors', batch_status.get('request_counts', {})))
                    _log(logs_dir, f"[{provider_name}] {batch_id} FAILED: {state[batch_id]['error']}")

                elif batch_status['status'] == BatchStatus.CANCELLED:
                    state[batch_id]['status'] = 'cancelled'
                    _log(logs_dir, f"[{provider_name}] {batch_id} was cancelled")

            except Exception as e:
                print(f"Error checking {provider_name} batch {batch_id}: {e}", file=sys.stderr)

    # Merge what changed into the current state file (under the lock)
    changes = {
        batch_id: {k: v for k, v in info.items() if original[batch_id].get(k) != v}
        for batch_id, info in state.items() if batch_id in original
    }
    changes = {batch_id: fields for batch_id, fields in changes.items() if fields}

    if changes:
        def apply_changes(current):
            for batch_id, fields in changes.items():
                if batch_id in current:
                    current[batch_id].update(fields)

        update_state(state_file, apply_changes)

    return completed_count


def main():
    parser = argparse.ArgumentParser(
        description="Poll for completed batch jobs across all providers."
    )
    parser.add_argument(
        "--provider", "-p",
        default=None,
        choices=list_providers(),
        help="Only poll batches from this provider (default: all providers)"
    )
    
    args = parser.parse_args()
    count = poll_batches(only_provider=args.provider)
    print(json.dumps({"completed": count}))


if __name__ == "__main__":
    main()