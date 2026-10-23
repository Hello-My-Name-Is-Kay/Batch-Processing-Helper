# Known issues and limits

What is not done or not verified. Fixed problems are in the git history and in [AUDIT.md](AUDIT.md).

## Not verified against the real services

The test suite uses fake providers and mocked HTTP, so none of this has been run against live APIs in this repository:

- A full Anthropic batch (submit, poll, collect, route) and a full OpenRouter batch. The one live test, `python3 test_batch_pipeline.py --live`, needs `OPENROUTER_API_KEY` and is skipped without it.
- OpenRouter model IDs are sent exactly as written, with no `:batch` suffix, following OpenRouter's batch documentation. If a live call rejects a model, try passing it with the suffix (`--model vendor/model:batch`).
- The cron job on a real machine, the `fish` wrapper, and the TUI in a real terminal (it is tested headless).
- The GitHub Actions workflow (`.github/workflows/ci.yml`) has not run on GitHub yet. Python 3.12 and Linux have not been run locally; the suite has been run on macOS with Python 3.9 and 3.15.

## Limits

- **No retries.** A transient provider error (network, 429, 5xx) is logged and the batch is asked about again on the next poll; submitting is not retried and does not back off.
- **Anthropic client has no explicit timeout.** It uses the SDK's defaults. OpenRouter calls time out after 60 s.
- **No escalation notification.** Escalations are files; you find them with `bash batch.sh escalations`, the TUI or the logs. There is no command to mark one resolved; delete the file.
- **Anthropic cost is not reported.** The batch API returns tokens, not cost, so Anthropic history entries have tokens only.
- **Router cost.** Every result gets one live classification call, and the router uses `BATCH_PROVIDER` for it, whichever provider ran the batch.
- **OpenRouter results.** The parser reads the first choice of each chat completion; tool calls or other response shapes are not handled.
- **Locking is advisory and POSIX-only.** The state lock uses `fcntl.flock`, so Windows is not supported and a state file on a network filesystem may not be protected.
- **No LICENSE file** and no `systemd/` units yet.

## Testing gaps

Network interruption during a poll, a full disk, very large results, rate limiting, and OpenRouter batches with slow models are not covered by tests.

## Reporting a problem

Add an entry here with: what you did, what you expected, what happened, and any workaround.
