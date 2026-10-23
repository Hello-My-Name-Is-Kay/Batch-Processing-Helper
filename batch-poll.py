#!/usr/bin/env python3
"""Poll for completed batch jobs and write results."""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
import anthropic

def load_config():
    """Load batch configuration."""
    return {
        'state_file': os.environ.get('BATCH_STATE'),
        'responses_dir': os.environ.get('BATCH_RESPONSES_DIR'),
        'logs_dir': os.environ.get('BATCH_LOGS_DIR'),
    }

def poll_batches():
    """Check all pending batches for completion."""

    config = load_config()
    state_file = Path(config['state_file'])
    responses_dir = Path(config['responses_dir'])
    logs_dir = Path(config['logs_dir'])

    if not state_file.exists():
        return 0

    with open(state_file) as f:
        state = json.load(f)

    client = anthropic.Anthropic()
    completed_count = 0

    # Check each batch
    for batch_id, batch_info in list(state.items()):
        if batch_info.get('status') == 'completed':
            continue

        try:
            batch = client.beta.messages.batches.retrieve(batch_id)

            if batch.processing_status == "succeeded":
                # Batch is done; fetch results
                results = client.beta.messages.batches.results(batch_id)

                request_id = batch_info['custom_id']
                response_file = responses_dir / f"{request_id}.result"

                # Write results
                result_data = []
                for result in results:
                    result_data.append({
                        "custom_id": result.custom_id,
                        "result": {
                            "type": result.result.type,
                            "message": {
                                "content": result.result.message.content[0].text
                                           if result.result.message.content else ""
                            }
                        }
                    })

                with open(response_file, 'w') as f:
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
                log_msg = f"[{datetime.now().isoformat()}] {batch_id} completed in {latency_str} → {response_file}"
                print(log_msg, file=sys.stderr)

                with open(logs_dir / "poll.log", 'a', encoding='utf-8') as f:
                    f.write(log_msg + "\n")

            elif batch.processing_status == "failed":
                state[batch_id]['status'] = 'failed'
                state[batch_id]['error'] = batch.request_counts

        except Exception as e:
            print(f"Error checking batch {batch_id}: {e}", file=sys.stderr)

    # Write updated state
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)

    return completed_count

if __name__ == "__main__":
    count = poll_batches()
    print(json.dumps({"completed": count}))
