#!/usr/bin/env python3
"""
batch_tui.py — Interactive TUI for the Batch Processing Pipeline.

A Textual-based terminal UI with mouse and keyboard navigation for:
  • Dashboard — pipeline overview, counts, recent completions
  • Batches   — all batch state entries with status/age
  • History   — historical completions with per-provider aggregates
  • Escalations — items needing human review
  • Logs      — recent poll/router log tail

Keyboard:  1-5 switch tabs, r refresh, q quit
Mouse:     click tabs, scroll tables
"""

import sys
from pathlib import Path
from datetime import datetime

# ── Textual imports ────────────────────────────────────────────────
from textual.app import App, ComposeResult
from textual.widgets import (
    Header, Footer, Static, DataTable, RichLog,
    TabbedContent, TabPane, Rule
)
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.binding import Binding
from rich.text import Text

# ── Ensure project root on path ────────────────────────────────────
_HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(_HERE))

from batch_common import (
    format_age, format_duration, pipeline_counts, read_escalations, read_state, resolve_paths,
)
from batch_history import read_history, get_aggregates


# ═══════════════════════════════════════════════════════════════════
#  Data helpers
# ═══════════════════════════════════════════════════════════════════

def _read_log(log_name: str, lines: int = 30) -> str:
    log_file = Path(resolve_paths()["logs_dir"]) / log_name
    if log_file.exists():
        try:
            content = log_file.read_text()
            return "\n".join(content.strip().split("\n")[-lines:])
        except Exception:
            return f"(error reading {log_name})"
    return f"(no {log_name} yet)"


# ═══════════════════════════════════════════════════════════════════
#  Screens
# ═══════════════════════════════════════════════════════════════════

class DashboardScreen(Vertical):
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

    def on_mount(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        state = read_state()

        # ── Counts ──
        pipeline = pipeline_counts()
        history = read_history()

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
            (f"  Batches:     {pipeline['batches']:3d} total  ", ""),
            (f"{pipeline['running']:3d} running  ", "cyan"),
            (f"{pipeline['completed']:3d} completed  ", "green"),
            (f"{pipeline['failed'] + pipeline['cancelled']:3d} failed or cancelled\n", "red"),
            (f"  Results:     {pipeline['awaiting_routing']:3d} to route  ", ""),
            (f"{pipeline['archived']:3d} archived  ", "green"),
            (f"{pipeline['escalations']:3d} escalated\n", "yellow"),
            (f"  Providers:   {prov_str}\n", "white"),
            (f"  History:     {len(history)} entries", "blue"),
            ("\n", ""),
        )

        # ── Recent history ──
        hist_lines = [("\nRecent Completions\n", "bold white underline"), ("\n", "")]
        if history:
            for e in history[:8]:
                model_s = e.get("raw_model", e.get("model", "?"))[:35]
                lat = e.get("latency_seconds", 0)
                cost = e.get("cost")
                cost_s = f"${cost:.6f}" if cost else "—"
                ts = datetime.fromtimestamp(e.get("finalized_at", 0)).strftime("%H:%M:%S") if e.get("finalized_at") else "?"
                prov = e.get("provider", "?")
                line = f"  [{ts}] {prov}: {model_s}  latency={format_duration(lat)}  cost={cost_s}\n"
                hist_lines.append((line, "white"))
        else:
            hist_lines.append(("  (no history yet — submit a batch first)\n", "dim white"))

        # ── Aggregates ──
        agg_lines = [("\nPer-Provider Aggregates\n", "bold white underline"), ("\n", "")]
        by_provider = get_aggregates().get("by_provider", {})
        if by_provider:
            for prov, stats in by_provider.items():
                lat = stats.get("latency_seconds", {})
                cost = stats.get("cost_usd", {})
                agg_lines.append((f"  {prov} ({stats.get('batches', 0)} batches)\n", "cyan"))
                if lat:
                    agg_lines.append((f"    Latency: min={lat['min']}s  mean={lat['mean']}s  max={lat['max']}s\n", ""))
                if cost:
                    agg_lines.append((f"    Cost:    mean=${cost['mean']:.6f}  total=${cost['sum']:.4f}\n", ""))
        else:
            agg_lines.append(("  (no aggregate data yet)\n", "dim white"))

        self.query_one("#dash-title", Static).update(title)
        self.query_one("#dash-counts", Static).update(counts)
        self.query_one("#dash-history", Static).update(Text.assemble(*hist_lines))
        self.query_one("#dash-aggregates", Static).update(Text.assemble(*agg_lines))


class BatchesScreen(Vertical):
    """All batch state entries in a sortable table."""

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="batches-scroll"):
            yield Static("╔═══════════════════════════════════════════════════════════╗\n", markup=True)
            yield Static("║    Batches                                               ║\n", markup=True)
            yield Static("╚═══════════════════════════════════════════════════════════╝\n", markup=True)
            yield DataTable(id="batches-table")

    def on_mount(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        table = self.query_one("#batches-table", DataTable)
        table.clear(True)
        table.add_columns("Status", "Provider", "Batch ID", "Model", "Age", "Latency", "Req")

        state = read_state()
        if not state:
            table.add_row("—", "—", "No batches yet", "—", "—", "—", "—")
            return

        # Sort: running first, then by age descending
        order = {"running": 0, "submitted": 1, "completed": 2, "failed": 3, "cancelled": 4}
        items = sorted(state.items(),
                       key=lambda x: (order.get(x[1].get("status", ""), 99),
                                      -(x[1].get("submitted_at_unix", 0) or 0)))

        for batch_id, info in items:
            status = info.get("status", "?")
            provider = info.get("provider", "?")[:10]
            model = info.get("model", "?")[:28]
            age = format_age(info.get("submitted_at_unix"))
            lat = format_duration(info.get("latency_seconds", 0))
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
            elif status == "cancelled":
                s_style = "yellow"

            table.add_row(
                Text(status, style=s_style) if s_style else status,
                provider,
                batch_id[:20],
                model,
                age,
                lat if status == "completed" else "—",
                req_str,
            )


class HistoryScreen(Vertical):
    """Historical completions with aggregates."""

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="hist-agg-panel"):
                yield Static(id="hist-agg", markup=True)
            yield Static("\n", markup=True)
            yield DataTable(id="hist-table")

    def on_mount(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        # Aggregates summary
        agg_text = Text.assemble(
            ("Per-Provider / Per-Model Aggregates\n", "bold white underline"),
        )
        agg = get_aggregates()
        for prov, stats in agg.get("by_provider", {}).items():
            lat = stats.get("latency_seconds", {})
            cost = stats.get("cost_usd", {})
            agg_text.append(f"\n  {prov} ({stats.get('batches', 0)} batches)\n", "cyan")
            if lat:
                agg_text.append(f"    Latency:  min={lat['min']}s  mean={lat['mean']}s  max={lat['max']}s\n", "")
            if cost:
                agg_text.append(f"    Cost:     mean=${cost['mean']:.6f}  total=${cost['sum']:.4f}\n", "")

        by_model = agg.get("by_model", {})
        if by_model:
            agg_text.append("\n  Per Model:\n", "bold white")
            for model_key, stats in list(by_model.items())[:10]:
                lat = stats.get("latency_seconds", {})
                cost = stats.get("cost_usd", {})
                agg_text.append(f"    {model_key[:45]}\n", "white")
                if lat:
                    agg_text.append(f"      latency mean={lat['mean']}s  ", "")
                if cost:
                    agg_text.append(f"cost mean=${cost['mean']:.6f}", "")
                agg_text.append("\n", "")

        self.query_one("#hist-agg", Static).update(agg_text)

        # History table
        table = self.query_one("#hist-table", DataTable)
        table.clear(True)
        table.add_columns("Time", "Provider", "Model", "Latency", "Tokens", "Cost", "Backend")

        entries = read_history()[:50]
        if not entries:
            table.add_row("—", "—", "No history entries yet", "—", "—", "—", "—")
            return

        for e in entries:
            ts = ""
            if e.get("finalized_at"):
                ts = datetime.fromtimestamp(e["finalized_at"]).strftime("%m/%d %H:%M")
            prov = e.get("provider", "?")[:10]
            model = e.get("raw_model", e.get("model", "?"))[:30]
            lat = format_duration(e.get("latency_seconds", 0))
            tokens = str(e.get("total_tokens", "?"))
            cost = f"${e.get('cost', 0):.6f}" if e.get("cost") else "—"
            backend = (e.get("provider_backend") or "")[:12]

            table.add_row(ts, prov, model, lat, tokens, cost, backend)


class EscalationsScreen(Vertical):
    """Items needing human review."""

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="esc-scroll"):
            yield Static("╔═══════════════════════════════════════════════════════════╗\n", markup=True)
            yield Static("║    Escalations — Items Needing Review                     ║\n", markup=True)
            yield Static("╚═══════════════════════════════════════════════════════════╝\n", markup=True)
            yield DataTable(id="esc-table")
            yield Rule()
            yield Static(id="esc-detail", markup=True)

    def on_mount(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        table = self.query_one("#esc-table", DataTable)
        table.clear(True)
        table.add_columns("Request", "Class", "Reason", "Response")

        escs = read_escalations(50)
        if not escs:
            table.add_row("—", "—", "No escalations — all clear!", "—")
            self.query_one("#esc-detail", Static).update("")
            return

        # Text(...) so brackets in model output are not read as markup
        for e in escs:
            if e.get("error"):
                table.add_row(Text(e["file"][:24]), "—", Text(e["error"]), "—")
                continue
            reason = e["reason"] or e["summary"]
            preview = " ".join(e["response"].split())
            table.add_row(
                Text(e["request_id"][:24]),
                Text(e["classification"] or "—"),
                Text(reason[:40]),
                Text(preview[:50] or "(empty response)"),
            )

        self.query_one("#esc-detail", Static).update(
            "  Each escalation is a file in the escalations folder (<request>.escalate).\n"
            "  Read it, act on it, then delete the file to clear it from this list."
        )


class LogsScreen(Vertical):
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

    def on_mount(self) -> None:
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
        self.set_interval(10, self.refresh_active_pane)

    def refresh_active_pane(self) -> None:
        """Refresh the active screen every 10 seconds."""
        try:
            # Find the active tab's content pane and refresh its content
            tab = self.tabs.active_pane
            if tab is not None:
                for child in tab.children:
                    if hasattr(child, "refresh_content"):
                        child.refresh_content()
        except Exception as e:
            self.notify(f"Refresh failed: {e}", severity="error", timeout=10)

    def action_screen_dashboard(self) -> None:
        self.tabs.active = "tab-dash"

    def action_screen_batches(self) -> None:
        self.tabs.active = "tab-batches"

    def action_screen_history(self) -> None:
        self.tabs.active = "tab-hist"

    def action_screen_escalations(self) -> None:
        self.tabs.active = "tab-esc"

    def action_screen_logs(self) -> None:
        self.tabs.active = "tab-logs"

    def action_refresh(self) -> None:
        self.refresh_active_pane()


# ═══════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════

def main():
    app = BatchTUI()
    app.run()


if __name__ == "__main__":
    main()