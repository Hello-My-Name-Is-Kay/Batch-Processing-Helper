#!/usr/bin/env python3
"""Display batch pipeline status with visual formatting."""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
from time import time

def load_config():
    """Load batch configuration."""
    return {
        'state_file': os.environ.get('BATCH_STATE'),
        'requests_dir': os.environ.get('BATCH_REQUESTS_DIR'),
        'responses_dir': os.environ.get('BATCH_RESPONSES_DIR'),
        'escalations_dir': os.environ.get('BATCH_ESCALATIONS_DIR'),
        'completed_dir': os.environ.get('BATCH_COMPLETED_DIR'),
    }

def get_status_icon(status):
    """Return icon for status."""
    icons = {
        'submitted': '📤',
        'running': '⏳',
        'completed': '✅',
        'failed': '❌',
        'escalation': '⚠️ ',
    }
    return icons.get(status, '❓')

def format_duration(seconds):
    """Format seconds into readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"

def display_visual(config):
    """Display status with visual formatting."""

    state_file = Path(config['state_file'])

    if not state_file.exists():
        print("❌ No batch state found. Run 'batch send' to start a batch.\n")
        return

    with open(state_file, encoding='utf-8') as f:
        state = json.load(f)

    # Count items
    requests_count = len(list(Path(config['requests_dir']).glob("*.jsonl"))) if Path(config['requests_dir']).exists() else 0
    responses_count = len(list(Path(config['responses_dir']).glob("*.result"))) if Path(config['responses_dir']).exists() else 0
    escalations_count = len(list(Path(config['escalations_dir']).glob("*.escalate"))) if Path(config['escalations_dir']).exists() else 0
    completed_count = len(list(Path(config['completed_dir']).glob("*.done"))) if Path(config['completed_dir']).exists() else 0

    current_time = time()

    # Header
    print("\n" + "="*70)
    print(" " * 15 + "🔄 BATCH PIPELINE STATUS")
    print("="*70)

    # Summary
    print("\n📊 PIPELINE SUMMARY:")
    print(f"  {requests_count:3d} 📤 Queued        {responses_count:3d} ⏳ Processing")
    print(f"  {completed_count:3d} ✅ Completed     {escalations_count:3d} ⚠️  Escalations")

    total_batches = len(state)
    print(f"\n  Total Batches: {total_batches}")

    # Status breakdown
    print("\n📋 BATCH DETAILS:")
    print("-" * 70)
    print(f"  {'STATUS':<12} {'ID':<9} {'AGE':<8} {'SUMMARY':<35}")
    print("-" * 70)

    # Sort by status (running first, then completed, then others)
    status_order = {'running': 0, 'submitted': 1, 'completed': 2, 'failed': 3}
    sorted_batches = sorted(state.items(),
                           key=lambda x: (status_order.get(x[1].get('status'), 99),
                                        -x[1].get('submitted_at_unix', 0)))

    for batch_id, batch_info in sorted_batches[:10]:  # Show top 10
        status = batch_info.get('status', 'unknown')
        req_id = batch_info.get('custom_id', 'unknown')[:8]

        # Calculate age
        submitted_unix = batch_info.get('submitted_at_unix', 0)
        if submitted_unix:
            age_seconds = current_time - submitted_unix
            age_str = format_duration(age_seconds)
        else:
            age_str = "?"

        # Get summary (from latency if completed)
        if status == 'completed' and 'latency_minutes' in batch_info:
            summary = f"✅ {batch_info['latency_minutes']}m latency"
        elif status == 'running':
            summary = f"⏳ {age_str} running"
        else:
            summary = f"{status.capitalize()}"

        icon = get_status_icon(status)
        print(f"  {icon} {status:<10} {req_id:<9} {age_str:<8} {summary:<35}")

    if total_batches > 10:
        print(f"  ... and {total_batches - 10} more")

    print("\n" + "="*70)

    # Escalations section
    escalations_dir = Path(config['escalations_dir'])
    if escalations_dir.exists():
        escalations = list(escalations_dir.glob("*.escalate"))
        if escalations:
            print("\n⚠️  ESCALATIONS AWAITING REVIEW:")
            print("-" * 70)
            for esc_file in escalations[:5]:
                req_id = esc_file.stem
                print(f"  • {req_id}")
            if len(escalations) > 5:
                print(f"  ... and {len(escalations) - 5} more")
            print()

    print("="*70 + "\n")

def display_json(config):
    """Display raw JSON output."""

    state_file = Path(config['state_file'])

    if not state_file.exists():
        print(json.dumps({"error": "No batch state found"}, indent=2))
        return

    with open(state_file, encoding='utf-8') as f:
        state = json.load(f)

    # Add current time for age calculation
    output = {
        "timestamp": datetime.now().isoformat(),
        "timestamp_unix": time(),
        "batches": state,
        "summary": {
            "total": len(state),
            "by_status": {}
        }
    }

    # Count by status
    for batch_info in state.values():
        status = batch_info.get('status', 'unknown')
        output['summary']['by_status'][status] = output['summary']['by_status'].get(status, 0) + 1

    print(json.dumps(output, indent=2))

if __name__ == "__main__":
    import os
    from pathlib import Path

    # Load config from environment
    SCRIPT_DIR = Path(__file__).parent
    config_path = SCRIPT_DIR / "batch-config.sh"

    # Manual config (fallback)
    config = load_config()

    # Use provided config or defaults
    if not config['state_file']:
        config['state_file'] = os.path.expanduser('~/.claude/batch-pipeline/freedom-os/.batch-state')
        config['requests_dir'] = os.path.expanduser('~/.claude/batch-pipeline/freedom-os/requests')
        config['responses_dir'] = os.path.expanduser('~/.claude/batch-pipeline/freedom-os/responses')
        config['escalations_dir'] = os.path.expanduser('~/.claude/batch-pipeline/freedom-os/escalations')
        config['completed_dir'] = os.path.expanduser('~/.claude/batch-pipeline/freedom-os/completed')

    # Check for --json flag
    if "--json" in sys.argv:
        display_json(config)
    else:
        display_visual(config)
