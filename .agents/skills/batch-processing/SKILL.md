---
name: batch-processing
description: Multi-provider async batch processing for LLMs (Anthropic, OpenRouter). Use when submitting, polling, tracking, or analyzing batch LLM requests and their cost/latency metrics.
---

# Batch Processing Helper

Project at `{{ cwd | default("Batch-Processing-Helper") }}`. Requires `venv/` and API keys.

## Quick reference

| Task | Command |
|------|---------|
| Submit a batch request | `bash batch.sh send "Your task"` |
| Submit via OpenRouter with model | `bash batch.sh --provider openrouter --model "deepseek/deepseek-v4.1-flash" send "Task"` |
| Check pipeline status | `bash batch.sh status` |
| View recent completions | `bash batch.sh history` |
| View per-provider/per-model stats | `bash batch.sh stats` |
| View items needing review | `bash batch.sh escalations` |
| Launch interactive TUI | `bash batch.sh tui` |
| Run unit tests | `python3 test_batch_pipeline.py --unit` |

## Architecture

```
User Task → Provider Abstraction Layer → Batch API (Anthropic/OpenRouter)
                                               ↓ (async, minutes/hours)
         LLM Router ←─────────────── Completed results
            ↓
     Archive / Escalate / Re-queue
            ↓
     📊 History Database ←── every completion logged
```

## Providers

- **Anthropic**: `export ANTHROPIC_API_KEY="sk-..."`
- **OpenRouter**: `export OPENROUTER_API_KEY="sk-..."` + `export BATCH_PROVIDER=openrouter`
- Model gets `:batch` suffix appended automatically for OpenRouter

## Project structure key files

| File | Purpose |
|------|---------|
| `batch-submit.py` | Submit requests |
| `batch-poll.py` | Poll for completion + log history |
| `batch-router.py` | Route results via LLM |
| `batch_history.py` | Persistent history & aggregates |
| `batch_tui.py` | Interactive terminal UI |
| `test_batch_pipeline.py` | Test suite (21 tests) |
| `batch-mcp.py` | MCP server (Claude Desktop, etc.) |
| `providers/` | Provider abstraction layer |
| `.batch-data/history/` | Persistent history database |

## Key env vars

```
BATCH_PROVIDER     — anthropic (default) or openrouter
BATCH_MODEL        — model name (default: claude-haiku-4-5-20251001)
OPENROUTER_BATCH_MODEL — model override for OpenRouter
```

## Common issues

- **"No module named batch_history"**: Ensure `venv/` is active
- **OpenRouter batch stuck**: Check at openrouter.ai/batches — processing time varies by provider backend
- **Router uses batch instead of live**: Ensure `chat_complete()` is implemented for your provider