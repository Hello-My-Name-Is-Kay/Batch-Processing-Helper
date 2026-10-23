#!/usr/bin/env python3
"""
batch-tui.py — Interactive TUI for the Batch Processing Pipeline.

A Textual-based terminal UI with mouse and keyboard navigation for:
  • Dashboard — pipeline overview, counts, recent completions
  • Batches   — all batch state entries with status/age
  • History   — historical completions with per-provider aggregates
  • Escalations — items needing human review
  • Logs      — recent poll/router log tail

Keyboard:  1-5 screens, r refresh, q quit, ↑↓ scroll, / search
Mouse:     Click tabs, scroll tables, click items for details
"""

import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime

# ── Textual imports ────────────────────────────────────────────────
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import (
    Header, Footer, Static, DataTable, RichLog, Label,
    TabbedContent, TabPane, Button, Input, Rule
)
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.binding import Binding
from rich.text import Text

# ── Ensure project root on path ────────────────────────────────────
_HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(_HERE))

# Import project modules (best-effort)
try:
    from providers import get_provider, list_providers
    _PROVIDERS_OK = True
except Exception:
    _PROVIDERS_OK = False

try:
    from batch_history import read_history, get_aggregates
    _HISTORY_OK = True
except Exception:
    _HISTORY_OK = False


# ═══════════════════════════════════════════════════════════════════
#  Data helpers
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


def _read_log(log_name: str, lines: int = 30) -> str:
    log_file = _batch_data_dir() / "logs" / log_name
    if log_file.exists():
        try:
            content = log_file.read_text()
            return "\n".join(content.strip().split("\n")[-lines:])
        except Exception:
            return f"(error reading {log_name})"
    return f"(no {log_name} yet)"


def _get_escalations() -> list[dict]:
    esc_dir = _batch_data_dir() / "escalations"
    if not esc_dir.exists():
        return []
    entries = []
    for f in sorted(esc_dir.glob("*.escalate"), reverse=True)[:50]:
        try:
            entries.append(json.loads(f.read_text()))
        except Exception:
            entries.append({"file": f.name, "error": "parse failed"})
    return entries


def _format_duration(seconds: float) -> str:
    if seconds is None or seconds == 0:
        return "—"
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    else:
        return f"{seconds / 3600:.1f}h"


def _age_from_unix(unix_ts: Optional[float]) -> str:
    if not unix_ts:
        return "—"
    diff = time.time() - unix_ts
    return _format_duration(diff)


# ═══════════════════════════════════════════════════════════════════
#  Screens
# ═══════════════════════════════════════════════════════════════════

class DashboardScreen(Screen):
    """Main dashboard — counts, recent history, quick stats."""

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="dash-scroll"):
            yield Static(id="dash-title", markup=True)
            yield Rule()
            yield Static(id="dash-counts", markup=True)
            yield Rule()
            yield Static(id="dash-history", markup=True)
            yield Rule()
            yield Static(id="dash-aggregates", markup=True)

    def on_screen_mounted(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        state = _load_state()

        # ── Counts ──
        n_total = len(state)
        n_running = sum(1 for v in state.values() if v.get("status") == "running")
        n_completed = sum(1 for v in state.values() if v.get("status") == "completed")
        n_failed = sum(1 for v in state.values() if v.get("status") == "failed")
        n_queued_req = _count_files("requests", "*.jsonl")
        n_esc = _count_files("escalations", "*.escalate")
        n_done = _count_files("completed", "*.done")

        providers = set(v.get("provider", "?") for v in state.values())
        prov_str = ", ".join(sorted(providers)) if providers else "none"

        title = Text.assemble(
            ("╔═══════════════════════════════════════════════════════════╗\n", "bold yellow"),
            ("║    BATCH PIPELINE TUI                                    ║\n", "bold yellow"),
            ("╚═══════════════════════════════════════════════════════════╝", "bold yellow"),
        )

        counts = Text.assemble(
            ("\n", ""),
            ("Pipeline Status", "bold white underline"),
            ("\n\n", ""),
            (f"  Batches:     {n_total:3d} total  ", ""),
            (f"{n_running:3d} running  ", "cyan"),
            (f"{n_completed:3d} completed  ", "green"),
            (f"{n_failed:3d} failed\n", "red"),
            (f"  Files:       {n_queued_req:3d} queued  ", ""),
            (f"{n_done:3d} completed  ", "green"),
            (f"{n_esc:3d} escalated\n", "yellow"),
            (f"  Providers:   {prov_str}\n", "white"),
            (f"  History:     {_count_files('history', '*.jsonl')} entries", "blue"),
            ("\n", ""),
        )

        # ── Recent history ──
        hist_lines = [("\nRecent Completions\n", "bold white underline"), ("\n", "")]
        if _HISTORY_OK:
            entries = read_history()[:8]
            if entries:
                for e in entries:
                    model_s = e.get("raw_model", e.get("model", "?"))[:35]
                    lat = e.get("latency_seconds", 0)
                    cost = e.get("cost", 0)
                    ts = datetime.fromtimestamp(e.get("finalized_at", 0)).strftime("%H:%M:%S") if e.get("finalized_at") else "?"
                    prov = e.get("provider", "?")
                    line = f"  [{ts}] {prov}: {model_s}  latency={_format_duration(lat)}  cost=${cost:.6f}\n"
                    hist_lines.append((line, "white"))
            else:
                hist_lines.append(("  (no history yet — submit a batch first)\n", "dim white"))
        else:
            hist_lines.append(("  (batch_history module not available)\n", "dim red"))

        # ── Aggregates ──
        agg_lines = [("\nPer-Provider Aggregates\n", "bold white underline"), ("\n", "")]
        if _HISTORY_OK:
            agg = get_aggregates()
            bp = agg.get("by_provider", {})
            if bp:
                for prov, stats in bp.items():
                    lat = stats.get("latency_seconds", {})
                    cost = stats.get("cost_usd", {})
                    agg_lines.append((f"  {prov} ({stats.get('batches', 0)} batches)\n", "cyan"))
                    if lat:
                        agg_lines.append((f"    Latency: min={lat['min']}s  mean={lat['mean']}s  max={lat['max']}s\n", ""))
                    if cost:
                        agg_lines.append((f"    Cost:    mean=${cost['mean']:.6f}  total=${cost['sum']:.4f}\n", ""))
            else:
                agg_lines.append(("  (no aggregate data yet)\n", "dim white"))
        else:
            agg_lines.append(("  (history module not available)\n", "dim red"))

        self.query_one("#dash-title", Static).update(title)
        self.query_one("#dash-counts", Static).update(counts)
        self.query_one("#dash-history", Static).update(Text.assemble(*hist_lines))
        self.query_one("#dash-aggregates", Static).update(Text.assemble(*agg_lines))


class BatchesScreen(Screen):
    """All batch state entries in a sortable table."""

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="batches-scroll"):
            yield Static("╔═══════════════════════════════════════════════════════════╗\n", markup=True)
            yield Static("║    Batches                                               ║\n", markup=True)
            yield Static("╚═══════════════════════════════════════════════════════════╝\n", markup=True)
            yield DataTable(id="batches-table")

    def on_screen_mounted(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        table = self.query_one("#batches-table", DataTable)
        table.clear(True)
        table.add_columns("Status", "Provider", "Batch ID", "Model", "Age", "Latency", "Req")

        state = _load_state()
        if not state:
            table.add_row("—", "—", "No batches yet", "—", "—", "—", "—")
            return

        # Sort: running first, then by age descending
        order = {"running": 0, "submitted": 1, "completed": 2, "failed": 3}
        items = sorted(state.items(),
                       key=lambda x: (order.get(x[1].get("status", ""), 99),
                                      -(x[1].get("submitted_at_unix", 0) or 0)))

        for batch_id, info in items:
            status = info.get("status", "?")
            provider = info.get("provider", "?")[:10]
            model = info.get("model", "?")[:28]
            age = _age_from_unix(info.get("submitted_at_unix"))
            lat = _format_duration(info.get("latency_seconds", 0))
            rqs = info.get("request_counts", {})
            if isinstance(rqs, dict):
                req_str = f"{rqs.get('completed', '?')}/{rqs.get('total', '?')}"
            else:
                req_str = "?"

            # Color by status
            s_style = ""
            if status == "running":
                s_style = "cyan"
            elif status == "completed":
                s_style = "green"
            elif status == "failed":
                s_style = "red"

            table.add_row(
                Text(status, style=s_style) if s_style else status,
                provider,
                batch_id[:20],
                model,
                age,
                lat if status == "completed" else "—",
                req_str,
            )


class HistoryScreen(Screen):
    """Historical completions with aggregates."""

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="hist-agg-panel"):
                yield Static(id="hist-agg", markup=True)
            yield Static("\n", markup=True)
            yield DataTable(id="hist-table")

    def on_screen_mounted(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        # Aggregates summary
        agg_text = Text.assemble(
            ("Per-Provider / Per-Model Aggregates\n", "bold white underline"),
        )
        if _HISTORY_OK:
            agg = get_aggregates()
            bp = agg.get("by_provider", {})
            for prov, stats in bp.items():
                lat = stats.get("latency_seconds", {})
                cost = stats.get("cost_usd", {})
                agg_text.append(f"\n  {prov} ({stats.get('batches', 0)} batches)\n", "cyan")
                if lat:
                    agg_text.append(f"    Latency:  min={lat['min']}s  mean={lat['mean']}s  max={lat['max']}s\n", "")
                if cost:
                    agg_text.append(f"    Cost:     mean=${cost['mean']:.6f}  total=${cost['sum']:.4f}\n", "")

            bm = agg.get("by_model", {})
            if bm:
                agg_text.append("\n  Per Model:\n", "bold white")
                for model_key, stats in list(bm.items())[:10]:
                    lat = stats.get("latency_seconds", {})
                    cost = stats.get("cost_usd", {})
                    agg_text.append(f"    {model_key[:45]}\n", "white")
                    if lat:
                        agg_text.append(f"      latency mean={lat['mean']}s  ", "")
                    if cost:
                        agg_text.append(f"cost mean=${cost['mean']:.6f}", "")
                    agg_text.append("\n", "")
        else:
            agg_text.append("  (history module not available)\n", "dim red")

        self.query_one("#hist-agg", Static).update(agg_text)

        # History table
        table = self.query_one("#hist-table", DataTable)
        table.clear(True)
        table.add_columns("Time", "Provider", "Model", "Latency", "Tokens", "Cost", "Backend")

        if _HISTORY_OK:
            entries = read_history()[:50]
            if entries:
                for e in entries:
                    ts = ""
                    if e.get("finalized_at"):
                        ts = datetime.fromtimestamp(e["finalized_at"]).strftime("%m/%d %H:%M")
                    prov = e.get("provider", "?")[:10]
                    model = e.get("raw_model", e.get("model", "?"))[:30]
                    lat = _format_duration(e.get("latency_seconds", 0))
                    tokens = str(e.get("total_tokens", "?"))
                    cost = f"${e.get('cost', 0):.6f}" if e.get("cost") else "—"
                    backend = (e.get("provider_backend") or "")[:12]

                    table.add_row(ts, prov, model, lat, tokens, cost, backend)
                return

        table.add_row("—", "—", "No history entries yet", "—", "—", "—", "—")


class EscalationsScreen(Screen):
    """Items needing human review."""

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="esc-scroll"):
            yield Static("╔═══════════════════════════════════════════════════════════╗\n", markup=True)
            yield Static("║    Escalations — Items Needing Review                     ║\n", markup=True)
            yield Static("╚═══════════════════════════════════════════════════════════╝\n", markup=True)
            yield DataTable(id="esc-table")
            yield Rule()
            yield Static(id="esc-detail", markup=True)

    def on_screen_mounted(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        table = self.query_one("#esc-table", DataTable)
        table.clear(True)
        table.add_columns("File", "Content Preview", "Reason")

        escs = _get_escalations()
        if not escs:
            table.add_row("—", "No escalations — all clear!", "—")
            self.query_one("#esc-detail", Static).update("")
            return

        for e in escs:
            fname = e.get("file", "?")[:20]
            content = (e.get("content") or e.get("result", {}).get("content") or "(no content)")[:50]
            reason = (e.get("reason") or e.get("classification") or "")[:30]
            table.add_row(fname, content, reason)

        self.query_one("#esc-detail", Static).update(
            "  Escalations require a human decision. Review each and decide:\n"
            "  archive → mark as done, escalate → keep for later"
        )


class LogsScreen(Screen):
    """Show recent log output from poll.log and router.log."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("╔═══════════════════════════════════════════════════════════╗\n", markup=True)
            yield Static("║    Logs                                                  ║\n", markup=True)
            yield Static("╚═══════════════════════════════════════════════════════════╝\n", markup=True)
            yield Static("Poll Log\n", markup=True, id="log-poll-title")
            yield RichLog(id="log-poll", highlight=True, markup=True, wrap=True, max_lines=30)
            yield Static("\nRouter Log\n", markup=True, id="log-router-title")
            yield RichLog(id="log-router", highlight=True, markup=True, wrap=True, max_lines=30)

    def on_screen_mounted(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        poll_log = _read_log("poll.log", 30)
        router_log = _read_log("router.log", 30)

        poll_widget = self.query_one("#log-poll", RichLog)
        poll_widget.clear()
        poll_widget.write(poll_log if poll_log.strip() else "(poll log is empty)")

        router_widget = self.query_one("#log-router", RichLog)
        router_widget.clear()
        router_widget.write(router_log if router_log.strip() else "(router log is empty)")


# ═══════════════════════════════════════════════════════════════════
#  Main App
# ═══════════════════════════════════════════════════════════════════

TITLE = "🔄  Batch Pipeline  🔄"


class BatchTUI(App):
    """Interactive TUI for the Batch Processing Pipeline."""

    CSS = """
    Screen {
        background: #1a1b2e;
    }

    Static {
        margin: 0 1;
    }

    DataTable {
        height: auto;
        margin: 0 1;
    }

    DataTable > .datatable--header {
        background: #2d3a5f;
        color: #88c0d0;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #3b4a6f;
        color: #ffffff;
    }

    RichLog {
        background: #0d1b2e;
        border: none;
        margin: 0 1;
    }

    #dash-scroll, #batches-scroll, #esc-scroll {
        overflow: auto;
    }

    #hist-agg-panel {
        height: auto;
        max-height: 12;
    }

    Horizontal {
        height: auto;
    }

    Vertical {
        height: auto;
    }

    Rule {
        margin: 0 2;
    }

    Button {
        margin: 1 2;
    }
    """

    BINDINGS = [
        Binding("1", "screen_dashboard", "Dashboard"),
        Binding("2", "screen_batches", "Batches"),
        Binding("3", "screen_history", "History"),
        Binding("4", "screen_escalations", "Escalations"),
        Binding("5", "screen_logs", "Logs"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    current_screen: str = "dashboard"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="tab-dash") as self.tabs:
            with TabPane("📊 Dashboard", id="tab-dash"):
                yield DashboardScreen()
            with TabPane("📋 Batches", id="tab-batches"):
                yield BatchesScreen()
            with TabPane("📈 History", id="tab-hist"):
                yield HistoryScreen()
            with TabPane("⚠️  Escalations", id="tab-esc"):
                yield EscalationsScreen()
            with TabPane("📜 Logs", id="tab-logs"):
                yield LogsScreen()
        yield Footer()

    def on_mount(self) -> None:
        """Set up auto-refresh."""
        self.set_interval(10, self._auto_refresh)

    def _auto_refresh(self) -> None:
        """Refresh the active screen every 10 seconds."""
        try:
            # Find the active tab's content pane and refresh its content
            tab = self.tabs.active_pane
            if tab is not None:
                for child in tab.children:
                    if hasattr(child, "refresh_content"):
                        child.refresh_content()
        except Exception:
            pass

    def action_screen_dashboard(self) -> None:
        self.current_screen = "dashboard"
        self.tabs.active = "tab-dash"

    def action_screen_batches(self) -> None:
        self.current_screen = "batches"
        self.tabs.active = "tab-batches"

    def action_screen_history(self) -> None:
        self.current_screen = "history"
        self.tabs.active = "tab-hist"

    def action_screen_escalations(self) -> None:
        self.current_screen = "escalations"
        self.tabs.active = "tab-esc"

    def action_screen_logs(self) -> None:
        self.current_screen = "logs"
        self.tabs.active = "tab-logs"

    def action_refresh(self) -> None:
        self._auto_refresh()


# ═══════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════

def main():
    app = BatchTUI()
    app.run()


if __name__ == "__main__":
    main()