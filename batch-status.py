#!/usr/bin/env python3
"""Display batch pipeline status with visual formatting.

Supports multiple providers. Reads from the shared .batch-state file.
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from time import time

from batch_common import format_duration, pipeline_counts, resolve_paths


def get_status_icon(status):
    """Return icon for status."""
    icons = {
        'submitted': '📤',
        'running': '⏳',
        'completed': '✅',
        'failed': '❌',
        'cancelled': '🚫',
        'escalation': '⚠️ ',
    }
    return icons.get(status, '❓')


def display_visual(config):
    """Display status with visual formatting."""

    state_file = Path(config['state_file'])

    if not state_file.exists():
        print("❌ No batch state found. Run 'batch send' to start a batch.\n")
        return

    with open(state_file, encoding='utf-8') as f:
        state = json.load(f)

    counts = pipeline_counts()

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
    print(f"  {counts['running']:3d} ⏳ Running        {counts['completed']:3d} ✅ Collected")
    print(f"  {counts['awaiting_routing']:3d} 📥 To route       {counts['escalations']:3d} ⚠️  Escalations")
    print(f"  {counts['archived']:3d} 🗄  Archived       {counts['failed'] + counts['cancelled']:3d} ❌ Failed/cancelled")

    total_batches = len(state)
    print(f"\n  Total Batches: {total_batches}")

    # Status breakdown
    print("\n📋 BATCH DETAILS:")
    print("-" * 80)
    print(f"  {'STATUS':<12} {'PROVIDER':<12} {'ID':<9} {'AGE':<8} {'SUMMARY':<35}")
    print("-" * 80)

    # Sort by status (running first, then completed, then others)
    status_order = {'running': 0, 'submitted': 1, 'completed': 2, 'failed': 3, 'cancelled': 4}
    sorted_batches = sorted(state.items(),
                           key=lambda x: (status_order.get(x[1].get('status'), 99),
                                        -x[1].get('submitted_at_unix', 0)))

    for _, batch_info in sorted_batches[:15]:  # Show top 15
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
    config = resolve_paths()

    # Check for --json flag
    if "--json" in sys.argv:
        display_json(config)
    else:
        display_visual(config)