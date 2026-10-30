"""Batch lifecycle management helpers used by the CLI and local console.

This module keeps provider-aware operations separate from the HTTP console:
list/filter batches, inspect their local artifacts, cancel provider work when
supported, and dismiss terminal batches from the active tracker without
deleting results or history.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from batch_common import (
    PROJECT_ROOT, batch_dir, format_age, load_provider_credentials, read_state, resolve_paths, update_state,
)
from providers import get_provider, provider_supports_cancel

TERMINAL_STATES = ("completed", "failed", "cancelled")
ACTIVE_STATES = ("running", "submitted", "cancelling")


def _display_path(path: Path) -> str:
    """Return a privacy-friendly path without embedding the local username."""
    text = str(path)
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        pass
    home = str(Path.home())
    if text.startswith(home + "/"):
        return "~/" + text[len(home) + 1:]
    return text


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None


def list_batches(provider=None, status=None, search=None, limit=None) -> list[dict]:
    """Return tracked batches with optional provider/status/text filters."""
    status_order = {
        "cancelling": 0, "running": 1, "submitted": 2,
        "completed": 3, "failed": 4, "cancelled": 5,
    }
    rows = []
    for batch_id, info in read_state().items():
        if not isinstance(info, dict):
            continue
        row = {
            "batch_id": batch_id,
            "request_id": info.get("custom_id", ""),
            "custom_ids": info.get("custom_ids", []),
            "provider": info.get("provider", ""),
            "model": info.get("model", ""),
            "status": info.get("status", "unknown"),
            "age": format_age(info.get("submitted_at_unix")),
            "submitted_at": info.get("submitted_at", ""),
            "submitted_at_unix": info.get("submitted_at_unix"),
            "completed_at": info.get("completed_at", ""),
            "latency_seconds": info.get("latency_seconds"),
            "request_counts": info.get("request_counts", {}),
            "agent": info.get("agent", ""),
            "error": str(info.get("error", "")),
        }
        if provider and row["provider"] != provider:
            continue
        if status and row["status"] != status:
            continue
        if search:
            needle = search.casefold()
            haystack = " ".join(str(row.get(key, "")) for key in (
                "batch_id", "request_id", "provider", "model", "status", "agent",
            )).casefold()
            if needle not in haystack:
                continue
        rows.append(row)
    rows.sort(key=lambda row: (
        status_order.get(row["status"], 9),
        -(row.get("submitted_at_unix") or 0),
    ))
    if limit is not None:
        rows = rows[:max(1, min(limit, 5000))]
    return rows


def _history_for(batch_id: str) -> dict | None:
    try:
        from batch_history import read_history
        for entry in read_history():
            if entry.get("batch_id") == batch_id:
                return entry
    except Exception:
        pass
    return None


def batch_details(batch_id: str) -> dict:
    """Return the tracked state and local artifacts for one batch."""
    state = read_state()
    info = state.get(batch_id)
    if not isinstance(info, dict):
        raise KeyError(batch_id)
    paths = resolve_paths()
    request_id = info.get("custom_id", "")
    custom_ids = info.get("custom_ids") or ([request_id] if request_id else [])

    tracking_path = Path(paths["requests_dir"]) / f"{request_id}.jsonl"
    result_path = Path(paths["responses_dir"]) / f"{request_id}.result"
    routed_path = Path(paths["responses_dir"]) / f"{request_id}.routed"

    files = [
        {"kind": "tracking", "path": _display_path(tracking_path), "exists": tracking_path.exists()},
        {"kind": "raw results", "path": _display_path(result_path), "exists": result_path.exists()},
        {"kind": "routed results", "path": _display_path(routed_path), "exists": routed_path.exists()},
    ]
    for custom_id in custom_ids:
        done = Path(paths["completed_dir"]) / f"{custom_id}.done"
        escalation = Path(paths["escalations_dir"]) / f"{custom_id}.escalate"
        if done.exists():
            files.append({"kind": "archived result", "path": _display_path(done), "exists": True})
        if escalation.exists():
            files.append({"kind": "escalation", "path": _display_path(escalation), "exists": True})

    result_items = []
    raw_results = _read_json(result_path)
    if isinstance(raw_results, list):
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            content = (item.get("result") or {}).get("content")
            result_items.append({
                "custom_id": item.get("custom_id", ""),
                "status": item.get("status", ""),
                "error": str(item.get("error") or ""),
                "content_preview": str(content or "")[:1200],
            })

    provider_name = info.get("provider", "")
    can_cancel = provider_supports_cancel(provider_name)

    return {
        "batch_id": batch_id,
        "request_id": request_id,
        "custom_ids": custom_ids,
        "provider": provider_name,
        "model": info.get("model", ""),
        "status": info.get("status", "unknown"),
        "age": format_age(info.get("submitted_at_unix")),
        "submitted_at": info.get("submitted_at", ""),
        "completed_at": info.get("completed_at", ""),
        "latency_seconds": info.get("latency_seconds"),
        "request_counts": info.get("request_counts", {}),
        "agent": info.get("agent", ""),
        "error": str(info.get("error", "")),
        "tracking": _read_json(tracking_path),
        "history": _history_for(batch_id),
        "files": files,
        "result_items": result_items,
        "capabilities": {
            "poll": info.get("status") not in TERMINAL_STATES,
            "cancel": can_cancel and info.get("status") not in TERMINAL_STATES,
            "retry": False,
            "archive": info.get("status") in TERMINAL_STATES,
        },
    }


def cancel_batch(batch_id: str) -> dict:
    """Ask the provider to cancel a batch and mark it as cancelling locally."""
    load_provider_credentials()
    state = read_state()
    info = state.get(batch_id)
    if not isinstance(info, dict):
        raise KeyError(batch_id)
    if info.get("status") in TERMINAL_STATES:
        raise ValueError("This batch has already finished")
    provider_name = info.get("provider", "")
    if not provider_supports_cancel(provider_name):
        raise ValueError(f"{provider_name} does not support cancelling batches")
    try:
        provider = get_provider(provider_name)
    except Exception as exc:
        raise RuntimeError(f"Cannot load provider {provider_name}: {exc}") from exc
    if not provider.cancel_batch(batch_id):
        raise RuntimeError(f"{provider_name} did not confirm cancellation")

    def mark_cancelling(current):
        if batch_id in current:
            current[batch_id]["status"] = "cancelling"
            current[batch_id]["cancel_requested_at_unix"] = time.time()

    update_state(resolve_paths()["state_file"], mark_cancelling)
    return {"batch_id": batch_id, "status": "cancelling", "provider": provider_name}


def archive_batch(batch_id: str) -> dict:
    """Dismiss a terminal batch from active tracking while preserving artifacts."""
    state = read_state()
    info = state.get(batch_id)
    if not isinstance(info, dict):
        raise KeyError(batch_id)
    if info.get("status") not in TERMINAL_STATES:
        raise ValueError("Only a finished batch can be dismissed")
    archived = dict(info)
    archived["batch_id"] = batch_id
    archived["archived_at_unix"] = time.time()

    def remove(current):
        current.pop(batch_id, None)

    update_state(resolve_paths()["state_file"], remove)
    archive_dir = batch_dir() / "history"
    archive_dir.mkdir(parents=True, exist_ok=True)
    with (archive_dir / "archived-batches.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(archived, default=str) + "\n")
    return {"batch_id": batch_id, "archived": True}
