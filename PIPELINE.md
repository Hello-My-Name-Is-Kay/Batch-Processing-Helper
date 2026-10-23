# Multi-Provider Batch Pipeline

Asynchronous batch processing for LLM APIs — Anthropic, OpenRouter, and beyond.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      batch.sh / batch.fish                       │
│                     (CLI wrapper, dispatch)                      │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      batch-config.sh                             │
│              (provider, model, paths, API keys)                  │
└──────────┬──────────────────────────┬──────────────────────────┘
           │                          │
           ▼                          ▼
┌──────────────────────┐   ┌──────────────────────┐
│  batch-submit.py      │   │  batch-poll.py        │
│  (create batches)     │   │  (poll + fetch)       │
└──────────┬───────────┘   └──────────┬───────────┘
           │                          │
           ▼                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    providers/ abstraction layer                   │
│                                                                   │
│  ┌────────────────────┐   ┌────────────────────┐                 │
│  │ AnthropicProvider   │   │ OpenRouterProvider  │  ← add yours  │
│  │ (anthropic SDK)     │   │ (HTTP + JSONL)      │               │
│  └────────┬───────────┘   └────────┬───────────┘                 │
│           │                        │                             │
│           ▼                        ▼                             │
│  Anthropic Batch API        OpenRouter Batch API                 │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      batch-router.py                              │
│              (classify + route results to archive/escalate)      │
└─────────────────────────────────────────────────────────────────┘
```

## How it works

1. **Submit** a request via `batch.sh send` or `batch-submit.py`
   - Provider abstraction converts to provider-specific JSON format
   - Request gets a UUID
   - Submitted to the chosen provider's Batch API
   - Tracking file written to `requests/` with provider metadata

2. **Poll** (runs automatically every 2 minutes via cron/systemd)
   - Checks all pending batches (across all providers)
   - For each provider, uses the correct API to check status
   - When complete, fetches results and writes to `responses/`

3. **Route** (automatic, after poll)
   - Classifier (live API call) reads response
   - Classifies: text, question, error, action_needed, ready_to_commit
   - Routes to: archive, escalate, batch_again, live_model

4. **Escalations**
   - Results needing human decision written to `escalations/`
   - You see them when checking status
   - Decide action and file away

## Provider Architecture

### Provider Interface (`providers/base.py`)

Every provider must implement:

```python
class BatchProvider(ABC):
    def create_batch(self, requests: list[dict]) -> str:
        """Submit batch, return batch_id."""
        
    def retrieve_batch(self, batch_id: str) -> dict:
        """Get batch status. Return {id, status, ...}."""
        
    def get_results(self, batch_id: str) -> list[BatchResult]:
        """Fetch completed results."""
        
    def build_request(self, custom_id, user_message, ...) -> dict:
        """Build provider-specific request dict."""
        
    def get_provider_name(self) -> str:
        """Return provider name string."""
```

### Anthropic Provider (`providers/anthropic_provider.py`)

- Uses official `anthropic` Python SDK
- Request format: `{custom_id, params: {model, max_tokens, system, messages}}`
- API key: `ANTHROPIC_API_KEY`
- Endpoint: Anthropic Batch API (`claude.beta.messages.batches`)

### OpenRouter Provider (`providers/openrouter_provider.py`)

- Uses direct HTTP requests (`requests` library)
- Request format: OpenAI-compatible JSONL (`{custom_id, method, url, body}`)
- API key: `OPENROUTER_API_KEY`
- Endpoint: `https://openrouter.ai/api/v1/batch`
- Supports 200+ models from all major providers

### How to Add a New Provider

1. Create `providers/myprovider.py`:

```python
from .base import BatchProvider, BatchResult, BatchStatus

class MyProvider(BatchProvider):
    def get_provider_name(self): return "myprovider"
    
    def build_request(self, custom_id, user_message, system_message=None, 
                      model=None, max_tokens=2048, temperature=0.0):
        return { ... provider format ... }
    
    def create_batch(self, requests):
        # Submit to MyProvider's batch API
        return batch_id
    
    def retrieve_batch(self, batch_id):
        return {"id": batch_id, "status": ..., ...}
    
    def get_results(self, batch_id):
        return [BatchResult(...)]
```

2. Register in `providers/__init__.py`:
```python
from .myprovider import MyProvider
_PROVIDERS["myprovider"] = MyProvider
```

3. Add config to `batch-config.sh`:
```bash
export MYPROVIDER_API_KEY="${MYPROVIDER_API_KEY:-}"
```

## Pipeline Data Flow

### Submission (batch-submit.py)
```
User message
  → build_request() converts to provider format
  → Provider.create_batch() → API returns batch_id
  → Write tracking file {custom_id, batch_id, provider, ...}
  → Update .batch-state with {batch_id: {custom_id, provider, status, ...}}
```

### Polling (batch-poll.py)
```
Read .batch-state
  → Group by provider
  → For each pending batch:
    → Provider.retrieve_batch(batch_id)
    → If completed: Provider.get_results(batch_id)
    → Write response file → Update .batch-state
```

### Routing (batch-router.py)
```
Read response file
  → Send content to classifier (live API via provider)
  → Parse JSON classification
  → Route decision:
    'archive'  → Write .done file, remove .result
    'escalate' → Write .escalate file
    'batch_again' → Re-submit as new batch
```

## State File Format

The `.batch-state` file tracks all batches across providers:

```json
{
  "anthro_batch_01abc...": {
    "custom_id": "uuid-here",
    "provider": "anthropic",
    "submitted_at": "2026-01-15T10:30:00",
    "submitted_at_unix": 1705312200.0,
    "status": "completed",
    "model": "claude-haiku-4-5-20251001",
    "completed_at": "2026-01-15T10:45:00",
    "completed_at_unix": 1705313100.0,
    "latency_seconds": 900.0,
    "latency_minutes": 15.0
  },
  "batch_xyz789...": {
    "custom_id": "uuid-here",
    "provider": "openrouter",
    "submitted_at": "2026-01-15T11:00:00",
    "submitted_at_unix": 1705314000.0,
    "status": "running",
    "model": "openai/gpt-4o"
  }
}
```

## Provider-Specific Models

### Anthropic models
```
claude-haiku-4-5-20251001    (default, cheapest)
claude-sonnet-4-20250514     (best for complex work)
claude-3-opus-20240229       (heaviest, deprecated)
```

### OpenRouter models (200+ available)
```
anthropic/claude-3.5-sonnet       # Claude via OpenRouter
anthropic/claude-3.5-haiku        # Cheaper Claude
openai/gpt-4o                     # GPT-4o
openai/gpt-4o-mini                # Cheaper GPT-4o
google/gemini-2.0-flash-001       # Gemini Flash
google/gemini-2.0-pro-001         # Gemini Pro
meta-llama/llama-3.3-70b-instruct # Llama 3
mistralai/mistral-large-2411      # Mistral
deepseek/deepseek-chat            # DeepSeek
```

See all models: https://openrouter.ai/models

## Request Matching

Every request gets a UUID (`custom_id`). Batch API returns results unordered, but matched via `custom_id` → `request_id` → tracking file. The `provider` field ensures we use the correct API for polling.

## Routing Decisions

**Classifications:**
- **text** — plain output, archive it
- **question** — needs clarification, escalate to user
- **error** — batch failed, escalate
- **action_needed** — requires human decision, escalate
- **ready_to_commit** — work complete, escalate for approval

**Routes:**
- **archive** — task done, move to completed
- **escalate** — needs human review
- **batch_again** — ready for next async batch step
- **live_model** — needs immediate response

## Logs

All logs include provider context:
```bash
tail -f logs/orchestrator.log
tail -f logs/poll.log        # Shows [anthropic] or [openrouter] tags
tail -f logs/router.log      # Shows provider of classified result
```

## Disable

Remove cron job:
```bash
crontab -e
# Delete the batch-orchestrator.sh line
```

Or just stop sending requests; the pipeline will go idle.