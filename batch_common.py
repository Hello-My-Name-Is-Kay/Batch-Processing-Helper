"""Shared helpers: where pipeline data lives and how to read and write it safely.

Every script resolves its folders through resolve_paths(), so they work the
same whether they run from batch.sh (which sources batch-config.sh), from cron,
from an MCP host, or directly from a shell with no environment set up.

The state file (.batch-state) is shared by submit, poll and the viewers. Writers
go through update_state(), which holds a lock for the whole read-modify-write
and replaces the file atomically, so two processes cannot lose each other's
changes and readers never see a half-written file.
"""

import fcntl
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()

# What Anthropic accepts for a custom_id; also keeps ids safe to use as file names.
_CUSTOM_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def batch_dir() -> Path:
    """Base directory for pipeline data (BATCH_DIR, default: <project>/.batch-data)."""
    return Path(os.environ.get("BATCH_DIR") or PROJECT_ROOT / ".batch-data")


def resolve_paths() -> dict:
    """Return the pipeline folders and state file as strings.

    Each location can be overridden by its own BATCH_*_DIR variable; anything
    unset falls back to a folder under batch_dir().
    """
    base = batch_dir()

    def pick(env_name: str, default: str) -> str:
        return os.environ.get(env_name) or str(base / default)

    return {
        "requests_dir": pick("BATCH_REQUESTS_DIR", "requests"),
        "responses_dir": pick("BATCH_RESPONSES_DIR", "responses"),
        "completed_dir": pick("BATCH_COMPLETED_DIR", "completed"),
        "escalations_dir": pick("BATCH_ESCALATIONS_DIR", "escalations"),
        "logs_dir": pick("BATCH_LOGS_DIR", "logs"),
        "state_file": pick("BATCH_STATE", ".batch-state"),
    }


def validate_custom_id(value: str) -> str:
    """Return value if it is a safe request id (letters, digits, - and _, up to 64), else raise."""
    if not isinstance(value, str) or not _CUSTOM_ID.match(value):
        raise ValueError(
            f"Invalid request id {value!r}: use 1-64 letters, digits, '-' or '_'."
        )
    return value


# ---------------------------------------------------------------------------
# JSON files
# ---------------------------------------------------------------------------

def write_json_atomic(path, data, **dump_kwargs) -> None:
    """Write JSON to path so readers never see a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, **dump_kwargs)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------

@contextmanager
def state_lock(state_file):
    """Exclusive lock on the state file, shared by every process that writes it."""
    state_file = Path(state_file)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{state_file}.lock", "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load_state(state_file, repair: bool = False) -> dict:
    """Read the state file ({} if it is missing).

    A file that is not a JSON object is treated as empty. With repair=True it
    is first moved aside to <name>.corrupt-<time>, so a later write does not
    destroy it; read-only callers leave it where it is.
    """
    path = Path(state_file)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data
    except ValueError as e:
        if repair:
            stamp = int(time.time())
            backup = path.with_name(f"{path.name}.corrupt-{stamp}")
            extra = 0
            while backup.exists():          # never overwrite an earlier backup
                extra += 1
                backup = path.with_name(f"{path.name}.corrupt-{stamp}-{extra}")
            os.replace(path, backup)
            print(f"Warning: {path} is not valid ({e}); moved to {backup}", file=sys.stderr)
        return {}


def update_state(state_file, mutate) -> dict:
    """Apply mutate(state) to the state under the lock and save it atomically."""
    with state_lock(state_file):
        state = load_state(state_file, repair=True)
        mutate(state)
        write_json_atomic(state_file, state, indent=2)
        return state


# ---------------------------------------------------------------------------
# Views used by status, the TUI and the MCP server
# ---------------------------------------------------------------------------

def read_state() -> dict:
    """The current state file, read-only (see load_state)."""
    return load_state(resolve_paths()["state_file"])


def format_duration(seconds) -> str:
    """Readable duration: 45s, 3.2m, 1.5h. "—" for None or zero."""
    if not seconds:
        return "—"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def format_age(unix_ts) -> str:
    """How long ago a unix timestamp was, as a readable duration ("—" if unknown)."""
    if not unix_ts:
        return "—"
    return format_duration(time.time() - unix_ts)


def _count_files(folder, pattern: str) -> int:
    folder = Path(folder)
    return len(list(folder.glob(pattern))) if folder.exists() else 0


def pipeline_counts() -> dict:
    """Counts that say where work is: with the provider, collected, routed or escalated."""
    paths = resolve_paths()
    by_status = Counter(
        info.get("status", "unknown") for info in load_state(paths["state_file"]).values()
    )
    return {
        "batches": sum(by_status.values()),
        # Batches still at the provider
        "running": by_status["running"] + by_status["submitted"],
        # Batches whose results were downloaded
        "completed": by_status["completed"],
        "failed": by_status["failed"],
        "cancelled": by_status["cancelled"],
        # Downloaded results the router has not classified yet
        "awaiting_routing": _count_files(paths["responses_dir"], "*.result"),
        # Router outcomes
        "escalations": _count_files(paths["escalations_dir"], "*.escalate"),
        "archived": _count_files(paths["completed_dir"], "*.done"),
    }


def read_escalations(limit: int = 50) -> list:
    """Escalated items, newest first, flattened for display.

    Each row has: file, request_id, provider, classification, reason, summary,
    response and escalated_at (or an "error" if the file could not be read).
    """
    folder = Path(resolve_paths()["escalations_dir"])
    if not folder.exists():
        return []

    files = sorted(folder.glob("*.escalate"), key=lambda p: p.stat().st_mtime, reverse=True)
    rows = []
    for path in files[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows.append({"file": path.name, "request_id": path.stem, "error": "could not read file"})
            continue
        verdict = data.get("classification")
        if not isinstance(verdict, dict):
            verdict = {}
        rows.append({
            "file": path.name,
            "request_id": data.get("request_id", path.stem),
            "provider": data.get("provider", ""),
            "classification": verdict.get("classification", ""),
            "reason": verdict.get("reason", ""),
            "summary": verdict.get("summary", ""),
            "response": data.get("response") or "",
            "escalated_at": data.get("escalated_at", ""),
        })
    return rows
