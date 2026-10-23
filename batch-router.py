#!/usr/bin/env python3
"""Route batch results: classify and decide next action."""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
import anthropic

def load_config():
    """Load batch configuration."""
    return {
        'responses_dir': os.environ.get('BATCH_RESPONSES_DIR'),
        'escalations_dir': os.environ.get('BATCH_ESCALATIONS_DIR'),
        'completed_dir': os.environ.get('BATCH_COMPLETED_DIR'),
        'logs_dir': os.environ.get('BATCH_LOGS_DIR'),
        'freedom_os_dir': os.environ.get('FREEDOM_OS_DIR'),
        'router_model': os.environ.get('ROUTER_MODEL', 'claude-haiku-4-5-20251001'),
    }

def load_project_context(freedom_os_dir):
    """Load Freedom-OS project context for routing decisions."""
    handoff_file = Path(freedom_os_dir) / "docs/handoff.md"
    context = ""
    if handoff_file.exists():
        with open(handoff_file) as f:
            content = f.read()
            # Extract first 2000 chars as summary
            context = content[:2000]
    return context

def route_result(result_file):
    """Classify a batch result and decide routing."""

    config = load_config()
    routing_start_time = datetime.now()

    with open(result_file, encoding='utf-8') as f:
        result = json.load(f)

    if not result or not isinstance(result, list) or len(result) == 0:
        return None

    # Get first result (single-request batch)
    result_data = result[0]
    request_id = result_data['custom_id']
    response_text = result_data['result']['message']['content']

    # Use Haiku to classify the response
    project_context = load_project_context(config['freedom_os_dir'])

    classification_prompt = f"""Classify this batch result and route it:

Project context (Freedom-OS):
{project_context}

Response to classify:
{response_text}

Respond ONLY with JSON (no markdown, no backticks):
{{
  "classification": "text|question|error|action_needed|ready_to_commit",
  "confidence": 0.0-1.0,
  "summary": "one line",
  "route": "archive|escalate|batch_again|live_model",
  "reason": "brief reason"
}}

- text: plain output, archive it
- question: needs clarification, escalate to user
- error: batch failed, escalate
- action_needed: requires human decision (commit, permission, sensitive data), escalate
- ready_to_commit: work is complete and can be committed, escalate for approval

Routes:
- archive: move to completed, task is done
- escalate: write to escalations dir, notify user
- batch_again: ready for next async batch step
- live_model: needs immediate live model response
"""

    client = anthropic.Anthropic()

    classification_response = client.messages.create(
        model=config['router_model'],
        max_tokens=512,
        messages=[
            {"role": "user", "content": classification_prompt}
        ]
    )

    # Parse classification
    try:
        # Extract JSON from response
        response_text_full = classification_response.content[0].text
        # Try to find JSON in response
        start = response_text_full.find('{')
        end = response_text_full.rfind('}') + 1
        if start >= 0 and end > start:
            json_str = response_text_full[start:end]
            classification = json.loads(json_str)
        else:
            classification = {
                "classification": "error",
                "route": "escalate",
                "reason": "Could not parse router response"
            }
    except json.JSONDecodeError:
        classification = {
            "classification": "error",
            "route": "escalate",
            "reason": "Router classification failed"
        }

    # Execute routing decision
    escalations_dir = Path(config['escalations_dir'])
    completed_dir = Path(config['completed_dir'])
    logs_dir = Path(config['logs_dir'])

    routing_end_time = datetime.now()
    routing_result = {
        "request_id": request_id,
        "classification": classification,
        "routed_at": routing_end_time.isoformat(),
        "routing_time_ms": round((routing_end_time - routing_start_time).total_seconds() * 1000, 2)
    }

    route = classification.get('route', 'escalate')

    if route == 'escalate' or route == 'action_needed':
        # Write to escalations
        escalation_file = escalations_dir / f"{request_id}.escalate"
        with open(escalation_file, 'w', encoding='utf-8') as f:
            json.dump({
                "request_id": request_id,
                "result_file": str(result_file),
                "classification": classification,
                "response": response_text,
                "escalated_at": datetime.now().isoformat(),
                "routing_time_ms": routing_result["routing_time_ms"]
            }, f, indent=2)
        routing_result['action'] = f"escalated to {escalation_file}"

    elif route == 'archive':
        # Move to completed
        completed_file = completed_dir / f"{request_id}.done"
        with open(completed_file, 'w', encoding='utf-8') as f:
            json.dump(routing_result, f)
        result_file.unlink()  # Remove result file
        routing_result['action'] = f"archived to {completed_file}"

    # Log routing decision with timing
    log_msg = f"[{datetime.now().isoformat()}] {request_id} → {route} ({routing_result['routing_time_ms']}ms) {classification.get('summary', 'no summary')}"
    print(log_msg, file=sys.stderr)

    with open(logs_dir / "router.log", 'a', encoding='utf-8') as f:
        f.write(log_msg + "\n")

    return routing_result

if __name__ == "__main__":
    responses_dir = Path(os.environ.get('BATCH_RESPONSES_DIR'))

    # Process all completed results
    routed = 0
    for result_file in sorted(responses_dir.glob("*.result")):
        try:
            route_result(result_file)
            routed += 1
        except Exception as e:
            print(f"Error routing {result_file}: {e}", file=sys.stderr)

    print(json.dumps({"routed": routed}))
