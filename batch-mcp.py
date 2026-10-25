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

from __future__ import annotations

import sys
import os
import json
import importlib.util
from pathlib import Path
from datetime import datetime

# ── Ensure project root on path ────────────────────────────────────
_HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(_HERE))

from batch_common import (
    format_age, format_duration, pipeline_counts, read_escalations, read_state,
)
from batch_history import read_history, get_aggregates


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
        # The submit script has a hyphen in its name, so it cannot be imported
        # with a plain "import"; load it from its file.
        spec = importlib.util.spec_from_file_location("batch_submit", _HERE / "batch-submit.py")
        submit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(submit)

        result = submit.submit_request(
            user_message=args["task"],
            system_message=None,
            provider_name=args.get("provider"),
            model=args.get("model"),
        )

        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"status": "submitted", **result}, indent=2),
            }]
        }

    def _status(self) -> dict:
        state = read_state()
        counts = pipeline_counts()

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
                    "age": format_age(info.get("submitted_at_unix")),
                    "latency": format_duration(info.get("latency_seconds")),
                })

        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "batches": {"total": counts["batches"], "running": counts["running"],
                                "completed": counts["completed"], "failed": counts["failed"],
                                "cancelled": counts["cancelled"]},
                    "results": {"awaiting_routing": counts["awaiting_routing"],
                                "archived": counts["archived"],
                                "escalations": counts["escalations"]},
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
                "latency": format_duration(e.get("latency_seconds")),
                "tokens": e.get("total_tokens"),
                "cost": f"${e.get('cost', 0):.6f}" if e.get("cost") else "—",
                "backend": e.get("provider_backend", ""),
            })

        return {"content": [{"type": "text", "text": json.dumps(rows, indent=2)}]}

    def _stats(self) -> dict:
        agg = get_aggregates()
        return {"content": [{"type": "text", "text": json.dumps(agg, indent=2, default=str)}]}

    def _escalations(self) -> dict:
        entries = []
        for row in read_escalations(20):
            if row.get("error"):
                entries.append({"file": row["file"], "error": row["error"]})
                continue
            entries.append({
                "file": row["file"],
                "request_id": row["request_id"],
                "classification": row["classification"],
                "reason": row["reason"] or row["summary"],
                "content_preview": " ".join(row["response"].split())[:80],
            })

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

        # Notifications (no id) never get a reply; any other unknown request
        # must, or the client waits forever.
        if req_id is None:
            return None
        return {
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


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