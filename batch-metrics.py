#!/usr/bin/env python3
"""Analyze batch processing metrics: latency, throughput, performance.

Supports multiple providers. Metrics are per-provider and aggregated.
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
from statistics import mean, median, stdev, StatisticsError


def load_config():
    """Load batch configuration."""
    return {
        'state_file': os.environ.get('BATCH_STATE'),
        'completed_dir': os.environ.get('BATCH_COMPLETED_DIR'),
        'logs_dir': os.environ.get('BATCH_LOGS_DIR'),
    }


def analyze_metrics():
    """Analyze batch pipeline metrics across all providers."""

    config = load_config()
    completed_dir = Path(config['completed_dir'])

    if not completed_dir.exists():
        print("No completed batches yet.")
        return {}

    # Read all completed requests
    completed_requests = []

    for done_file in sorted(completed_dir.glob("*.done")):
        try:
            with open(done_file, encoding='utf-8') as f:
                data = json.load(f)
                completed_requests.append(data)
        except Exception as e:
            print(f"Error reading {done_file}: {e}", file=sys.stderr)

    # Read state file to get latencies
    state_file = Path(config['state_file'])
    
    # Per-provider stats
    latencies_by_provider = {}
    routing_times_by_provider = []
    routing_times = []
    all_latencies = []

    if state_file.exists():
        try:
            with open(state_file, encoding='utf-8') as f:
                state = json.load(f)
                for batch_id, batch_info in state.items():
                    if batch_info.get('status') == 'completed':
                        provider = batch_info.get('provider', 'anthropic')
                        if 'latency_seconds' in batch_info:
                            lat = batch_info['latency_seconds']
                            all_latencies.append(lat)
                            if provider not in latencies_by_provider:
                                latencies_by_provider[provider] = []
                            latencies_by_provider[provider].append(lat)
        except Exception as e:
            print(f"Error reading state file: {e}", file=sys.stderr)

    # Read routing times from completed files
    for req in completed_requests:
        if 'routing_time_ms' in req:
            routing_times.append(req['routing_time_ms'])
            provider = req.get('provider', 'unknown')
            routing_times_by_provider.append((provider, req['routing_time_ms']))

    # Calculate overall statistics
    metrics = {
        "completed_requests": len(completed_requests),
        "total_latency_seconds": sum(all_latencies) if all_latencies else 0,
        "total_routing_time_ms": sum(routing_times) if routing_times else 0,
        "by_provider": {},
    }

    # Overall latency stats
    if all_latencies:
        try:
            metrics["latency"] = {
                "min": min(all_latencies),
                "max": max(all_latencies),
                "mean": mean(all_latencies),
                "median": median(all_latencies),
                "stdev": stdev(all_latencies) if len(all_latencies) > 1 else 0,
                "total_count": len(all_latencies),
            }
        except StatisticsError:
            pass

    if routing_times:
        try:
            metrics["routing_time"] = {
                "min": min(routing_times),
                "max": max(routing_times),
                "mean": mean(routing_times),
                "median": median(routing_times),
                "stdev": stdev(routing_times) if len(routing_times) > 1 else 0,
                "total_count": len(routing_times),
            }
        except StatisticsError:
            pass

    # Per-provider metrics
    for provider, latencies in latencies_by_provider.items():
        provider_metrics = {
            "total_requests": len(latencies),
            "total_latency_seconds": sum(latencies),
        }
        if latencies:
            try:
                provider_metrics["latency"] = {
                    "min": min(latencies),
                    "max": max(latencies),
                    "mean": mean(latencies),
                    "median": median(latencies),
                }
            except StatisticsError:
                pass
        metrics["by_provider"][provider] = provider_metrics

    # Throughput
    if metrics['completed_requests'] > 0 and metrics['total_latency_seconds'] > 0:
        throughput = metrics['completed_requests'] / (metrics['total_latency_seconds'] / 3600)
        metrics["throughput"] = {
            "requests_per_hour": round(throughput, 2),
        }

    return metrics


def format_metrics(metrics):
    """Format metrics for display."""

    print("\n" + "="*65)
    print("BATCH PIPELINE METRICS")
    print("="*65)

    if not metrics.get('completed_requests'):
        print("  No completed requests yet.")
        print("="*65 + "\n")
        return

    print(f"\n📊 Completed Requests: {metrics['completed_requests']}")

    # Overall latency
    if 'latency' in metrics:
        lat = metrics['latency']
        print(f"\n⏱  Latency (seconds, {lat['total_count']} samples)")
        print(f"  ┌──────────┬────────────┐")
        print(f"  │ Min      │ {lat['min']:>8.2f}s │")
        print(f"  │ Max      │ {lat['max']:>8.2f}s │")
        print(f"  │ Mean     │ {lat['mean']:>8.2f}s │")
        print(f"  │ Median   │ {lat['median']:>8.2f}s │")
        if lat.get('stdev'):
            print(f"  │ StdDev   │ {lat['stdev']:>8.2f}s │")
        print(f"  └──────────┴────────────┘")
        print(f"  Total: {metrics['total_latency_seconds']:.0f}s ({metrics['total_latency_seconds']/60:.1f}m)")

    # Per-provider breakdown
    if metrics.get('by_provider'):
        print(f"\n🏭 Per-Provider Breakdown:")
        for provider, pm in metrics['by_provider'].items():
            print(f"  {provider}:")
            print(f"    Requests: {pm['total_requests']}")
            if 'latency' in pm:
                pl = pm['latency']
                print(f"    Latency:  mean={pl['mean']:.1f}s  median={pl['median']:.1f}s  range=[{pl['min']:.1f}s, {pl['max']:.1f}s]")

    # Routing time
    if 'routing_time' in metrics:
        rt = metrics['routing_time']
        print(f"\n⚡ Routing Time (ms, {rt['total_count']} samples)")
        print(f"  ┌──────────┬────────────┐")
        print(f"  │ Min      │ {rt['min']:>8.0f}ms │")
        print(f"  │ Max      │ {rt['max']:>8.0f}ms │")
        print(f"  │ Mean     │ {rt['mean']:>8.0f}ms │")
        print(f"  │ Median   │ {rt['median']:>8.0f}ms │")
        if rt.get('stdev'):
            print(f"  │ StdDev   │ {rt['stdev']:>8.0f}ms │")
        print(f"  └──────────┴────────────┘")

    # Throughput
    if 'throughput' in metrics:
        print(f"\n📈 Throughput: {metrics['throughput']['requests_per_hour']} req/hr")

    print("\n" + "="*65 + "\n")


def export_json(metrics, output_file):
    """Export metrics as JSON."""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2)
    print(f"Metrics exported to {output_file}")


if __name__ == "__main__":
    metrics = analyze_metrics()

    if "--json" in sys.argv:
        idx = sys.argv.index("--json")
        output_file = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "batch-metrics.json"
        export_json(metrics, output_file)
    else:
        format_metrics(metrics)
        # Also output JSON for programmatic use
        print("--- JSON ---")
        print(json.dumps(metrics, indent=2))