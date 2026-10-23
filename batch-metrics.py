#!/usr/bin/env python3
"""Analyze batch processing metrics: latency, throughput, performance.

Supports multiple providers. Metrics are per-provider and aggregated.
"""

import json
import sys
from pathlib import Path
from statistics import mean, median, stdev, StatisticsError

from batch_common import load_state, resolve_paths


def analyze_metrics():
    """Analyze batch pipeline metrics across all providers.

    Latency and throughput come from the batches the poller has collected
    (the state file); routing time comes from the router's archive records.
    """

    config = resolve_paths()
    completed_dir = Path(config['completed_dir'])

    # Routing times from the archive records the router writes
    routing_times = []
    archived_results = 0
    if completed_dir.exists():
        for done_file in sorted(completed_dir.glob("*.done")):
            try:
                with open(done_file, encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                print(f"Error reading {done_file}: {e}", file=sys.stderr)
                continue
            archived_results += 1
            if 'routing_time_ms' in data:
                routing_times.append(data['routing_time_ms'])

    # Latencies of collected batches, plus when each was submitted and finished
    latencies_by_provider = {}
    all_latencies = []
    submitted_times = []
    finished_times = []
    completed_batches = 0

    for batch_info in load_state(config['state_file']).values():
        if batch_info.get('status') != 'completed':
            continue
        completed_batches += 1
        provider = batch_info.get('provider', 'anthropic')
        if 'latency_seconds' in batch_info:
            lat = batch_info['latency_seconds']
            all_latencies.append(lat)
            latencies_by_provider.setdefault(provider, []).append(lat)
        if 'submitted_at_unix' in batch_info and 'completed_at_unix' in batch_info:
            submitted_times.append(batch_info['submitted_at_unix'])
            finished_times.append(batch_info['completed_at_unix'])

    # Calculate overall statistics
    metrics = {
        "completed_batches": completed_batches,
        "archived_results": archived_results,
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

    # Throughput: batches finished per hour of wall-clock time, from the first
    # submission to the last completion. (Batches overlap, so adding up their
    # latencies would not measure this.) It needs at least two batches.
    if len(finished_times) >= 2:
        window = max(finished_times) - min(submitted_times)
        if window > 0:
            metrics["throughput"] = {
                "batches_per_hour": round(len(finished_times) / (window / 3600), 2),
                "window_seconds": round(window, 1),
            }

    return metrics


def format_metrics(metrics):
    """Format metrics for display."""

    print("\n" + "="*65)
    print("BATCH PIPELINE METRICS")
    print("="*65)

    if not metrics.get('completed_batches'):
        print("  No completed batches yet.")
        print("="*65 + "\n")
        return

    print(f"\n📊 Completed Batches: {metrics['completed_batches']}"
          f"   (archived results: {metrics['archived_results']})")

    # Overall latency
    if 'latency' in metrics:
        lat = metrics['latency']
        print(f"\n⏱  Latency (seconds, {lat['total_count']} samples)")
        print("  ┌──────────┬────────────┐")
        print(f"  │ Min      │ {lat['min']:>8.2f}s │")
        print(f"  │ Max      │ {lat['max']:>8.2f}s │")
        print(f"  │ Mean     │ {lat['mean']:>8.2f}s │")
        print(f"  │ Median   │ {lat['median']:>8.2f}s │")
        if lat.get('stdev'):
            print(f"  │ StdDev   │ {lat['stdev']:>8.2f}s │")
        print("  └──────────┴────────────┘")
        print(f"  Total: {metrics['total_latency_seconds']:.0f}s ({metrics['total_latency_seconds']/60:.1f}m)")

    # Per-provider breakdown
    if metrics.get('by_provider'):
        print("\n🏭 Per-Provider Breakdown:")
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
        print("  ┌──────────┬────────────┐")
        print(f"  │ Min      │ {rt['min']:>8.0f}ms │")
        print(f"  │ Max      │ {rt['max']:>8.0f}ms │")
        print(f"  │ Mean     │ {rt['mean']:>8.0f}ms │")
        print(f"  │ Median   │ {rt['median']:>8.0f}ms │")
        if rt.get('stdev'):
            print(f"  │ StdDev   │ {rt['stdev']:>8.0f}ms │")
        print("  └──────────┴────────────┘")

    # Throughput
    if 'throughput' in metrics:
        tp = metrics['throughput']
        print(f"\n📈 Throughput: {tp['batches_per_hour']} batches/hr"
              f"  (over {tp['window_seconds'] / 60:.1f} min, first submit to last completion)")

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
