# Batch Processing Helper

Async batch-processing pipeline for LLM work. It submits tasks to the Anthropic or OpenRouter batch APIs, polls for results in the background, classifies each result with an LLM (archive or escalate), and records cost and latency for every batch.

![The terminal UI (bash batch.sh tui)](docs/tui.gif)

## Why

Batch APIs are cheaper than live calls and suit work where nobody is waiting for the answer: evaluations, labeling, large prompt runs. The trade-off is operational: you have to submit, poll, collect, check and keep track of what came back. This project handles that loop so you can send a task with one command and review only the results that need a person.

## How it works

```mermaid
flowchart LR
    A[batch.sh send] --> B[Provider abstraction]
    B --> C[Batch API: Anthropic or OpenRouter]
    C --> D[Poller: cron, every 120 s]
    D --> E[Router: LLM classifier]
    E -->|task complete| F[completed/]
    E -->|needs a human| G[escalations/]
    D --> I[history.jsonl]
```

1. **Submit.** `batch.sh send` builds one request per message and submits them together, as one batch, to the selected provider's batch API.
2. **Poll.** A scheduled job checks batch status every 2 minutes by default (`BATCH_POLL_INTERVAL`, applied when you install the cron job) and downloads finished results.
3. **Route.** An LLM classifier labels each result as `text`, `question`, `error` or `action_needed`. Results are archived or escalated to a human; any other route the classifier returns is escalated too. A routed result is kept as `<id>.routed` in `responses/` and is not classified again.
4. **Log.** Every completed batch is appended to a history file with provider, model, latency, token counts and cost.

Routing is automatic, but escalated items wait for a person to review them.

## Features

- Provider abstraction with two implementations today: Anthropic and OpenRouter
- Background polling through cron
- LLM-based result router with archive and escalate outcomes
- Many requests per batch: `send` takes several messages, `send-file` a file of prompts, `--from-stdin` a pipe; the router handles each result on its own
- A unique id for every request (`<batch id>-0000`, `-0001`, …), all of them kept in the state file, the tracking file and the history
- Agent ownership: `--agent NAME` tags a batch with the agent or session that owns it, so several agents can share one pipeline
- Pre-submit review: `--dry-run` shows the batch (requests, ids, model, agent) without sending or writing anything
- CLI (`batch.sh`, with a Fish wrapper) and a five-tab terminal UI built with Textual
- Per-batch history with per-provider and per-model aggregates (latency, tokens, cost)
- Unit tests that run offline, plus optional live tests

## Supported providers

| Provider | API used | Default model | Notes |
|---|---|---|---|
| Anthropic | Message Batches API | `claude-haiku-4-5-20251001` (`BATCH_MODEL`) | Claude models only |
| OpenRouter | OpenRouter Batch API | `OPENROUTER_BATCH_MODEL`, falling back to `BATCH_MODEL`, then `deepseek/deepseek-v4.1-flash` | Only models that offer a batch variant. The model ID is sent exactly as written. |

Example OpenRouter model IDs: `anthropic/claude-3.5-haiku`, `openai/gpt-4o`, `google/gemini-2.0-flash-001`, `meta-llama/llama-3.3-70b-instruct`, `deepseek/deepseek-v4.1-flash`. Model availability changes often, so check OpenRouter's models page filtered by batch support before choosing one.

## Quick start

Requirements: Linux or macOS, Python 3.9 or newer with `venv` (tested on 3.9 and 3.15), an API key for one provider, and optionally `jq` (pretty-prints the output of `send`).

```bash
git clone https://github.com/Hello-My-Name-Is-Kay/Batch-Processing-Helper.git
cd Batch-Processing-Helper
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` installs the packages for both providers; each one is only imported when its provider is selected.

Set a key for one provider (never commit keys):

```bash
# Anthropic (default provider)
export ANTHROPIC_API_KEY="sk-..."

# or OpenRouter
export OPENROUTER_API_KEY="sk-..."
export BATCH_PROVIDER=openrouter
```

Or keep them in a git-ignored `.env` file, which is also what the scheduled job reads (see [Scheduling](#scheduling)):

```bash
cp .env.example .env    # then edit it
chmod 600 .env
```

Send a task and check on it:

```bash
bash batch.sh send "Summarize the main trade-offs of batch APIs in three bullets"
bash batch.sh status
```

To send several prompts as ONE batch, list them, or put one prompt per line in a file (or JSON Lines with `message`, `system` and `id` fields):

```bash
bash batch.sh send "Task 1" "Task 2" "Task 3"
bash batch.sh send-file prompts.txt
cat tasks.txt | python3 batch-submit.py --from-stdin
```

Each request gets its own id (`<batch id>-0000`, `<batch id>-0001`, …) and its own result. Add `--agent NAME` to record who owns the batch, and `--dry-run` to preview it first:

```bash
bash batch.sh --agent "my-session" --dry-run send "Task 1" "Task 2"
```

Finished batches are collected by the scheduler (see [Scheduling](#scheduling)). Then review them:

```bash
bash batch.sh history
bash batch.sh stats
```

## Commands

| Command | What it does |
|---|---|
| `bash batch.sh send "task" ["task" ...]` | Submit one or more tasks as one batch to the default provider |
| `bash batch.sh send-file prompts.txt` | Submit every prompt in a file as one batch |
| `bash batch.sh --agent NAME send "task"` | Record which agent or session owns the batch |
| `bash batch.sh --system "text" send "task"` | Set the system message for the requests |
| `bash batch.sh --dry-run send "task"` | Preview the batch without sending or writing anything |
| `bash batch.sh --provider openrouter --model "<model>" send "task"` | Submit with a specific provider and model |
| `bash batch.sh status` | Show running, collected, awaiting-routing, escalated and archived counts |
| `bash batch.sh escalations` | List items that need a human decision |
| `bash batch.sh history [N]` | Show the last N completed batches (default 10) |
| `bash batch.sh stats` | Provider-side latency, tokens and cost per provider and per model |
| `bash batch.sh metrics` | End-to-end latency, routing time and throughput |
| `bash batch.sh logs` | View pipeline logs |
| `bash batch.sh providers` | List available providers |
| `bash batch.sh tui` | Open the terminal UI |

## Terminal UI

`bash batch.sh tui` opens a Textual interface that refreshes every 10 seconds.

| Key | Tab | Shows |
|---|---|---|
| `1` | Dashboard | Pipeline overview, counts, recent history, per-provider aggregates |
| `2` | Batches | All tracked batches with status, provider, model, age and latency |
| `3` | History | Completed batches plus per-provider and per-model stats |
| `4` | Escalations | Items waiting for human review |
| `5` | Logs | Tail of `poll.log` and `router.log` |

Press `r` to refresh and `q` to quit.

## Configuration

Set these as environment variables or edit `batch-config.sh`.

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | For Anthropic | Anthropic API key |
| `OPENROUTER_API_KEY` | For OpenRouter | OpenRouter API key |
| `BATCH_PROVIDER` | No | `anthropic` (default) or `openrouter` |
| `BATCH_MODEL` | No | Batch model (provider-specific). Unset: the provider's default |
| `OPENROUTER_BATCH_MODEL` | No | OpenRouter model, defaults to `BATCH_MODEL` |
| `OPENROUTER_REFERER`, `OPENROUTER_APP_NAME` | No | Attribution headers for OpenRouter |
| `ROUTER_MODEL` | No | Model used for the routing classifier. Unset: `claude-haiku-4-5-20251001` on Anthropic, the provider default on OpenRouter |
| `OPENROUTER_ROUTER_MODEL` | No | Routing model on OpenRouter, takes precedence over `ROUTER_MODEL` |
| `BATCH_POLL_INTERVAL` | No | Seconds between polls (default 120). Applied by `setup-cron`, rounded up to whole minutes |
| `BATCH_DIR` | No | Base directory for pipeline files |
| `BATCH_ENV_FILE` | No | Path of the `.env` file to load (default: `.env` in the project folder) |
| `BATCH_PYTHON` | No | Python interpreter to use (default: `venv/bin/python3` if present, else `python3`) |

`batch-config.sh` derives the request, response, completed, escalation, log and state paths from `BATCH_DIR`. Runtime data lives in `.batch-data/` and is git-ignored. The Python scripts use the same defaults when run on their own.

`.env` holds plain `KEY=VALUE` lines (see `.env.example`). It is read, not executed, and anything already set in your environment wins over it.

To check that a key is set without printing it:

```bash
[ -n "$ANTHROPIC_API_KEY" ] && echo "Anthropic key set" || echo "Anthropic key missing"
```

## Scheduling

Polling runs from cron. `setup-cron` installs the job, using `BATCH_POLL_INTERVAL` (default every 2 minutes). Running it again updates this project's entry and leaves your other cron entries alone.

```bash
bash batch-orchestrator.sh setup-cron
crontab -l | grep batch-orchestrator
```

Cron does not inherit your shell's exports, so put your API key in `.env` (see above). The job uses the project's `venv/` automatically, and any error from the poll or router is written to `.batch-data/logs/orchestrator.log`.

systemd unit files are not included in this repository yet, so use cron on both Linux and macOS. On macOS a `launchd` agent also works but is less reliable for timers.

## Cost and latency

Both Anthropic and OpenRouter price batch calls at a discount to live calls, typically about 50%. The exact price is listed on each model's page, so check it before estimating savings.

A single smoke test is the only measurement recorded so far: 3 requests, 352 tokens, about $0.000034 using DeepSeek through OpenRouter. That is too small to draw savings conclusions from. To measure your own workload:

```bash
bash batch.sh history 50
bash batch.sh stats
```

`stats` reports latency (min, mean, max), token counts and cost per provider and per model.

History is stored in `.batch-data/history/`: `history.jsonl` is an append-only log with one JSON entry per collected batch (batch ID, provider, model, latency, request counts, tokens, cost). Aggregates are computed from it when asked for. From Python, `read_history()` returns entries newest first and `get_aggregates()` returns `by_provider` and `by_model` stats. [METRICS.md](METRICS.md) explains how `metrics` and `stats` differ.

## Limitations

- **Latency.** Batches usually finish in minutes but can take up to 24 hours. This is not for interactive use.
- **No cancellation.** OpenRouter batches cannot be cancelled once submitted, and results are deleted after 30 days.
- **OpenRouter constraints.** One model per batch, text and public image URLs only, no Zero Data Retention and no provider sorting.
- **Router cost.** Every result gets one small live LLM call to classify it, so a batch of N results costs N extra calls. If that call fails, the result is escalated with the error as the reason.
- **No retries.** Transient provider failures are not retried yet.
- **Platform support.** Tested on Linux. macOS works with cron.

See [ISSUES.md](ISSUES.md) for the full list of known issues.

## Adding a provider

1. Subclass `BatchProvider` (see `providers/base.py`) in a new file under `providers/`. Implement `get_provider_name`, `build_request`, `create_batch`, `retrieve_batch` and `get_results`.
2. Make `retrieve_batch()` return `model`, `usage` (prompt, completion and total tokens plus cost) and `request_counts` (total, completed, failed).
3. Register it in `providers/__init__.py` as a module name and class name: `_PROVIDERS["myprovider"] = (".myprovider", "MyProvider")`. The module is only imported when that provider is used.
4. Add any new environment variables to `batch-config.sh` and `.env.example`.

`providers/openrouter_provider.py` is a complete reference implementation.

## Tests

```bash
python3 test_batch_pipeline.py --unit                  # offline, no API calls
python3 test_batch_pipeline.py --live                  # needs OPENROUTER_API_KEY
python3 test_batch_pipeline.py                         # everything
python3 test_batch_pipeline.py --unit --filter P1-12   # only tests whose name contains the text
ruff check .                                           # lint (settings in pyproject.toml)
```

Unit tests run offline with fake providers. They cover the providers, the full submit → poll → route flow, the shell wrappers and cron setup, the state file, the router, history, the TUI (headless) and the MCP server. Live tests are skipped when no API key is set. On GitHub, `.github/workflows/ci.yml` runs `ruff check .` and `python test_batch_pipeline.py --unit` on Python 3.9 and 3.12 for every push to `main` and every pull request. Run `pip install ruff` to lint locally.

## Project layout

```
batch.sh, batch.fish        CLI wrappers
batch-submit.py             Submit requests
batch-poll.py               Poll batch status and collect results
batch-router.py             LLM result classifier and router
batch-status.py             Status view
batch-metrics.py            Provider metrics
batch_history.py            History and aggregates
batch_common.py             Shared folder defaults and atomic JSON writes
batch_tui.py                Terminal UI
docs/tui.gif                Terminal UI demo shown at the top of this README
batch-orchestrator.sh       Scheduling (cron)
batch-config.sh             Configuration (also loads .env)
.env.example                Template for API keys and overrides
providers/                  Provider abstraction and implementations
test_batch_pipeline.py      Tests
pyproject.toml              Project metadata, dependencies, lint settings
.github/workflows/ci.yml   CI: ruff and the unit tests on Python 3.9 and 3.12
.batch-data/                Runtime data (git-ignored)
PIPELINE.md, METRICS.md,
SETUP.md, ISSUES.md       Extra documentation (internals, metrics, troubleshooting, known issues)
AUDIT.md                    Audit report and fix log
```

## Roadmap

- Retry logic for transient provider failures
- Request timeouts for the Anthropic client
- Escalation notifications (Slack or webhook)
- Multi-step chains: re-queue a result as the next request
- Integration tests for all providers
- Provider performance comparison dashboard

## License

MIT. A `LICENSE` file has not been added to the repository yet.
