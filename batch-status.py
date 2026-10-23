#!/usr/bin/env python3
"""Display batch pipeline status with visual formatting.

Supports multiple providers. Reads from the shared .batch-state file.
"""

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
    base = Path(config['requests_dir']) if config['requests_dir'] else Path()
    requests_count = len(list(base.glob("*.jsonl"))) if base.exists() else 0
    base = Path(config['responses_dir']) if config['responses_dir'] else Path()
    responses_count = len(list(base.glob("*.result"))) if base.exists() else 0
    base = Path(config['escalations_dir']) if config['escalations_dir'] else Path()
    escalations_count = len(list(base.glob("*.escalate"))) if base.exists() else 0
    base = Path(config['completed_dir']) if config['completed_dir'] else Path()
    completed_count = len(list(base.glob("*.done"))) if base.exists() else 0

    current_time = time()

    # Count by provider
    providers = set()
    for batch_info in state.values():
        provider = batch_info.get('provider', 'anthropic')
        providers.add(provider)
    provider_list = ", ".join(sorted(providers))

    # Header
    print("\n" + "="*70)
    print(" " * 15 + "🔄 BATCH PIPELINE STATUS")
    print("="*70)

    # Provider info
    print(f"\n  Providers: {provider_list}")

    # Summary
    print("\n📊 PIPELINE SUMMARY:")
    print(f"  {requests_count:3d} 📤 Queued        {responses_count:3d} ⏳ Processing")
    print(f"  {completed_count:3d} ✅ Completed     {escalations_count:3d} ⚠️  Escalations")

    total_batches = len(state)
    print(f"\n  Total Batches: {total_batches}")

    # Status breakdown
    print("\n📋 BATCH DETAILS:")
    print("-" * 80)
    print(f"  {'STATUS':<12} {'PROVIDER':<12} {'ID':<9} {'AGE':<8} {'SUMMARY':<35}")
    print("-" * 80)

    # Sort by status (running first, then completed, then others)
    status_order = {'running': 0, 'submitted': 1, 'completed': 2, 'failed': 3}
    sorted_batches = sorted(state.items(),
                           key=lambda x: (status_order.get(x[1].get('status'), 99),
                                        -x[1].get('submitted_at_unix', 0)))

    for batch_id, batch_info in sorted_batches[:15]:  # Show top 15
        status = batch_info.get('status', 'unknown')
        provider = batch_info.get('provider', '?')[:10]
        req_id = batch_info.get('custom_id', 'unknown')[:8]

        # Calculate age
        submitted_unix = batch_info.get('submitted_at_unix', 0)
        if submitted_unix:
            age_seconds = current_time - submitted_unix
            age_str = format_duration(age_seconds)
        else:
            age_str = "?"

        # Get summary
        if status == 'completed' and 'latency_minutes' in batch_info:
            summary = f"✅ {batch_info['latency_minutes']}m latency"
        elif status == 'running':
            summary = f"⏳ {age_str} running"
        else:
            summary = f"{status.capitalize()}"

        icon = get_status_icon(status)
        print(f"  {icon} {status:<10} {provider:<12} {req_id:<9} {age_str:<8} {summary:<35}")

    if total_batches > 15:
        print(f"  ... and {total_batches - 15} more")

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
                # Try to get provider info from escalation file
                provider_info = ""
                try:
                    with open(esc_file, encoding='utf-8') as f:
                        esc_data = json.load(f)
                        provider_info = esc_data.get('provider', '')
                except Exception:
                    pass
                prov_str = f" [{provider_info}]" if provider_info else ""
                print(f"  • {req_id}{prov_str}")
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
            "by_status": {},
            "by_provider": {},
        }
    }

    # Count by status and provider
    for batch_info in state.values():
        status = batch_info.get('status', 'unknown')
        provider = batch_info.get('provider', 'unknown')
        output['summary']['by_status'][status] = output['summary']['by_status'].get(status, 0) + 1
        output['summary']['by_provider'][provider] = output['summary']['by_provider'].get(provider, 0) + 1

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    import os
    from pathlib import Path

    SCRIPT_DIR = Path(__file__).parent

    # Load config from environment
    config = load_config()

    # Use provided config or defaults (inside project directory)
    if not config['state_file']:
        default_batch_dir = SCRIPT_DIR / '.batch-data'
        config['state_file'] = str(default_batch_dir / '.batch-state')
        config['requests_dir'] = str(default_batch_dir / 'requests')
        config['responses_dir'] = str(default_batch_dir / 'responses')
        config['escalations_dir'] = str(default_batch_dir / 'escalations')
        config['completed_dir'] = str(default_batch_dir / 'completed')

    # Check for --json flag
    if "--json" in sys.argv:
        display_json(config)
    else:
        display_visual(config)