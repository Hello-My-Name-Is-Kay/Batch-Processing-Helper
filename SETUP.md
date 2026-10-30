# Setup, troubleshooting and advanced use

Installing, configuring and scheduling are covered in the [README](README.md). This page is for when something does not work, and for pointing the pipeline at your own project.

## Check your setup

```bash
bash batch.sh providers                  # which provider is selected
bash batch-orchestrator.sh status        # counts, and any escalations
python3 test_batch_pipeline.py --unit    # offline tests, no API calls
```

To see whether a key is set without printing it:

```bash
[ -n "$ANTHROPIC_API_KEY" ] && echo "Anthropic key set" || echo "Anthropic key missing"
```

## Troubleshooting

**`ModuleNotFoundError: No module named 'anthropic'` (or `requests`, `textual`)**
Install the dependencies into the project's virtual environment: `source venv/bin/activate && pip install -r requirements.txt`. `batch.sh` and the cron job use `venv/bin/python3` automatically when `venv/` exists. A provider's package is only needed when you use that provider.

**`ANTHROPIC_API_KEY is required` / `OPENROUTER_API_KEY is required` / `GROQ_API_KEY is required`**
Set the key for the provider you selected, either as an environment variable or in `.env` (see `.env.example`). Cron does not see your shell's exports, so a scheduled job needs the key in `.env`.

**The cron job is installed but nothing happens**
Read `.batch-data/logs/orchestrator.log`: Python's errors from the poll and router are written there. Then check `crontab -l`, that `.env` holds the key, and that `venv/` exists (or set `BATCH_PYTHON`).

**No results after 10 minutes**
Batch APIs can take up to 24 hours. Run `bash batch.sh status` and `tail .batch-data/logs/poll.log`. A batch marked `failed` keeps the provider's error in its `error` field (`bash batch.sh status --json`).

**A result is waiting to be routed but nothing routes it**
`bash batch.sh poll` runs the poller and the router once. To route one file by hand: `python3 batch-router.py .batch-data/responses/<id>.result`. To classify an already routed result again, pass its `<id>.routed` file the same way.

**Escalations**
Each one is a file, `.batch-data/escalations/<request>.escalate`. `bash batch.sh escalations` prints them and the TUI lists them. Delete the file when you have dealt with it.

**`.batch-state.corrupt-<time>` appeared**
The state file was not valid JSON, so it was moved aside instead of being overwritten. Compare it with the new `.batch-state` and copy back any batch you still need.

## Using it for your own project

- **Where data lives.** Set `BATCH_DIR` to keep runtime data outside the checkout.
- **Routing context.** Set `PROJECT_CONTEXT_FILE`, or `PROJECT_DIR` (the router then reads the first of `docs/handoff.md`, `HANDOFF.md`, `README.md`, `CONTEXT.md`). The first 2,000 characters are sent to the classifier's provider with every result, so do not point it at private files.
- **Keys and overrides.** Keep them in `.env` (git-ignored). Values already set in the environment win over the file.

## macOS

Cron works. A `launchd` agent also works but is less reliable for timers; if you use one, run `batch-orchestrator.sh poll` from it.
