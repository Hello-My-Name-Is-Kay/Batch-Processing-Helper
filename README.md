# Claude Batch Processing

Asynchronous batch processing for Claude API using the Anthropic Batch API + systemd timers.

**Cost:** ~50% cheaper than live API. **Time:** Batches process async (hours, not minutes). **Use case:** Long-running tasks, non-urgent work, cost-optimized workflows.

## What's Included

- **Batch submission** (`batch-submit.py`) — Queue requests to Anthropic Batch API
- **Polling** (`batch-poll.py`) — Periodic checks for completed batches
- **Smart routing** (`batch-router.py`) — Haiku classifier routes results to archive, escalate, or queue next batch
- **CLI wrappers** (`batch.sh`, `batch.fish`) — Easy commands to submit, check status, view escalations
- **Systemd integration** — Automatic polling every 2 minutes (Linux/macOS)
- **Logging** — Full audit trail of all operations

## Quick Start

```bash
# 1. Clone
git clone <repo> ~/Projects/tools/Claude-Batching
cd ~/Projects/tools/Claude-Batching

# 2. Setup venv
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Set API key
export ANTHROPIC_API_KEY="sk-..."

# 4. Send work
bash batch.sh send "Write a summary of my project"

# 5. Check status
bash batch.sh status

# Results appear in ~5-30 minutes (depending on queue)
```

## Commands

```bash
# Submit a batch request
bash batch.sh send "Your task description"

# Check pipeline status (queued, processing, escalations)
bash batch.sh status

# View items needing human decision
bash batch.sh escalations

# View logs
bash batch.sh logs
```

## How It Works

```
Your task
    ↓
batch.sh send "task"
    ↓
Request queued (UUID-tracked)
    ↓
Systemd timer polls every 2 minutes
    ↓
Batch API completes work
    ↓
Haiku classifier routes result:
  • Archive (task done) → completed/
  • Escalate (needs your decision) → escalations/
  • Queue next (more steps) → requests/ (loop)
    ↓
You check: bash batch.sh status
    ↓
If escalation: review and decide
```

## File Structure

```
Claude-Batching/
├── batch.sh              # Main command (use this)
├── batch.fish            # Fish shell version
├── batch-submit.py       # Submit to Batch API
├── batch-poll.py         # Poll for results
├── batch-router.py       # Route/classify results
├── batch-orchestrator.sh # Systemd integration
├── batch-config.sh       # Configuration
├── requests/             # Queued requests (UUID.jsonl)
├── responses/            # Completed results (UUID.result)
├── escalations/          # Awaiting decision (UUID.escalate)
├── completed/            # Finished tasks (UUID.done)
├── logs/                 # Audit logs
├── SETUP.md              # Installation guide
├── PIPELINE.md           # Full technical docs
└── requirements.txt      # Python deps (anthropic)
```

## Status Line

After setup, you can show pipeline status in your shell prompt:

```fish
# Add to ~/.config/fish/config.fish (fish shell)
function fish_prompt
  set -l status_text ""
  set -l req (find ~/.claude/batch-pipeline/freedom-os/requests -name "*.jsonl" 2>/dev/null | wc -l)
  set -l esc (find ~/.claude/batch-pipeline/freedom-os/escalations -name "*.escalate" 2>/dev/null | wc -l)
  
  if test $esc -gt 0
    set status_text "⚠ Batch:$esc "
  else if test $req -gt 0
    set status_text "◌ Batch:$req "
  end
  
  echo -n $status_text
  # ... rest of prompt
end
```

## Environment Setup

### Linux (systemd)

```bash
# Install timer
cp systemd/*.service ~/.config/systemd/user/
cp systemd/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable freedom-batch-poll.timer
systemctl --user start freedom-batch-poll.timer
```

### macOS (launchd)

See `SETUP.md` for launchd configuration.

### Manual polling

If no systemd/launchd, poll manually:

```bash
# Check once
bash batch.sh poll

# Or add to crontab (every 2 min)
*/2 * * * * cd ~/Projects/tools/Claude-Batching && bash batch.sh poll
```

## Use Cases

**Freedom-OS project:** Async VM tests, image builds, ladder reviews
```bash
bash batch.sh send "Run test-ladder.sh --accel kvm; report pass/fail"
bash batch.sh send "Build image without firmware; test in VM; report"
bash batch.sh send "Review candidate ladder for incomplete patterns"
```

**General:** Long-running analysis, batch processing
```bash
bash batch.sh send "Analyze 1000 files for security issues"
bash batch.sh send "Generate documentation for my codebase"
bash batch.sh send "Run comprehensive code review on my PR"
```

## Cost Savings

| Task | Live API | Batch API | Savings |
|------|----------|-----------|---------|
| 1 hr analysis | $0.30 | $0.15 | 50% |
| 10 image builds | $3.00 | $1.50 | 50% |
| Nightly review | $2.00 | $1.00 | 50% |

**Time trade-off:** Batch takes hours (background), live takes minutes (foreground).

## Logs & Audit

Every operation logged to `logs/`:

```bash
tail logs/orchestrator.log  # Main pipeline activity
tail logs/poll.log          # Polling results
tail logs/router.log        # Routing decisions
```

Each request tracked with UUID for full audit trail.

## Troubleshooting

**See `SETUP.md` for common issues and fixes.**

Quick checks:
```bash
# Is the timer running?
systemctl --user status freedom-batch-poll.timer

# API key set?
echo $ANTHROPIC_API_KEY

# Any requests queued?
ls requests/

# View a completed result
cat completed/*.done | jq .
```

## Customization

Edit `batch-config.sh`:

```bash
export BATCH_MODEL="claude-opus-5-5"        # Use bigger model for complex work
export ROUTER_MODEL="claude-haiku-4-5-20251001"
export BATCH_POLL_INTERVAL=60               # Poll more frequently (costs more)
```

Edit `batch-router.py` to customize routing logic (what counts as "done" vs. "escalate").

## See Also

- `SETUP.md` — Full installation and advanced configuration
- `PIPELINE.md` — Technical deep dive (Batch API mechanics, retry logic, state management)
- Anthropic Batch API docs — https://docs.anthropic.com/en/docs/build-a-bot/batch-api

## License

Same as parent project.

---

**Ready to save 50% on async work? Start with `SETUP.md`.**
