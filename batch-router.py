#!/usr/bin/env python3
"""Route batch results: classify and decide next action.

Uses a live (non-batch) LLM call to classify each completed result
and decide whether to archive, escalate, or queue next step.

Supports multiple LLM providers for routing via the providers/ layer.
"""

import json
import sys
import os
import re
import argparse
from pathlib import Path
from datetime import datetime

from providers import get_provider, list_providers, BatchStatus


def load_config():
    """Load batch configuration."""
    return {
        'responses_dir': os.environ.get('BATCH_RESPONSES_DIR'),
        'escalations_dir': os.environ.get('BATCH_ESCALATIONS_DIR'),
        'completed_dir': os.environ.get('BATCH_COMPLETED_DIR'),
        'logs_dir': os.environ.get('BATCH_LOGS_DIR'),
        'project_dir': os.environ.get('PROJECT_DIR'),
        'project_context_file': os.environ.get('PROJECT_CONTEXT_FILE'),
        'router_model': os.environ.get('ROUTER_MODEL', 'claude-haiku-4-5-20251001'),
        'router_provider': os.environ.get('BATCH_PROVIDER', 'anthropic'),
    }


def load_project_context(config):
    """Load project context for routing decisions."""
    context = ""
    
    # Try explicit context file first
    ctx_file = config.get('project_context_file')
    if ctx_file and Path(ctx_file).exists():
        with open(ctx_file, encoding='utf-8') as f:
            context = f.read()[:2000]
        return context
    
    # Try project_dir/handoff.md or similar
    project_dir = config.get('project_dir')
    if project_dir:
        candidates = [
            Path(project_dir) / "docs/handoff.md",
            Path(project_dir) / "HANDOFF.md",
            Path(project_dir) / "README.md",
            Path(project_dir) / "CONTEXT.md",
        ]
        for candidate in candidates:
            if candidate.exists():
                with open(candidate, encoding='utf-8') as f:
                    context = f.read()[:2000]
                break
    
    return context


def classify_with_live_api(response_text, project_context, config):
    """Use a live API call to classify the batch result.
    
    Supports multiple providers for the routing classification step.
    Falls back to Anthropic if the configured provider doesn't support
    live chat completions well (OpenRouter works fine too).
    """
    router_provider = config.get('router_provider', 'anthropic')
    router_model = config.get('router_model', 'claude-haiku-4-5-20251001')
    
    classification_prompt = f"""Classify this batch result and route it:

Project context:
{project_context}

Response to classify:
{response_text}

Respond ONLY with JSON (no markdown, no backticks):
{{
  "classification": "text|question|error|action_needed|ready_to_commit",
  "confidence": 0.0-1.0,
  "summary": "one line summary",
  "route": "archive|escalate|batch_again|live_model",
  "reason": "brief reason for this routing decision"
}}

Classifications:
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

    # Use the provider to make a live chat call
    provider = get_provider(router_provider)
    
    # Build a single-turn "live" message using the provider's format
    # For the router, we build a request and submit it as a single-item batch,
    # then poll for the result (simplest cross-provider approach).
    # 
    # Better: use the provider's native live API if available.
    # For now, we submit as a tiny batch and wait.
    
    router_request = provider.build_request(
        custom_id="router-classification",
        user_message=classification_prompt,
        system_message=None,
        model=router_model,
        max_tokens=512,
    )
    
    # Submit as a batch
    batch_id = provider.create_batch([router_request])
    
    # Poll until done (should be quick for a single small request)
    import time
    max_wait = 30  # seconds
    waited = 0
    while waited < max_wait:
        status = provider.retrieve_batch(batch_id)
        if status['status'] == BatchStatus.COMPLETED:
            break
        elif status['status'] == BatchStatus.FAILED:
            raise RuntimeError(f"Router classification batch failed: {status.get('errors', 'unknown')}")
        time.sleep(1)
        waited += 1
    
    if waited >= max_wait:
        raise TimeoutError("Router classification timed out")
    
    # Get results
    results = provider.get_results(batch_id)
    
    if not results:
        raise RuntimeError("No results from router classification")
    
    return results[0].content


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
    response_text = result_data.get('result', {}).get('content', '')
    
    # If response has no content, check for error
    if not response_text and result_data.get('error'):
        response_text = f"ERROR: {result_data['error']}"

    # Get provider info from result
    result_provider = result_data.get('provider', 'unknown')

    # Load project context
    project_context = load_project_context(config)

    # Classify using a live model
    try:
        classification_response = classify_with_live_api(response_text, project_context, config)
    except Exception as e:
        print(f"Error during classification for {request_id}: {e}", file=sys.stderr)
        classification = {
            "classification": "error",
            "route": "escalate",
            "reason": f"Router classification failed: {e}",
            "summary": "Classification error",
            "confidence": 0.0,
        }
    else:
        # Parse classification JSON from response
        try:
            # Extract JSON from response (handles markdown-wrapped JSON)
            start = classification_response.find('{')
            end = classification_response.rfind('}') + 1
            if start >= 0 and end > start:
                json_str = classification_response[start:end]
                classification = json.loads(json_str)
            else:
                classification = {
                    "classification": "error",
                    "route": "escalate",
                    "reason": "Could not parse router response",
                    "summary": "Parse error",
                    "confidence": 0.0,
                }
        except json.JSONDecodeError:
            classification = {
                "classification": "error",
                "route": "escalate",
                "reason": "Router classification JSON parse failed",
                "summary": "Parse error",
                "confidence": 0.0,
            }

    # Execute routing decision
    escalations_dir = Path(config['escalations_dir'])
    completed_dir = Path(config['completed_dir'])
    logs_dir = Path(config['logs_dir'])

    routing_end_time = datetime.now()
    routing_result = {
        "request_id": request_id,
        "provider": result_provider,
        "classification": classification,
        "routed_at": routing_end_time.isoformat(),
        "routing_time_ms": round((routing_end_time - routing_start_time).total_seconds() * 1000, 2),
    }

    route = classification.get('route', 'escalate')

    if route in ('escalate', 'action_needed'):
        # Write to escalations
        escalation_file = escalations_dir / f"{request_id}.escalate"
        with open(escalation_file, 'w', encoding='utf-8') as f:
            json.dump({
                "request_id": request_id,
                "provider": result_provider,
                "result_file": str(result_file),
                "classification": classification,
                "response": response_text,
                "escalated_at": datetime.now().isoformat(),
                "routing_time_ms": routing_result["routing_time_ms"],
            }, f, indent=2)
        routing_result['action'] = f"escalated to {escalation_file}"

    elif route == 'archive':
        # Move to completed
        completed_file = completed_dir / f"{request_id}.done"
        with open(completed_file, 'w', encoding='utf-8') as f:
            json.dump(routing_result, f, indent=2)
        result_file.unlink(missing_ok=True)  # Remove result file
        routing_result['action'] = f"archived to {completed_file}"

    # Log routing decision with timing
    log_msg = (
        f"[{datetime.now().isoformat()}] "
        f"[{result_provider}] {request_id} → {route} "
        f"({routing_result['routing_time_ms']}ms) "
        f"{classification.get('summary', 'no summary')}"
    )
    print(log_msg, file=sys.stderr)

    with open(logs_dir / "router.log", 'a', encoding='utf-8') as f:
        f.write(log_msg + "\n")

    return routing_result


def main():
    parser = argparse.ArgumentParser(
        description="Route batch results: classify and decide next action."
    )
    parser.add_argument(
        "--provider", "-p",
        default=None,
        choices=list_providers(),
        help="Provider for routing classification (default: from BATCH_PROVIDER env)"
    )
    parser.add_argument(
        "result_files",
        nargs="*",
        help="Specific result files to route (default: all in BATCH_RESPONSES_DIR)"
    )
    
    args = parser.parse_args()
    
    if args.provider:
        os.environ['BATCH_PROVIDER'] = args.provider
    
    responses_dir = Path(os.environ.get('BATCH_RESPONSES_DIR', ''))
    if not responses_dir.exists() and not args.result_files:
        print(json.dumps({"routed": 0, "error": "No responses directory found"}))
        return
    
    # Process results
    routed = 0
    
    if args.result_files:
        files_to_process = [Path(f) for f in args.result_files]
    else:
        files_to_process = sorted(responses_dir.glob("*.result"))
    
    for result_file in files_to_process:
        if not result_file.exists():
            print(f"Warning: {result_file} does not exist, skipping", file=sys.stderr)
            continue
        try:
            route_result(result_file)
            routed += 1
        except Exception as e:
            print(f"Error routing {result_file}: {e}", file=sys.stderr)

    print(json.dumps({"routed": routed}))


if __name__ == "__main__":
    main()