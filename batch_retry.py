#!/usr/bin/env python3
"""Retry logic for failed batches with exponential backoff."""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional


class RetryQueue:
    """Manage retry queue for failed batches."""

    QUEUE_FILE = ".batch-data/retry-queue.jsonl"

    # Retry configuration
    BACKOFF_INITIAL = 1  # 1 second
    BACKOFF_FACTOR = 2   # exponential: 1s, 2s, 4s, 8s, ...
    BACKOFF_MAX = 300    # 5 minute max delay
    MAX_RETRIES = 3      # Give up after 3 retries

    def __init__(self, queue_file: Optional[str] = None):
        """Initialize retry queue.

        Args:
            queue_file: Path to retry queue JSONL file
        """
        self.queue_file = queue_file or self.QUEUE_FILE
        Path(self.queue_file).parent.mkdir(parents=True, exist_ok=True)
        if not Path(self.queue_file).exists():
            Path(self.queue_file).touch()

    def add_batch(self, batch_id: str, provider: str, reason: str) -> None:
        """Add a failed batch to the retry queue.

        Args:
            batch_id: Failed batch ID
            provider: Provider name (groq, anthropic, etc.)
            reason: Reason for failure
        """
        entry = {
            "batch_id": batch_id,
            "provider": provider,
            "reason": reason,
            "attempt": 1,
            "created_at": datetime.utcnow().isoformat(),
            "next_retry_at": self._calculate_next_retry(attempt=1),
            "status": "pending"
        }

        with open(self.queue_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def get_ready_batches(self) -> list[dict]:
        """Get batches ready to retry (delay expired).

        Returns:
            List of batch entries ready for retry
        """
        ready = []
        now = datetime.utcnow()

        if not Path(self.queue_file).exists():
            return ready

        with open(self.queue_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)

                # Skip if already retried or exceeded max retries
                if entry["status"] == "done" or entry["attempt"] > self.MAX_RETRIES:
                    continue

                retry_at = datetime.fromisoformat(entry["next_retry_at"])
                if now >= retry_at:
                    ready.append(entry)

        return ready

    def mark_retried(self, batch_id: str, success: bool = True) -> None:
        """Mark a batch as retried and schedule next retry if needed.

        Args:
            batch_id: Batch that was retried
            success: Whether the retry succeeded
        """
        entries = []

        with open(self.queue_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)

                if entry["batch_id"] == batch_id:
                    if success:
                        entry["status"] = "done"
                    else:
                        entry["attempt"] += 1
                        if entry["attempt"] <= self.MAX_RETRIES:
                            entry["next_retry_at"] = self._calculate_next_retry(entry["attempt"])
                            entry["status"] = "pending"
                        else:
                            entry["status"] = "exhausted"

                entries.append(entry)

        # Rewrite queue file
        with open(self.queue_file, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

    def get_stats(self) -> dict:
        """Get retry queue statistics.

        Returns:
            Dict with pending, completed, exhausted counts
        """
        stats = {"pending": 0, "done": 0, "exhausted": 0, "total": 0}

        if not Path(self.queue_file).exists():
            return stats

        with open(self.queue_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                stats[entry.get("status", "pending")] += 1
                stats["total"] += 1

        return stats

    @staticmethod
    def _calculate_next_retry(attempt: int) -> str:
        """Calculate when to retry based on attempt number.

        Args:
            attempt: Which attempt this is (1, 2, 3, ...)

        Returns:
            ISO format datetime string for next retry
        """
        delay_seconds = min(
            RetryQueue.BACKOFF_INITIAL * (RetryQueue.BACKOFF_FACTOR ** (attempt - 1)),
            RetryQueue.BACKOFF_MAX
        )
        next_retry = datetime.utcnow() + timedelta(seconds=delay_seconds)
        return next_retry.isoformat()


def main():
    """CLI for retry queue management."""
    if len(sys.argv) < 2:
        print("Usage: python batch_retry.py [status|add|ready|mark-done|mark-failed]")
        sys.exit(1)

    queue = RetryQueue()
    command = sys.argv[1]

    if command == "status":
        stats = queue.get_stats()
        print("Retry Queue Status:")
        print(f"  Pending: {stats['pending']}")
        print(f"  Completed: {stats['done']}")
        print(f"  Exhausted: {stats['exhausted']}")
        print(f"  Total: {stats['total']}")

    elif command == "add":
        if len(sys.argv) < 4:
            print("Usage: python batch_retry.py add <batch_id> <provider> [reason]")
            sys.exit(1)
        batch_id = sys.argv[2]
        provider = sys.argv[3]
        reason = sys.argv[4] if len(sys.argv) > 4 else "Batch failed"
        queue.add_batch(batch_id, provider, reason)
        print(f"Added {batch_id} to retry queue")

    elif command == "ready":
        ready = queue.get_ready_batches()
        if ready:
            print(f"Batches ready for retry ({len(ready)}):")
            for batch in ready:
                print(f"  - {batch['batch_id']} ({batch['provider']}) - Attempt {batch['attempt']}")
        else:
            print("No batches ready for retry")

    elif command == "mark-done":
        if len(sys.argv) < 3:
            print("Usage: python batch_retry.py mark-done <batch_id>")
            sys.exit(1)
        queue.mark_retried(sys.argv[2], success=True)
        print(f"Marked {sys.argv[2]} as done")

    elif command == "mark-failed":
        if len(sys.argv) < 3:
            print("Usage: python batch_retry.py mark-failed <batch_id>")
            sys.exit(1)
        queue.mark_retried(sys.argv[2], success=False)
        print(f"Marked {sys.argv[2]} for retry")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
