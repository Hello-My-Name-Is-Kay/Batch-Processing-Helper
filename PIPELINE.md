# How the pipeline works

Internals for people who want to read or extend the code. For installing and using it, see the [README](README.md).

## Stages

```
batch.sh send / send-file
        │  batch-submit.py: check ids, key and folders → build requests → create ONE batch
        ▼
   provider batch API  (Anthropic or OpenRouter)
        │
        │  cron → batch-orchestrator.sh poll
        ▼
   batch-poll.py: ask about every unfinished batch → download results → record history
        │          writes responses/<id>.result
        ▼
   batch-router.py: classify each result with a live LLM call
                    → completed/<request>.done        (archived)
                    → escalations/<request>.escalate  (needs a person)
                    → responses/<id>.result is renamed <id>.routed
```

| Folder (under `.batch-data/`) | Holds |
|---|---|
| `requests/` | One tracking file per submission: `<id>.jsonl` (a single JSON object) |
| `responses/` | `<id>.result` waiting to be routed, then `<id>.routed` |
| `completed/` | `<request>.done`: archive record of a routed result |
| `escalations/` | `<request>.escalate`: result plus the classifier's verdict |
| `history/` | `history.jsonl`: one line per collected batch |
| `logs/` | `orchestrator.log`, `poll.log`, `router.log` |
| `.batch-state` | Every batch and its status (below) |

`<id>` is the batch's tracking id; each request inside a batch has its own `<request>` id (the same as `<id>` for a single prompt, `<id>-0000`, `<id>-0001`, … when a batch holds several).

## State file

`.batch-state` maps provider batch ids to their status:

```json
{
  "msgbatch_01abc...": {
    "custom_id": "6f1c...",
    "provider": "anthropic",
    "model": "claude-haiku-4-5-20251001",
    "status": "completed",
    "submitted_at_unix": 1705312200.0,
    "completed_at_unix": 1705313100.0,
    "latency_seconds": 900.0,
    "request_counts": {"total": 3, "completed": 3, "failed": 0},
    "custom_ids": ["6f1c...-0000", "6f1c...-0001", "6f1c...-0002"],
    "agent": "pi-session-abc"
  }
}
```

`status` is `running` until the poller sees the batch finish, then `completed`, `failed` or `cancelled`. Finished batches are not asked about again. `custom_id` is the batch's tracking id (it names the `.result` file); `custom_ids` lists the id of every request in the batch; `agent` is only present when the batch was submitted with `--agent`.

Every write goes through `batch_common.update_state()`: it takes a file lock, re-reads the file, applies the change and replaces the file atomically. The poller keeps its own copy while it talks to the providers and merges only what it changed, so a `send` that happens during a poll is not lost. A state file that is not valid JSON is moved to `.batch-state.corrupt-<time>`. The lock is `fcntl`-based (Linux and macOS).

## Routing rules

The classifier returns a classification and a route as JSON. The result text is fenced as untrusted data in the prompt, and the pipeline applies its own rules on top:

- Only `archive` and `escalate` exist. Any other route is escalated.
- Only a result classified `text` is archived. If the classifier says `archive` for anything else (`question`, `error`, `action_needed`, `ready_to_commit`), it is escalated and the original route is kept in the escalation as `original_route`.
- If the classification call fails, or the reply cannot be parsed, the result is escalated with the reason.
- A batch with several requests is classified one result at a time.

## Provider interface

`providers/base.py` defines `BatchProvider`. A provider implements:

| Method | Purpose |
|---|---|
| `get_provider_name()` | `"anthropic"`, `"openrouter"`, … |
| `default_model()` | Model used when none is given (optional; `None` if the provider has no default) |
| `build_request(custom_id, user_message, system_message, model, ...)` | Provider-specific request dict |
| `create_batch(requests)` | Submit; return the batch id |
| `retrieve_batch(batch_id)` | Return `{id, status, raw_status, request_counts, created_at, ended_at, ...}`; `status` is a `BatchStatus` value; times are unix seconds |
| `get_results(batch_id)` | List of `BatchResult` (`status` is `completed` or `failed`) |
| `chat_complete(messages, model, ...)` | Live call used by the router; raises on API errors |

`retrieve_batch()` may also return `model`, `usage` (token counts and cost) and `provider_backend` for the history; when `usage` is missing the poller sums the tokens from the results.

### Adding a provider

1. Create `providers/myprovider.py` with a `BatchProvider` subclass (`providers/openrouter_provider.py` is a complete example).
2. Register it in `providers/__init__.py` as `module name` and `class name`; the module is imported only when the provider is used:
   ```python
   _PROVIDERS["myprovider"] = (".myprovider", "MyProvider")
   ```
3. Add its environment variables to `batch-config.sh` (and `.env.example`).

## Logs

Every line carries the provider:

```bash
tail -f .batch-data/logs/orchestrator.log   # cron runs and Python errors
tail -f .batch-data/logs/poll.log           # [anthropic] / [openrouter] batch events
tail -f .batch-data/logs/router.log         # one line per routed result
```

## Turning it off

Remove the cron entry with `crontab -e` (delete the line that runs this project's `batch-orchestrator.sh`), or just stop sending requests; the pipeline goes idle.
