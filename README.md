# Multi-Provider Batch Processing

---

## 📋 TL;DR — What Is This???

**An extensible, multi-provider asynchronous batch processing engine for Large Language Models (LLMs).** It submits work to supported Batch APIs (Anthropic, OpenRouter), polls for results in the background, routes results via LLM classification, and logs every run to a persistent **batch history database** for cost and performance analytics — all with full audit logging, per-provider/per-model metrics, and pluggable provider support.

### Why it exists

Live LLM API calls are expensive and blocking. Batch APIs offer **50–90% cost reduction** but require async infrastructure. This project provides that infrastructure as a clean, extensible framework with built-in analytics to track what you're spending and how fast each provider/model delivers.

### Architecture at a glance

```
User Task  →  Provider Abstraction Layer  →  Batch API (Anthropic/OpenRouter/any)
                                                  ↓ (async, minutes/hours)
            LLM Router ←─────────────── Completed results
               ↓
        Archive / Escalate / Re-queue
               ↓
        📊 History Database ←── every completion logged
        (per-provider, per-model latency/cost aggregates)
```

### What it demonstrates

- **Pluggable provider architecture** — Abstract base class (`BatchProvider`) with concrete implementations for Anthropic and OpenRouter. Adding a new provider is one file + one line of registration.
- **Multi-request batches (R1)** — Send any number of tasks in a single API batch. All requests share one batch lifecycle, reducing overhead and cost.
- **Per-request IDs (R2)** — Each request gets a unique `custom_id` (e.g. `batch-0000`, `batch-0001`). Results carry the same ID back, so you can trace which response matches which request.
- **Agent ownership (R3)** — Every batch can be tagged with an `--agent` identifier. The agent follows the batch through state, history, and logs — enabling multi-agent workflows where each pi session owns its batches.
- **Pre-submit review (R4)** — `--dry-run` previews the batch JSON (requests, IDs, model, agent) without sending it. You inspect, edit the command, and re-run.
- **Asynchronous pipeline design** — Submit → poll (via cron/systemd) → fetch → classify → route, with UUID-based tracking across all stages.
- **Cross-provider compatibility** — Normalizes different batch API formats (Anthropic's SDK vs OpenRouter's REST API) into a unified state model. `.batch-state` tracks batches from multiple providers simultaneously.
- **LLM-as-a-judge routing** — Uses a live model call to classify each result (text/question/error/action_needed) and decide the next step without human intervention.
- **Persistent history & analytics** — Every completed batch is logged to `.batch-data/history/history.jsonl` with latency, token usage, cost, and agent. Per-provider and per-model aggregates are computed automatically.
- **Full observability** — Per-provider latency metrics, routing time tracking, and structured audit logs.
- **Clean CLI + automation** — Bash wrappers, cron/systemd integration, shell prompt status indicators.

### How to use it (plain English)

1. **Install once** — clone the repo, create a Python virtual environment, install dependencies. Takes 2 minutes.
2. **Pick your provider** — set your Anthropic or OpenRouter API key in an environment variable. That's your "login."
3. **Send a task** — run `batch.sh send "Describe your task"`. The program wraps your task in the correct API format, submits it to the provider's batch queue, and saves a tracking file with a unique ID.
4. **Walk away** — the batch API processes your request asynchronously (minutes to hours). A cron job or systemd timer checks for completion every 2 minutes automatically.
5. **Results come back** — when done, an LLM classifier reads each result and decides: *archive* (task complete, file it away), *escalate* (needs a human decision — flagged for your review), or *re-queue* (ready for the next batch step). The run is logged to history.
6. **Check in anytime** — run `batch.sh status` to see counts of queued/completed/escalated work. Run `batch.sh history` to see recent completion times and costs. Run `batch.sh stats` for per-provider and per-model aggregates.

**That's it.** You submit tasks, they process in the background at half the cost, and you only get involved when the system decides it needs you.

### Tech stack

**Python** (provider SDKs, `requests`, `json`, `dataclasses`, `statistics`), **Bash** (CLI wrappers), **cron/systemd** (scheduling), **LLM APIs** (Anthropic Beta Batch, OpenRouter Batch API).

---

## Table of Contents

- [Supported Providers](#supported-providers)
- [What's Included](#whats-included)
- [Quick Start](#quick-start)
- [Commands](#commands)
- [Provider Selection](#provider-selection)
- [How It Works](#how-it-works)
- [File Structure](#file-structure)
- [History & Analytics](#history--analytics)
- [Cost Savings](#cost-savings)
- [Extending: Add a New Provider](#extending-add-a-new-provider)
- [Logs & Audit](#logs--audit)
- [Testing](#testing)
- [MCP Server](#mcp-server-claude-desktop-cursor-vs-code-pi)
- [Pi Skill](#pi-skill)
- [Shell Prompt Integration](#shell-prompt-integration)
- [Troubleshooting](#troubleshooting)

---

## Supported Providers

| Provider | Batch API | Model Access | Cost vs Live | Backend Provider |
|----------|-----------|-------------|--------------|-----------------|
| **Anthropic** | ✅ Native | Claude models only | ~50% cheaper | Anthropic |
| **OpenRouter** | ✅ Native | 200+ models (Claude, GPT, Gemini, Llama, DeepSeek…) | ~50–90% cheaper | Varies (Sail Research, etc.) |

**Note on batch models:** OpenRouter requires a `:batch` model suffix (e.g. `deepseek/deepseek-v4.1-flash:batch`). The provider appends it automatically if omitted.

**Provider backends:** When routing through OpenRouter, the actual inference provider (e.g. "Sail Research" for DeepSeek models) is logged in the history for transparency.

## What's Included

- **Batch submission** (`batch-submit.py`) — Queue requests to any supported batch API
- **Polling** (`batch-poll.py`) — Periodic checks for completed batches across all providers, with automatic history logging
- **Smart routing** (`batch-router.py`) — LLM classifier routes results to archive, escalate, or queue next batch
- **History & analytics** (`batch_history.py`) — Persistent JSONL log of every completed batch; per-provider and per-model aggregates
- **Provider abstraction** (`providers/`) — Common interface for all batch backends
- **CLI wrappers** (`batch.sh`) — Easy commands to submit, check status, view history/stats, view escalations
- **MCP server** (`batch-mcp.py`) — Exposes all operations as MCP tools for Claude Desktop, Cursor, VS Code, and pi
- **Pi skill** — `.agents/skills/batch-processing/SKILL.md` auto-discovered by pi
- **Systemd/cron integration** — Automatic polling every 2 minutes
- **Logging & metrics** — Full audit trail and performance tracking per provider
- **Test suite** (`test_batch_pipeline.py`) — 21 unit tests

## Quick Start

```bash
# 1. Clone
cd ~/Projects/tools/Batch-Processing-Helper

# 2. Setup venv
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3a. Set API key (Anthropic)
export ANTHROPIC_API_KEY="sk-..."

# 3b. Or set API key (OpenRouter)
export OPENROUTER_API_KEY="sk-..."
export BATCH_PROVIDER=openrouter

# 4. Send work — single or multi-request batch
bash batch.sh send "Write a summary of my project"

#    Or send multiple requests in ONE batch (R1):
bash batch.sh send "Task 1" "Task 2" "Task 3"

# 5. Tag with agent ownership (R3):
bash batch.sh --agent "my-pi-session" send "Task"

# 6. Preview batch before sending (R4):
bash batch.sh --dry-run send "Task 1" "Task 2"

# 7. Check status
bash batch.sh status

# 8. Later: view history and stats
bash batch.sh history
bash batch.sh stats
```

## Commands

```bash
# ── Basic submission (single request in a batch) ──
bash batch.sh send "Your task description"

# ── Multi-request batch (R1): all in one API call ──
bash batch.sh send "Task 1" "Task 2" "Task 3"

# ── Read tasks from stdin (one per line) ──
cat tasks.txt | python3 batch-submit.py --from-stdin

# ── Agent ownership (R3): tag the batch ──
bash batch.sh --agent "pi-session-abc" send "Task"

# ── Provider + model ──
bash batch.sh --provider openrouter --model "deepseek/deepseek-v4.1-flash" send "Analyze this code"

# ── Dry-run (R4): preview without submitting ──
bash batch.sh --dry-run send "Task 1" "Task 2"

# ── Check pipeline status ──
bash batch.sh status

# ── Items needing human decision ──
bash batch.sh escalations

# ── Performance metrics (per-provider breakdown) ──
bash batch.sh metrics

# ── Recent history (last 10 completions) ──
bash batch.sh history

# ── Aggregate stats per provider/model ──
bash batch.sh stats

# ── Logs ──
bash batch.sh logs

# ── Available providers ──
bash batch.sh providers
```

### Interactive TUI (Textual-based, mouse + keyboard)

```bash
# Launch the terminal UI
bash batch.sh tui
```

![TUI concept](https://img.shields.io/badge/TUI-Textual-blue)

The TUI provides five tabbed views with auto-refresh every 10 seconds:

| Tab | Content | Keys |
|-----|---------|------|
| **📊 Dashboard** | Pipeline overview: counts, recent history, per-provider aggregates | `1` |
| **📋 Batches** | All batch state entries with status, provider, model, age, latency | `2` |
| **📈 History** | Historical completions table + per-provider/per-model stats | `3` |
| **⚠️ Escalations** | Items needing human review | `4` |
| **📜 Logs** | Tail of poll.log and router.log | `5` |

**Controls:** `1`–`5` switch tabs, `r` refreshes, `q` quits. All views respond to mouse clicks.

---

## Provider Selection

Set provider globally via environment:

```bash
# Always use OpenRouter
export BATCH_PROVIDER=openrouter

# Or per-command
bash batch.sh --provider openrouter send "Task"
```

### Anthropic Configuration

```bash
export ANTHROPIC_API_KEY="sk-..."                        # Required
export BATCH_MODEL="claude-haiku-4-5-20251001"           # Optional (default)
```

### OpenRouter Configuration

```bash
export OPENROUTER_API_KEY="sk-..."                       # Required
export BATCH_PROVIDER=openrouter                         # Select provider
export OPENROUTER_BATCH_MODEL="deepseek/deepseek-v4.1-flash"  # Model (defaults to BATCH_MODEL)
export OPENROUTER_REFERER="https://..."                  # Optional: identify your app
export OPENROUTER_APP_NAME="my-pipeline"                 # Optional: identify your app
```

OpenRouter provides access to **200+ models** from all major providers. The `:batch` suffix is appended automatically:

| Model ID | Description |
|----------|-------------|
| `anthropic/claude-3.5-haiku` | Claude via OpenRouter |
| `openai/gpt-4o` | GPT-4o |
| `google/gemini-2.0-flash-001` | Gemini Flash |
| `meta-llama/llama-3.3-70b-instruct` | Llama 3 |
| `deepseek/deepseek-v4.1-flash` | DeepSeek v4.1 Flash (fast reasoning) |

See all models at [openrouter.ai/models](https://openrouter.ai/models).

## How It Works

```
Your task
    ↓
batch.sh [--provider X] send "task"
    ↓
Provider builds request (Anthropic or OpenRouter format)
    ↓
Request queued (UUID-tracked with provider metadata)
    ↓
Cron/systemd timer polls every 2 minutes
    ↓
Provider's Batch API completes work
    ↓
LLM classifier routes result:
  • Archive (task done)        → completed/
  • Escalate (needs decision)  → escalations/
  • Queue next (more steps)    → requests/ (loop)
    ↓
📊 History logged: latency, cost, tokens, provider_backend
    ↓
You check: bash batch.sh status / history / stats
    ↓
If escalation: review and decide
```

### Pipeline stages in detail

1. **Submit** — `batch-submit.py` accepts **one or more messages** (R1). Each gets a unique `custom_id` (R2). You can tag the whole batch with an `--agent` identifier (R3). Use `--dry-run` to preview before sending (R4). The provider abstraction converts tasks into the correct API format, submits them all as a single batch, and writes a tracking file + state entry with all custom_ids.

2. **Poll** — `batch-poll.py` reads `.batch-state`, groups batches by provider, and calls each provider's `retrieve_batch()` / `get_results()` when done. Results are normalized into a common format and written to `responses/`. Each result carries its original `custom_id` (R2). On completion, the batch is automatically logged to history with latency, usage, cost, provider backend, and agent (R3).

3. **Route** — `batch-router.py` sends each completed result to a live LLM for classification: is this output, a question, an error, or action-needed? Based on the answer, it archives the result, escalates for human review, or re-queues for another batch step.

4. **Log** — Every completed batch is recorded in `.batch-data/history/history.jsonl` with all fields including `agent` and `custom_ids`.

5. **Review** — Human checks `bash batch.sh escalations` or `bash batch.sh status` to see what needs attention. `bash batch.sh history` shows recent completions with costs and agents.

## File Structure

```
Batch-Processing-Helper/
├── batch.sh                     # Main command (bash)
├── batch.fish                   # Fish shell version
├── batch-submit.py              # Submit to provider's Batch API
├── batch-poll.py                # Poll for results + log history
├── batch-router.py              # Route/classify results
├── batch-status.py              # Pipeline status display
├── batch-metrics.py             # Performance metrics
├── batch_history.py             # ★ Persistent history & aggregates
├── batch-orchestrator.sh        # Systemd/cron integration
├── batch-config.sh              # Configuration (edit this)
├── batch_tui.py                 # ★ Interactive TUI (Textual-based, mouse+keyboard)
├── batch-mcp.py                 # ★ MCP server (Claude Desktop, Cursor, pi)
├── poll_and_results.py          # Convenience: poll batch + retrieve results
├── test_batch_pipeline.py       # ★ 21 unit tests
├── .agents/                     # ★ Pi skill (auto-discovered)
│   └── skills/batch-processing/SKILL.md
├── providers/                   # ★ Provider abstraction layer
│   ├── __init__.py              # Provider registry & factory
│   ├── base.py                  # Abstract base class (BatchProvider)
│   ├── anthropic_provider.py    # Anthropic Batch API implementation
│   └── openrouter_provider.py   # OpenRouter Batch API implementation
├── .batch-data/                 # ★ Runtime data (auto-created)
│   ├── requests/                # Queued requests (UUID.jsonl)
│   ├── responses/               # Completed results (UUID.result)
│   ├── escalations/             # Awaiting decision (UUID.escalate)
│   ├── completed/               # Finished tasks (UUID.done)
│   ├── logs/                    # Audit logs
│   ├── history/                 # ★ Persistent batch history
│   │   ├── history.jsonl        #   Append-only log of completions
│   │   └── history.db.json      #   Pre-computed aggregates
│   └── .batch-state             # Batch tracking state
├── SETUP.md                     # Installation guide
├── PIPELINE.md                  # Full technical docs & architecture
├── METRICS.md                   # Performance tracking docs
├── ISSUES.md                    # Known issues & roadmap
└── requirements.txt             # Python deps (anthropic, requests)
```

## History & Analytics

Every completed batch is automatically logged to a persistent history database inside `.batch-data/history/`.

### What's tracked per batch

| Field | Description |
|-------|-------------|
| `batch_id` | Provider-assigned batch ID |
| `provider` | e.g. `openrouter`, `anthropic` |
| `model` / `raw_model` | Requested model & provider-resolved model name |
| `latency_seconds` | Time from batch creation to completion |
| `pipeline_latency` | Time from submission to completion (wall clock) |
| `total_requests` / `completed_requests` | Request counts |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | Token usage |
| `cost` | Dollar cost (from provider when available) |
| `provider_backend` | Actual inference provider (e.g. "Sail Research" for DeepSeek via OpenRouter) |
| `agent` | Agent/source that submitted the batch (R3) |
| `custom_ids` | List of all request IDs in this batch (R2) |

### Commands

```bash
# Show last 10 completions
bash batch.sh history

# Show last 50
bash batch.sh history 50

# Show aggregate stats per provider and per model
bash batch.sh stats
```

### Example output

```
  Batch History (last 10 of 1 total)
 ════════════════════════════════════════════════════════════════════════
  ID         PROVIDER      MODEL                            STATUS     TIME     COST
  ──────────────────────────────────────────────────────────────────────
  b-...KItf  openrouter   deepseek/deepseek-v4.1-flash...   completed  875s     $0.000034
 ════════════════════════════════════════════════════════════════════════
```

```
  Batch Processing Aggregates
  Total batches: 1
 ══════════════════════════════════════════════════════════════════════

  Provider: openrouter
    Batches: 1
    Latency:  min=875s  mean=875s  max=875s
    Cost:     mean=$0.000034  total=$0.0000
    Tokens:   mean=352  total=352
 ══════════════════════════════════════════════════════════════════════
```

### Programmatic access

The history data is stored as newline-delimited JSON in `history.jsonl` for easy consumption by other tools. Pre-computed aggregates live in `history.db.json`.

```python
from batch_history import read_history, get_aggregates

entries = read_history()      # list[dict], newest first
aggregates = get_aggregates() # dict with by_provider and by_model stats
```

## Cost Savings

| Provider | Task | Live API | Batch API | Savings |
|----------|------|----------|-----------|---------|
| **Anthropic** | 1 hr analysis | $0.30 | $0.15 | 50% |
| **Anthropic** | 10 image builds | $3.00 | $1.50 | 50% |
| **OpenRouter** | GPT-4o analysis | $0.50 | $0.10 | 80% |
| **OpenRouter** | Gemini batch | $0.15 | $0.04 | 73% |
| **OpenRouter** | 3 DeepSeek v4.1 Flash queries | $0.15 | **$0.000034** | ~99.9% |

*Last row: real measured cost from an actual test batch (3 requests, 352 tokens total, via Sail Research).*

**Time trade-off:** Batch processes in background (minutes to hours), live takes seconds. Best for non-urgent, cost-sensitive workloads.

## Extending: Add a New Provider

The provider abstraction is intentionally minimal — just 4 methods to implement:

```python
from .base import BatchProvider, BatchResult, BatchStatus

class YourProvider(BatchProvider):
    def get_provider_name(self):
        return "your_provider"

    def build_request(self, custom_id, user_message, system_message=None,
                      model=None, max_tokens=2048, temperature=0.0):
        return { ... your API format ... }

    def create_batch(self, requests):
        return batch_id

    def retrieve_batch(self, batch_id):
        return {"id": batch_id, "status": ..., "created_at": ..., "ended_at": ...,
                "model": ..., "usage": {...}, "request_counts": {...}}

    def get_results(self, batch_id):
        return [BatchResult(custom_id="...", content="...")]
```

**Important for history tracking:** `retrieve_batch()` should return `model`, `usage` (with `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost`), and `request_counts` (with `total`, `completed`, `failed`) for proper analytics.

2. **Register** in `providers/__init__.py`:

```python
from .your_provider import YourProvider
_PROVIDERS["your_provider"] = YourProvider
```

3. **Configure** in `batch-config.sh` with any required environment variables.

4. **Done** — all pipeline scripts (`batch-submit.py`, `batch-poll.py`, `batch-router.py`, `batch_history.py`) auto-detect and use the new provider.

See `providers/base.py` for the full interface. See `providers/openrouter_provider.py` for a complete example.

## Logs & Audit

Every operation logged to `logs/` with provider context:

```bash
tail .batch-data/logs/orchestrator.log   # Main pipeline activity
tail .batch-data/logs/poll.log           # Polling results ([anthropic] or [openrouter])
tail .batch-data/logs/router.log         # Routing decisions with timing
```

Each request tracked with UUID + provider for full audit trail. Example log entries:

```
[2026-01-15T10:45:00] [openrouter] batch_abc123 completed in 15.2 min → responses/uuid.result
[2026-01-15T10:45:01] [openrouter] uuid → archive (1834ms) Analysis complete
```

History entries (`.batch-data/history/history.jsonl`) provide durable, queryable records of every batch:

```json
{"batch_id":"batch-...","provider":"openrouter","raw_model":"deepseek/...","latency_seconds":875.0,"total_tokens":352,"cost":3.38e-05,"provider_backend":"Sail Research"}
```

## Testing

```bash
# Run all unit tests (no API calls required)
python3 test_batch_pipeline.py --unit

# Run live integration tests (requires OPENROUTER_API_KEY)
python3 test_batch_pipeline.py --live

# Run everything
python3 test_batch_pipeline.py
```

Current test results: **21/21 passing** (2 live tests skipped without API key). Tests cover:
- Provider registry & factory
- Request/result dataclasses
- OpenRouter request format & batch model suffix
- Anthropic request format
- Config loading
- Pipeline graceful error handling
- History module: schema, round-trip, empty state, aggregates
- Router: chat completion fallback, JSON parsing
- TUI: imports, helper functions, formatting
- `chat_complete`: OpenRouter + Anthropic implementations, base class contract

## MCP Server (Claude Desktop, Cursor, VS Code, Pi)

`batch-mcp.py` exposes six tools via stdio MTP:

| Tool | Description |
|------|-------------|
| `batch_send` | Submit a batch request (task, provider?, model?) |
| `batch_status` | Current pipeline status with counts and recent activity |
| `batch_history` | Recent completions with latency, cost, tokens |
| `batch_stats` | Per-provider and per-model aggregates |
| `batch_escalations` | Items awaiting human review |
| `batch_poll` | Trigger a poll cycle |

### Claude Desktop setup

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "batch-processing": {
      "command": "python3",
      "args": ["/path/to/Batch-Processing-Helper/batch-mcp.py"],
      "env": {
        "OPENROUTER_API_KEY": "${OPENROUTER_API_KEY}",
        "BATCH_PROVIDER": "openrouter"
      }
    }
  }
}
```

### Pi setup

```bash
pi mcp add batch-processing -- python3 /path/to/Batch-Processing-Helper/batch-mcp.py
```

Tools appear as `mcp__batch_processing__batch_send`, etc.

### Test from shell

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 batch-mcp.py
```

---

## Pi Skill

The skill at `.agents/skills/batch-processing/SKILL.md` tells pi when and how to use the batch pipeline. It's loaded **only when relevant** — no prompt bloat.

### Local (project-only) — auto-discovered

Just run pi from the project directory. Pi discovers `.agents/skills/` when [project trust](https://pi-docs) is granted.

### Global (any directory, any pi process)

```bash
# Symlink the skill into your user-level skills directory
mkdir -p ~/.agents/skills
ln -s "$PWD/.agents/skills/batch-processing" ~/.agents/skills/batch-processing
```

Now the skill is available from **any directory, any pi process**, including parallel sessions elsewhere on your filesystem. Pi scans `~/.agents/skills/` at startup.

### What the skill covers

- When to use the batch pipeline (cost-sensitive or async LLM tasks)
- How to submit, check status, view history and stats
- How to launch the TUI
- Provider configuration and common troubleshooting

---

## Shell Prompt Integration

Show pipeline status directly in your shell prompt:

```fish
# Fish shell — add to config.fish
function fish_prompt
  set -l prov (echo $BATCH_PROVIDER)
  set -l req (count .batch-data/requests/*.jsonl 2>/dev/null)
  set -l esc (count .batch-data/escalations/*.escalate 2>/dev/null)

  if test $esc -gt 0
    set status_text "⚠ Batch[$prov]:$esc "
  else if test $req -gt 0
    set status_text "◌ Batch[$prov]:$req "
  end

  echo -n $status_text
  # ... rest of your prompt
end
```

## Troubleshooting

Quick checks:

```bash
# Is the timer running?
systemctl --user status freedom-batch-poll.timer
crontab -l | grep batch-orchestrator

# API key set? (check your provider)
echo $ANTHROPIC_API_KEY
echo $OPENROUTER_API_KEY

# Provider selected?
echo $BATCH_PROVIDER

# Any requests queued?
ls .batch-data/requests/

# Check provider status
bash batch.sh providers

# Full pipeline status
bash batch.sh status

# View history
bash batch.sh history

# Check OpenRouter batch models are being used correctly
# (model should end in :batch for OpenRouter)
bash batch.sh history | grep openrouter
```

See `SETUP.md` for common issues and fixes.
