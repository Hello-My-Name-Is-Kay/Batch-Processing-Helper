#!/usr/bin/env python3
"""Analyze batch processing metrics: latency, throughput, performance."""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
from statistics import mean, median, stdev

def load_config():
    """Load batch configuration."""
    return {
        'state_file': os.environ.get('BATCH_STATE'),
        'completed_dir': os.environ.get('BATCH_COMPLETED_DIR'),
        'logs_dir': os.environ.get('BATCH_LOGS_DIR'),
    }

def analyze_metrics():
    """Analyze batch pipeline metrics."""

    config = load_config()
    completed_dir = Path(config['completed_dir'])

    if not completed_dir.exists():
        print("No completed batches yet.")
        return {}

    # Read all completed requests
    latencies = []
    routing_times = []
    completed_requests = []

    for done_file in sorted(completed_dir.glob("*.done")):
        try:
            with open(done_file, encoding='utf-8') as f:
                data = json.load(f)
                completed_requests.append(data)

                # Extract latency if available (from state file)
                # Latency stored in state file, not in done file
        except Exception as e:
            print(f"Error reading {done_file}: {e}", file=sys.stderr)

    # Read state file to get latencies
    state_file = Path(config['state_file'])
    if state_file.exists():
        try:
            with open(state_file, encoding='utf-8') as f:
                state = json.load(f)
                for batch_id, batch_info in state.items():
                    if batch_info.get('status') == 'completed':
                        if 'latency_seconds' in batch_info:
                            latencies.append(batch_info['latency_seconds'])
        except Exception as e:
            print(f"Error reading state file: {e}", file=sys.stderr)

    # Read routing times from completed files
    for req in completed_requests:
        if 'routing_time_ms' in req:
            routing_times.append(req['routing_time_ms'])

    # Calculate statistics
    metrics = {
        "completed_requests": len(completed_requests),
        "total_latency_seconds": sum(latencies) if latencies else 0,
        "total_routing_time_ms": sum(routing_times) if routing_times else 0,
    }

    if latencies:
        metrics["latency"] = {
            "min": min(latencies),
            "max": max(latencies),
            "mean": mean(latencies),
            "median": median(latencies),
            "stdev": stdev(latencies) if len(latencies) > 1 else 0,
            "total_count": len(latencies)
        }

    if routing_times:
        metrics["routing_time"] = {
            "min": min(routing_times),
            "max": max(routing_times),
            "mean": mean(routing_times),
            "median": median(routing_times),
            "stdev": stdev(routing_times) if len(routing_times) > 1 else 0,
            "total_count": len(routing_times)
        }

    return metrics

def format_metrics(metrics):
    """Format metrics for display."""

    print("\n" + "="*60)
    print("BATCH PIPELINE METRICS")
    print("="*60)

    if not metrics.get('completed_requests'):
        print("No completed requests yet.")
        return

    print(f"\nCompleted Requests: {metrics['completed_requests']}")

    if 'latency' in metrics:
        lat = metrics['latency']
        print(f"\n--- Latency (seconds, {lat['total_count']} samples) ---")
        print(f"  Min:     {lat['min']:.2f}s")
        print(f"  Max:     {lat['max']:.2f}s")
        print(f"  Mean:    {lat['mean']:.2f}s")
        print(f"  Median:  {lat['median']:.2f}s")
        if lat['stdev'] > 0:
            print(f"  StdDev:  {lat['stdev']:.2f}s")
        print(f"  Total:   {metrics['total_latency_seconds']:.0f}s ({metrics['total_latency_seconds']/60:.1f} min)")

    if 'routing_time' in metrics:
        rt = metrics['routing_time']
        print(f"\n--- Routing Time (milliseconds, {rt['total_count']} samples) ---")
        print(f"  Min:     {rt['min']:.0f}ms")
        print(f"  Max:     {rt['max']:.0f}ms")
        print(f"  Mean:    {rt['mean']:.0f}ms")
        print(f"  Median:  {rt['median']:.0f}ms")
        if rt['stdev'] > 0:
            print(f"  StdDev:  {rt['stdev']:.0f}ms")
        print(f"  Total:   {metrics['total_routing_time_ms']:.0f}ms")

    # Throughput
    if metrics['completed_requests'] > 0 and metrics['total_latency_seconds'] > 0:
        throughput = metrics['completed_requests'] / (metrics['total_latency_seconds'] / 3600)
        print(f"\n--- Throughput ---")
        print(f"  Requests/hour: {throughput:.1f}")

    print("\n" + "="*60 + "\n")

def export_json(metrics, output_file):
    """Export metrics as JSON."""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2)
    print(f"Metrics exported to {output_file}")

if __name__ == "__main__":
    metrics = analyze_metrics()

    if "--json" in sys.argv:
        # Export to JSON file
        output_file = sys.argv[sys.argv.index("--json") + 1] if sys.argv.index("--json") + 1 < len(sys.argv) else "batch-metrics.json"
        export_json(metrics, output_file)
    else:
        # Display formatted metrics
        format_metrics(metrics)
        # Also output JSON for programmatic use
        print("JSON:")
        print(json.dumps(metrics, indent=2))
