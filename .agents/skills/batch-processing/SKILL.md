---
name: batch-processing
description: Async batch processing for LLMs (Anthropic, OpenRouter, Groq). Use when submitting, polling, tracking, or analyzing batch LLM requests and their cost/latency metrics.
---

# Batch Processing Helper

Project at `{{ cwd | default("Batch-Processing-Helper") }}`. Requires `venv/` and an API key for the provider in use (environment or `.env`).

## Quick reference

| Task | Command |
|------|---------|
| Submit a batch request | `bash batch.sh send "Your task"` |
| Submit several prompts as one batch | `bash batch.sh send "Task 1" "Task 2" "Task 3"` |
| Submit a file of prompts as one batch | `bash batch.sh send-file prompts.txt` |
| Preview a batch without sending it | `bash batch.sh --dry-run send "Task"` |
| Record which agent owns the batch | `bash batch.sh --agent "my-session" send "Task"` |
| Submit via OpenRouter with model | `bash batch.sh --provider openrouter --model "deepseek/deepseek-v4.1-flash" send "Task"` |
| Submit via Groq | `bash batch.sh --provider groq send "Task"` |
| Check pipeline status | `bash batch.sh status` |
| Run one poll + route cycle by hand | `bash batch.sh poll` |
| View recent completions | `bash batch.sh history` |
| View per-provider/per-model stats | `bash batch.sh stats` |
| View end-to-end latency and throughput | `bash batch.sh metrics` |
| View items needing review | `bash batch.sh escalations` |
| Launch interactive TUI | `bash batch.sh tui` |
| Start gateway + web console | `./start-server.sh --console` |
| Run unit tests | `python3 test_batch_pipeline.py --unit` |

How it works: see `PIPELINE.md`. Metrics vs stats: see `METRICS.md`.

## Providers

- **Anthropic**: `ANTHROPIC_API_KEY`
- **OpenRouter**: `OPENROUTER_API_KEY` and `BATCH_PROVIDER=openrouter`; model IDs are sent exactly as written
- **Groq**: `GROQ_API_KEY` and `BATCH_PROVIDER=groq`

## Key files

| File | Purpose |
|------|---------|
| `batch-submit.py` | Submit one request, or a whole prompt file as one batch |
| `batch-poll.py` | Poll for completion, download results, log history |
| `batch-router.py` | Classify each result: archive or escalate |
| `batch_common.py` | Folder defaults, locked state file, shared formatting |
| `batch_history.py` | Persistent history and aggregates |
| `batch_tui.py` | Interactive terminal UI |
| `batch-mcp.py` | MCP server (Claude Desktop, etc.) |
| `providers/` | Provider abstraction layer |
| `test_batch_pipeline.py` | Test suite (`--unit`, `--live`, `--filter TEXT`) |

## Key env vars

```
BATCH_PROVIDER          anthropic (default), openrouter, or groq
BATCH_MODEL             model name; unset = the provider's default
OPENROUTER_BATCH_MODEL  model override for OpenRouter
BATCH_DIR               where runtime data lives (default .batch-data/)
```

## Common issues

- **`ModuleNotFoundError`**: the dependencies are not in `venv/`; run `pip install -r requirements.txt` there.
- **Scheduled job does nothing**: read `.batch-data/logs/orchestrator.log`; cron needs the key in `.env`.
- **Batch seems stuck**: batch APIs can take up to 24 hours; check `bash batch.sh status` and `poll.log`.
