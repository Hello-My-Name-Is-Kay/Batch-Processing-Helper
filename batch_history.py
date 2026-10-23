#!/usr/bin/env python3
"""
Batch processing history tracker.

Logs every completed batch to a persistent history file, keyed by provider
and model. Supports querying, aggregating, and analyzing historical data.

History directory structure:
  .batch-data/history/
    history.jsonl          — Append-only log of every batch completion

Aggregates (per provider and per model) are computed from that log when asked
for, so there is no second copy to keep in step.
"""

import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from collections import defaultdict

from batch_common import batch_dir


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _history_file() -> Path:
    return batch_dir() / "history" / "history.jsonl"


def _to_unix(value) -> Optional[float]:
    """Coerce a datetime, ISO-8601 string or number to a unix timestamp.

    Providers report batch times in different shapes; None means "unknown".
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def make_history_entry(batch_id: str,
                       provider: str,
                       model: str,
                       raw_model: str,
                       status: str,
                       created_at: float,
                       finalized_at: float,
                       total_requests: int,
                       completed_requests: int,
                       failed_requests: int = 0,
                       prompt_tokens: Optional[int] = None,
                       completion_tokens: Optional[int] = None,
                       total_tokens: Optional[int] = None,
                       cost: Optional[float] = None,
                       submitted_at_unix: Optional[float] = None,
                       provider_backend: Optional[str] = None,
                       agent: Optional[str] = None,
                       custom_ids: Optional[list] = None,
                       **extra) -> dict:
    """Create a standardized history entry."""
    created_at = _to_unix(created_at)
    finalized_at = _to_unix(finalized_at)
    entry = {
        "batch_id": batch_id,
        "provider": provider,
        "model": model,
        "raw_model": raw_model,
        "status": status,
        "created_at": created_at,
        "finalized_at": finalized_at,
        "latency_seconds": round(finalized_at - created_at, 1) if finalized_at and created_at else None,
        "total_requests": total_requests,
        "completed_requests": completed_requests,
        "failed_requests": failed_requests,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost": cost,
        "submitted_at_unix": submitted_at_unix,
        "pipeline_latency": round(finalized_at - submitted_at_unix, 1) if finalized_at and submitted_at_unix else None,
        "provider_backend": provider_backend,
        "agent": agent,
        "custom_ids": custom_ids,
        "logged_at": time.time(),
    }
    # Remove None values that aren't meaningful
    return {k: v for k, v in entry.items() if v is not None}


# ---------------------------------------------------------------------------
# Write / read
# ---------------------------------------------------------------------------

def log_completion(entry: dict) -> None:
    """Append a history entry to the JSONL log."""
    hist_file = _history_file()
    hist_file.parent.mkdir(parents=True, exist_ok=True)
    with open(hist_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def read_history() -> list[dict]:
    """Read all history entries (most recent first)."""
    hist_file = _history_file()
    if not hist_file.exists():
        return []
    entries = []
    with open(hist_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return list(reversed(entries))  # newest first


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

def _stats(vals: list[float]) -> dict:
    """Compute summary statistics with adaptive precision.

    Uses more decimal places for very small values (e.g. costs)
    so that sub-cent amounts aren't lost to rounding.
    """
    if not vals:
        return {}
    vals = sorted(vals)
    n = len(vals)
    middle = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    max_val = max(abs(v) for v in vals)
    if max_val < 0.01:
        precision = 8
    elif max_val < 1:
        precision = 6
    else:
        precision = 2
    return {
        "count": n,
        "min": round(min(vals), precision),
        "max": round(max(vals), precision),
        "mean": round(sum(vals) / n, precision),
        "median": round(middle, precision),
        "sum": round(sum(vals), precision),
    }


def _summarize(items: list, pipeline: bool = False) -> dict:
    """Aggregate a group of history entries (latency, cost, tokens, optionally pipeline latency)."""
    series = [("latency_seconds", "latency_seconds")]
    if pipeline:
        series.append(("pipeline_latency_seconds", "pipeline_latency"))
    series += [("cost_usd", "cost"), ("tokens", "total_tokens")]

    stats = {"batches": len(items)}
    for out_key, field in series:
        values = [e[field] for e in items if e.get(field)]
        if values:
            stats[out_key] = _stats(values)
    return stats


def get_aggregates() -> dict:
    """Per-provider and per-model aggregates, computed from the history log ({} if it is empty)."""
    entries = read_history()
    if not entries:
        return {}

    by_provider = defaultdict(list)
    by_model = defaultdict(list)
    for e in entries:
        prov = e.get("provider", "unknown")
        by_provider[prov].append(e)
        by_model[f"{prov}/{e.get('raw_model', e.get('model', 'unknown'))}"].append(e)

    return {
        "total_batches": len(entries),
        "by_provider": {prov: _summarize(items, pipeline=True) for prov, items in by_provider.items()},
        "by_model": {key: _summarize(items) for key, items in by_model.items()},
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_stats(stats: dict) -> None:
    """Print one aggregate block (a provider's or a model's)."""
    print(f"    Batches: {stats.get('batches', 0)}")
    if "latency_seconds" in stats:
        lat = stats["latency_seconds"]
        print(f"    Latency:  min={lat['min']}s  mean={lat['mean']}s  max={lat['max']}s  median={lat['median']}s")
    if "cost_usd" in stats:
        c = stats["cost_usd"]
        print(f"    Cost:     min=${c['min']:.6f}  mean=${c['mean']:.6f}  total=${c['sum']:.4f}")
    if "tokens" in stats:
        t = stats["tokens"]
        print(f"    Tokens:   mean={t['mean']:.0f}  total={t['sum']:,.0f}")


def cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Batch processing history and metrics")
    sub = parser.add_subparsers(dest="command")

    # list (and its alias "show")
    list_args = argparse.ArgumentParser(add_help=False)
    list_args.add_argument("--limit", type=int, default=10)
    list_args.add_argument("--provider", default=None)
    list_args.add_argument("--model", default=None)
    sub.add_parser("list", parents=[list_args], help="List recent history")
    sub.add_parser("show", parents=[list_args], help="Alias for list")

    # stats (and its alias "aggregates")
    sub.add_parser("stats", help="Show aggregates per provider/model")
    sub.add_parser("aggregates", help="Alias for stats")

    args = parser.parse_args()

    if args.command in ("list", "show"):
        entries = read_history()
        provider = args.provider
        model = args.model
        if provider:
            entries = [e for e in entries if e.get("provider") == provider]
        if model:
            entries = [e for e in entries if model in e.get("model", "") or model in e.get("raw_model", "")]
        entries = entries[:args.limit]
        if not entries:
            print("No history entries.")
            return
        print(f"\n{'='*75}")
        print(f"  Batch History (last {len(entries)} of {len(read_history())} total)")
        print(f"{'='*75}")
        print(f"  {'ID':<10} {'PROVIDER':<12} {'MODEL':<32} {'STATUS':<10} {'TIME':<8} {'COST':<8}")
        print(f"  {'-'*74}")
        for e in entries:
            bid = e.get("batch_id", "?")[-8:]
            prov = e.get("provider", "?")[:10]
            model_s = e.get("raw_model", e.get("model", "?"))[:30]
            status = e.get("status", "?")
            lat = e.get("latency_seconds", 0)
            time_s = f"{lat:.0f}s" if lat else "?"
            cost = e.get("cost", 0)
            cost_s = f"${cost:.6f}" if cost else ""
            print(f"  {bid:<10} {prov:<12} {model_s:<32} {status:<10} {time_s:<8} {cost_s:<8}")
        print(f"{'='*75}\n")

    elif args.command in ("stats", "aggregates"):
        agg = get_aggregates()
        if not agg:
            print("No history data yet.")
            return

        print(f"\n{'='*70}")
        print("  Batch Processing Aggregates")
        print(f"  Total batches: {agg.get('total_batches', 0)}")
        print(f"{'='*70}")

        for prov, stats in agg.get("by_provider", {}).items():
            print(f"\n  Provider: {prov}")
            _print_stats(stats)

        by_model = agg.get("by_model", {})
        if by_model:
            print(f"\n{'-'*70}")
            print("  By model")
            for model_key, stats in by_model.items():
                print(f"\n  Model: {model_key}")
                _print_stats(stats)

        print(f"\n{'='*70}\n")

    else:
        parser.print_help()


if __name__ == "__main__":
    cli()