#!/usr/bin/env python3
"""Poll for completed batch jobs and write results.

Supports multiple providers via the providers/ abstraction layer.
Logs completions to persistent history for metrics and analytics.
"""

import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

from providers import get_provider, list_providers, BatchStatus

# History tracking (best-effort, don't fail if unavailable)
_HISTORY_AVAILABLE = False
def _make_history_entry(**kw): return {}
def _log_completion(entry): pass

# Try to import the real history module
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from batch_history import make_history_entry as _make_history_entry
    from batch_history import log_completion as _log_completion
    _HISTORY_AVAILABLE = True
except ImportError:
    pass

make_history_entry = _make_history_entry
log_completion = _log_completion


def load_config():
    """Load batch configuration."""
    return {
        'state_file': os.environ.get('BATCH_STATE'),
        'responses_dir': os.environ.get('BATCH_RESPONSES_DIR'),
        'logs_dir': os.environ.get('BATCH_LOGS_DIR'),
    }


def poll_batches():
    """Check all pending batches for completion across all providers."""

    config = load_config()
    state_file = Path(config['state_file'])
    responses_dir = Path(config['responses_dir'])
    logs_dir = Path(config['logs_dir'])

    if not state_file.exists():
        return 0

    with open(state_file, encoding='utf-8') as f:
        state = json.load(f)

    completed_count = 0

    # Group batches by provider for efficient polling
    batches_by_provider = {}
    for batch_id, batch_info in list(state.items()):
        if batch_info.get('status') == 'completed':
            continue
        provider_name = batch_info.get('provider', 'anthropic')
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

                    with open(response_file, 'w', encoding='utf-8') as f:
                        json.dump(result_data, f, indent=2)

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

                    # Log with latency
                    latency_str = f"{state[batch_id].get('latency_minutes', '?')} min"
                    log_msg = (
                        f"[{datetime.now().isoformat()}] "
                        f"[{provider_name}] {batch_id} completed in {latency_str} → {response_file}"
                    )
                    print(log_msg, file=sys.stderr)

                    with open(logs_dir / "poll.log", 'a', encoding='utf-8') as f:
                        f.write(log_msg + "\n")

                    # ── Persist to history ──
                    if _HISTORY_AVAILABLE:
                        try:
                            from providers.base import BatchProvider
                            # Try to get richer data from batch_status
                            entry = make_history_entry(
                                batch_id=batch_id,
                                provider=provider_name,
                                model=batch_info.get('model', ''),
                                raw_model=batch_status.get('raw_model', batch_status.get('model', '')),
                                status='completed',
                                created_at=batch_status.get('created_at', 0),
                                finalized_at=batch_status.get('ended_at', completion_time.timestamp()),
                                total_requests=batch_status.get('request_counts', {}).get('total', len(results)),
                                completed_requests=batch_status.get('request_counts', {}).get('completed', len(results)),
                                failed_requests=batch_status.get('request_counts', {}).get('failed', 0),
                                prompt_tokens=batch_status.get('usage', {}).get('prompt_tokens'),
                                completion_tokens=batch_status.get('usage', {}).get('completion_tokens'),
                                total_tokens=batch_status.get('usage', {}).get('total_tokens'),
                                cost=batch_status.get('usage', {}).get('cost'),
                                submitted_at_unix=batch_info.get('submitted_at_unix'),
                                provider_backend=batch_status.get('provider_backend', batch_status.get('provider', '')),
                                agent=batch_info.get('agent'),
                                custom_ids=batch_info.get('custom_ids'),
                            )
                            log_completion(entry)
                        except Exception as hist_err:
                            print(f"  (history logging skipped: {hist_err})", file=sys.stderr)

                elif batch_status['status'] == BatchStatus.FAILED:
                    state[batch_id]['status'] = 'failed'
                    state[batch_id]['error'] = str(batch_status.get('errors', batch_status.get('request_counts', {})))

                    log_msg = (
                        f"[{datetime.now().isoformat()}] "
                        f"[{provider_name}] {batch_id} FAILED: {state[batch_id]['error']}"
                    )
                    print(log_msg, file=sys.stderr)

                    with open(logs_dir / "poll.log", 'a', encoding='utf-8') as f:
                        f.write(log_msg + "\n")

            except Exception as e:
                print(f"Error checking {provider_name} batch {batch_id}: {e}", file=sys.stderr)

    # Write updated state
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

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
    count = poll_batches()
    print(json.dumps({"completed": count}))


if __name__ == "__main__":
    main()