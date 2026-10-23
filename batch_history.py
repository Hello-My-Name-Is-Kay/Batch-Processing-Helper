#!/usr/bin/env python3
"""
Batch processing history tracker.

Logs every completed batch to a persistent history file, keyed by provider
and model. Supports querying, aggregating, and analyzing historical data.

History directory structure:
  .batch-data/history/
    history.jsonl          — Append-only log of every batch completion
    history.db.json        — Pre-computed aggregates (refreshed on write)
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from collections import defaultdict


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _get_history_dir() -> Path:
    """Get the history directory (under .batch-data)."""
    batch_dir = Path(os.environ.get("BATCH_DIR", 
                    Path(__file__).parent / ".batch-data"))
    hist_dir = batch_dir / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    return hist_dir


def _history_file() -> Path:
    return _get_history_dir() / "history.jsonl"


def _aggregates_file() -> Path:
    return _get_history_dir() / "history.db.json"


# ---------------------------------------------------------------------------
# Data model for a history entry
# ---------------------------------------------------------------------------

HISTORY_ENTRY_SCHEMA = {
    "batch_id":           str,   # Provider's batch ID
    "provider":           str,   # e.g. "openrouter", "anthropic"
    "model":              str,   # Full model name including :batch suffix
    "raw_model":          str,   # Model name as returned by provider
    "status":             str,   # "completed", "failed"
    "created_at":         float, # Unix timestamp of batch creation
    "finalized_at":       float, # Unix timestamp of batch completion
    "latency_seconds":    float, # finalized_at - created_at
    "total_requests":     int,   # Number of requests in batch
    "completed_requests": int,   # Number of successfully completed
    "failed_requests":    int,   # Number of failed requests
    "prompt_tokens":      Optional[int],
    "completion_tokens":  Optional[int],
    "total_tokens":       Optional[int],
    "cost":               Optional[float],  # Provider cost in USD
    "submitted_at_unix":  Optional[float],  # When we submitted
    "pipeline_latency":   Optional[float],  # Time from submit to completion
    "provider_backend":   Optional[str],    # e.g. "Sail Research" for OpenRouter
    "agent":              Optional[str],    # Agent/source that submitted (R3)
    "custom_ids":         Optional[list],   # All request IDs in this batch (R2)
}


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
    with open(hist_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    # Update aggregates
    _update_aggregates()


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
        "median": round(vals[n // 2], precision),
        "sum": round(sum(vals), precision),
    }


def _update_aggregates() -> None:
    """Recompute and cache per-provider + per-model aggregates."""
    entries = read_history()
    if not entries:
        return

    # Per-provider
    by_provider = defaultdict(list)
    # Per-model
    by_model = defaultdict(list)

    for e in entries:
        prov = e.get("provider", "unknown")
        by_provider[prov].append(e)
        model_key = f"{prov}/{e.get('raw_model', e.get('model', 'unknown'))}"
        by_model[model_key].append(e)

    aggregates = {
        "last_updated": time.time(),
        "total_batches": len(entries),
        "by_provider": {},
        "by_model": {},
    }

    for prov, items in by_provider.items():
        latencies = [e["latency_seconds"] for e in items if e.get("latency_seconds")]
        costs = [e["cost"] for e in items if e.get("cost")]
        tokens = [e["total_tokens"] for e in items if e.get("total_tokens")]
        pipeline = [e["pipeline_latency"] for e in items if e.get("pipeline_latency")]

        stats = {"batches": len(items)}
        if latencies:
            stats["latency_seconds"] = _stats(latencies)
        if pipeline:
            stats["pipeline_latency_seconds"] = _stats(pipeline)
        if costs:
            stats["cost_usd"] = _stats(costs)
        if tokens:
            stats["tokens"] = _stats(tokens)

        aggregates["by_provider"][prov] = stats

    for model_key, items in by_model.items():
        latencies = [e["latency_seconds"] for e in items if e.get("latency_seconds")]
        costs = [e["cost"] for e in items if e.get("cost")]
        tokens = [e["total_tokens"] for e in items if e.get("total_tokens")]

        stats = {"batches": len(items)}
        if latencies:
            stats["latency_seconds"] = _stats(latencies)
        if costs:
            stats["cost_usd"] = _stats(costs)
        if tokens:
            stats["tokens"] = _stats(tokens)

        aggregates["by_model"][model_key] = stats

    agg_file = _aggregates_file()
    with open(agg_file, "w", encoding="utf-8") as f:
        json.dump(aggregates, f, indent=2)


def get_aggregates() -> dict:
    """Return cached aggregates (or recompute if missing)."""
    agg_file = _aggregates_file()
    if agg_file.exists():
        with open(agg_file, "r", encoding="utf-8") as f:
            return json.load(f)
    _update_aggregates()
    if agg_file.exists():
        with open(agg_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Batch processing history and metrics")
    sub = parser.add_subparsers(dest="command")

    # log
    log_p = sub.add_parser("log", help="Log a batch completion (called by poll.py)")
    log_p.add_argument("--batch-id", required=True)
    log_p.add_argument("--provider", required=True)
    log_p.add_argument("--model", required=True)
    log_p.add_argument("--raw-model", default="")
    log_p.add_argument("--status", default="completed")
    log_p.add_argument("--created-at", type=float, required=True)
    log_p.add_argument("--finalized-at", type=float, required=True)
    log_p.add_argument("--total-requests", type=int, required=True)
    log_p.add_argument("--completed-requests", type=int, required=True)
    log_p.add_argument("--failed-requests", type=int, default=0)
    log_p.add_argument("--prompt-tokens", type=int, default=None)
    log_p.add_argument("--completion-tokens", type=int, default=None)
    log_p.add_argument("--total-tokens", type=int, default=None)
    log_p.add_argument("--cost", type=float, default=None)
    log_p.add_argument("--submitted-at", type=float, default=None)
    log_p.add_argument("--provider-backend", default=None)

    # list
    list_p = sub.add_parser("list", help="List recent history")
    list_p.add_argument("--limit", type=int, default=10)
    list_p.add_argument("--provider", default=None)
    list_p.add_argument("--model", default=None)

    # stats
    stats_p = sub.add_parser("stats", help="Show aggregates per provider/model")

    # show (aliases)
    sub.add_parser("show", help="Alias for list --limit 10")
    sub.add_parser("aggregates", help="Alias for stats")

    args = parser.parse_args()

    if args.command == "log":
        entry = make_history_entry(
            batch_id=args.batch_id,
            provider=args.provider,
            model=args.model,
            raw_model=args.raw_model or args.model,
            status=args.status,
            created_at=args.created_at,
            finalized_at=args.finalized_at,
            total_requests=args.total_requests,
            completed_requests=args.completed_requests,
            failed_requests=args.failed_requests,
            prompt_tokens=args.prompt_tokens,
            completion_tokens=args.completion_tokens,
            total_tokens=args.total_tokens,
            cost=args.cost,
            submitted_at_unix=args.submitted_at,
            provider_backend=args.provider_backend,
        )
        log_completion(entry)
        print(json.dumps(entry, indent=2))

    elif args.command in ("list", "show"):
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
        print(f"  Batch Processing Aggregates")
        print(f"  Total batches: {agg.get('total_batches', 0)}")
        print(f"{'='*70}")

        for prov, stats in agg.get("by_provider", {}).items():
            print(f"\n  Provider: {prov}")
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

        print(f"\n{'='*70}\n")

    else:
        parser.print_help()


if __name__ == "__main__":
    cli()