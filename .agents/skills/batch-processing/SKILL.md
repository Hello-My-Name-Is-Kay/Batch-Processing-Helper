---
name: batch-processing
description: Multi-provider async batch processing for LLMs (Anthropic, OpenRouter). Use when submitting, polling, tracking, or analyzing batch LLM requests and their cost/latency metrics.
---

# Batch Processing Helper

Project at `{{ cwd | default("Batch-Processing-Helper") }}`. Requires `venv/` and an API key for the provider in use (environment or `.env`).

## Quick reference

| Task | Command |
|------|---------|
| Submit a batch request | `bash batch.sh send "Your task"` |
| Submit a file of prompts as one batch | `bash batch.sh send-file prompts.txt` |
| Submit via OpenRouter with model | `bash batch.sh --provider openrouter --model "deepseek/deepseek-chat" send "Task"` |
| Check pipeline status | `bash batch.sh status` |
| Run one poll + route cycle by hand | `bash batch.sh poll` |
| View recent completions | `bash batch.sh history` |
| View per-provider/per-model stats | `bash batch.sh stats` |
| View end-to-end latency and throughput | `bash batch.sh metrics` |
| View items needing review | `bash batch.sh escalations` |
| Launch interactive TUI | `bash batch.sh tui` |
| Run unit tests | `python3 test_batch_pipeline.py --unit` |

How it works: see `PIPELINE.md`. Metrics vs stats: see `METRICS.md`.

## Providers

- **Anthropic**: `ANTHROPIC_API_KEY`
- **OpenRouter**: `OPENROUTER_API_KEY` and `BATCH_PROVIDER=openrouter`; model IDs are sent exactly as written

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
BATCH_PROVIDER          anthropic (default) or openrouter
BATCH_MODEL             model name; unset = the provider's default
OPENROUTER_BATCH_MODEL  model override for OpenRouter
BATCH_DIR               where runtime data lives (default .batch-data/)
```

## Common issues

- **`ModuleNotFoundError`**: the dependencies are not in `venv/`; run `pip install -r requirements.txt` there.
- **Scheduled job does nothing**: read `.batch-data/logs/orchestrator.log`; cron needs the key in `.env`.
- **Batch seems stuck**: batch APIs can take up to 24 hours; check `bash batch.sh status` and `poll.log`.
