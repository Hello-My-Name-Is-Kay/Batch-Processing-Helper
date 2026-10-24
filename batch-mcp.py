#!/usr/bin/env python3
"""
batch-mcp.py — MCP server for the Batch Processing Pipeline.

Exposes batch operations as MCP tools consumable by Claude Desktop, Pi,
Cursor, VS Code, and any MCP-compatible host.

Usage:
  # Run directly (stdio transport, for MCP hosts)
  python3 batch-mcp.py

  # Test from shell
  echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 batch-mcp.py

  # Add to Claude Desktop mcp.json
  {
    "mcpServers": {
      "batch-processing": {
        "command": "python3",
        "args": ["/path/to/batch-mcp.py"],
        "env": {
          "OPENROUTER_API_KEY": "${OPENROUTER_API_KEY}",
          "BATCH_PROVIDER": "openrouter"
        }
      }
    }
  }
"""

import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Any

# ── Ensure project root on path ────────────────────────────────────
_HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(_HERE))

# ── Project imports (best-effort) ──────────────────────────────────
try:
    from providers import get_provider, list_providers, BatchStatus
except Exception as e:
    get_provider = None
    list_providers = lambda: []
    BatchStatus = None

try:
    from batch_history import read_history, get_aggregates
except Exception:
    read_history = lambda: []
    get_aggregates = lambda: {}


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _batch_data_dir() -> Path:
    return Path(os.environ.get("BATCH_DIR", _HERE / ".batch-data"))


def _load_state() -> dict:
    sf = _batch_data_dir() / ".batch-state"
    if sf.exists():
        try:
            return json.loads(sf.read_text())
        except Exception:
            return {}
    return {}


def _count_files(subdir: str, pattern: str) -> int:
    d = _batch_data_dir() / subdir
    return len(list(d.glob(pattern))) if d.exists() else 0


def _format_dur(seconds: float | None) -> str:
    if not seconds:
        return "—"
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    else:
        return f"{seconds / 3600:.1f}h"


def _age(unix_ts: float | None) -> str:
    if not unix_ts:
        return "—"
    return _format_dur(time.time() - unix_ts)


# ═══════════════════════════════════════════════════════════════════
#  MCP Server (stdio transport via JSON-RPC)
# ═══════════════════════════════════════════════════════════════════

class BatchMcpServer:
    """Minimal stdio MCP server exposing batch pipeline tools."""

    def __init__(self):
        self.request_id = 0

    # ── Tool definitions ──────────────────────────────────────────

    @property
    def tools(self) -> list[dict]:
        return [
            {
                "name": "batch_send",
                "description": "Submit a batch request to the LLM batch pipeline",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "Task description to submit"},
                        "provider": {"type": "string", "description": "Provider (anthropic/openrouter/groq)", "default": None},
                        "model": {"type": "string", "description": "Model name", "default": None},
                    },
                    "required": ["task"],
                },
            },
            {
                "name": "batch_status",
                "description": "Get current pipeline status: batch counts, recent activity",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "batch_history",
                "description": "View recent batch completion history with latency, cost, tokens",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Number of entries (default 10)", "default": 10},
                    },
                },
            },
            {
                "name": "batch_stats",
                "description": "View aggregate statistics per provider and per model",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "batch_escalations",
                "description": "List items awaiting human review",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "batch_poll",
                "description": "Trigger a poll cycle to check for completed batches",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    # ── Tool implementations ──────────────────────────────────────

    def handle_tool_call(self, name: str, args: dict) -> dict:
        try:
            if name == "batch_send":
                return self._send(args)
            elif name == "batch_status":
                return self._status()
            elif name == "batch_history":
                return self._history(args.get("limit", 10))
            elif name == "batch_stats":
                return self._stats()
            elif name == "batch_escalations":
                return self._escalations()
            elif name == "batch_poll":
                return self._poll()
            else:
                return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": f"Error: {e}"}]}

    def _send(self, args: dict) -> dict:
        from batch_submit import submit_batch_request

        task = args["task"]
        provider = args.get("provider")
        model = args.get("model")

        batch_id, req_id = submit_batch_request(
            user_message=task,
            system_message=None,
            provider_name=provider,
            model=model,
        )

        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "status": "submitted",
                    "batch_id": batch_id,
                    "request_id": req_id,
                    "provider": provider or os.environ.get("BATCH_PROVIDER", "anthropic"),
                    "model": model or os.environ.get("BATCH_MODEL", "default"),
                }, indent=2),
            }]
        }

    def _status(self) -> dict:
        state = _load_state()
        n_total = len(state)
        n_running = sum(1 for v in state.values() if v.get("status") == "running")
        n_completed = sum(1 for v in state.values() if v.get("status") == "completed")
        n_failed = sum(1 for v in state.values() if v.get("status") == "failed")
        n_queued = _count_files("requests", "*.jsonl")
        n_esc = _count_files("escalations", "*.escalate")
        n_done = _count_files("completed", "*.done")

        providers = sorted(set(v.get("provider", "?") for v in state.values()))

        # Recent activity
        recent = []
        if state:
            items = sorted(state.items(),
                          key=lambda x: -(x[1].get("submitted_at_unix", 0) or 0))[:5]
            for bid, info in items:
                recent.append({
                    "batch_id": bid[:20],
                    "status": info.get("status"),
                    "provider": info.get("provider"),
                    "age": _age(info.get("submitted_at_unix")),
                    "latency": _format_dur(info.get("latency_seconds")),
                })

        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "batches": {"total": n_total, "running": n_running,
                                "completed": n_completed, "failed": n_failed},
                    "files": {"queued": n_queued, "completed": n_done,
                              "escalations": n_esc},
                    "providers": providers,
                    "recent": recent,
                }, indent=2),
            }]
        }

    def _history(self, limit: int = 10) -> dict:
        entries = read_history()[:limit]
        if not entries:
            return {"content": [{"type": "text", "text": "No history entries yet."}]}

        rows = []
        for e in entries:
            rows.append({
                "time": datetime.fromtimestamp(e.get("finalized_at", 0)).strftime("%m/%d %H:%M") if e.get("finalized_at") else "?",
                "provider": e.get("provider"),
                "model": e.get("raw_model", e.get("model", "")),
                "latency": _format_dur(e.get("latency_seconds")),
                "tokens": e.get("total_tokens"),
                "cost": f"${e.get('cost', 0):.6f}" if e.get("cost") else "—",
                "backend": e.get("provider_backend", ""),
            })

        return {"content": [{"type": "text", "text": json.dumps(rows, indent=2)}]}

    def _stats(self) -> dict:
        agg = get_aggregates()
        return {"content": [{"type": "text", "text": json.dumps(agg, indent=2, default=str)}]}

    def _escalations(self) -> dict:
        esc_dir = _batch_data_dir() / "escalations"
        if not esc_dir.exists():
            return {"content": [{"type": "text", "text": "No escalations."}]}

        entries = []
        for f in sorted(esc_dir.glob("*.escalate"), reverse=True)[:20]:
            try:
                data = json.loads(f.read_text())
                entries.append({
                    "file": f.name,
                    "content_preview": (data.get("content") or data.get("result", {}).get("content") or "")[:80],
                    "reason": data.get("reason") or data.get("classification") or "",
                })
            except Exception:
                entries.append({"file": f.name, "error": "parse failed"})

        if not entries:
            return {"content": [{"type": "text", "text": "No escalations."}]}

        return {"content": [{"type": "text", "text": json.dumps(entries, indent=2)}]}

    def _poll(self) -> dict:
        """Run a poll cycle via batch-poll.py."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(_HERE / "batch-poll.py")],
            capture_output=True, text=True, timeout=60,
            env=os.environ,
        )
        try:
            data = json.loads(result.stdout.strip())
        except Exception:
            data = {"completed": 0, "stderr": result.stderr[:200]}

        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "poll_result": data,
                    "stderr": result.stderr.strip()[-300:] if result.stderr else "",
                }, indent=2),
            }]
        }

    # ── JSON-RPC handler ──────────────────────────────────────────

    def handle_request(self, req: dict) -> dict | None:
        method = req.get("method")
        req_id = req.get("id")
        params = req.get("params", {})

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.tools}}

        elif method == "tools/call":
            result = self.handle_tool_call(params.get("name", ""), params.get("arguments", {}))
            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        elif method == "initialize":
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "batch-processing-mcp", "version": "1.0.0"},
                },
            }

        elif method == "notifications/initialized":
            return None

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        return None


# ═══════════════════════════════════════════════════════════════════
#  Main — stdio JSON-RPC loop
# ═══════════════════════════════════════════════════════════════════

def main():
    server = BatchMcpServer()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        resp = server.handle_request(req)
        if resp is not None:
            print(json.dumps(resp), flush=True)


if __name__ == "__main__":
    main()