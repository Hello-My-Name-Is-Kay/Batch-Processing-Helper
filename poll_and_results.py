#!/usr/bin/env python3
"""
Poll a batch until completion and retrieve results.

Usage:
  python3 poll_and_results.py <batch_id> [--interval SECONDS] [--max-attempts N]
"""

import sys
import json
import time
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from providers import get_provider

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Poll and retrieve batch results")
    parser.add_argument("batch_id", help="Batch ID to poll")
    parser.add_argument("--interval", type=int, default=15, help="Poll interval in seconds")
    parser.add_argument("--max-attempts", type=int, default=120, help="Maximum poll attempts")
    parser.add_argument("--provider", default="openrouter", help="Provider name")
    args = parser.parse_args()

    provider = get_provider(args.provider)
    batch_id = args.batch_id

    print(f"Polling batch {batch_id} every {args.interval}s (max {args.max_attempts} attempts)")

    for attempt in range(args.max_attempts):
        status = provider.retrieve_batch(batch_id)
        raw = status.get("raw_status", "unknown")
        counts = status.get("request_counts", {})
        completed = counts.get("completed", 0)
        total = counts.get("total", "?")

        print(f"[{attempt+1:3d}] {raw:15s}  {completed}/{total}  ", end="")

        if raw == "completed":
            print("\n✅ Batch completed!")
            results = provider.get_results(batch_id)
            print(f"\nRetrieved {len(results)} result(s):")
            for i, r in enumerate(results):
                print(f"\n--- Result {i+1}: {r.custom_id} ---")
                print(f"  Status: {r.status}")
                if r.content:
                    print(f"  Content: {r.content[:500]}")
                if r.error:
                    print(f"  Error: {r.error}")
                if r.usage:
                    print(f"  Usage: {json.dumps(r.usage)}")
            return results

        if raw in ("failed", "cancelled", "expired"):
            print(f"\n❌ Batch ended with status: {raw}")
            if status.get("errors"):
                print(f"  Errors: {json.dumps(status['errors'], indent=2)}")
            return None

        if completed > 0:
            print()
        else:
            print()

        time.sleep(args.interval)

    print(f"\n⚠️  Batch still processing after {args.max_attempts * args.interval}s")
    return None

if __name__ == "__main__":
    results = main()
    if results is None:
        sys.exit(1)