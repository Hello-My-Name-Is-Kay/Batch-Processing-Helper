# Freedom-OS Batch Pipeline

Asynchronous batch processing for Freedom-OS tasks using Anthropic Batch API.

## How it works

1. **Submit** a request via `batch-send.sh` or `batch-submit.py`
   - Request gets a UUID
   - Submitted to Anthropic Batch API
   - Tracking file written to `requests/`

2. **Poll** (runs automatically every 2 minutes via cron)
   - Checks batch status via API
   - When complete, writes result to `responses/`

3. **Route** (automatic, after poll)
   - Haiku classifier reads response
   - Classifies: text, question, error, action_needed, ready_to_commit
   - Routes to: archive, escalate, batch_again, live_model

4. **Escalations**
   - Results needing human decision written to `escalations/`
   - You see them when checking status
   - Decide action and file away

## Quick start

```bash
# Initialize and set up cron
cd ~/.claude/batch-pipeline/freedom-os
bash batch-orchestrator.sh setup-cron

# Send a request
bash batch-send.sh 'Run the ladder tests and report results'

# Check status anytime
bash batch-orchestrator.sh status

# View escalations
bash batch-orchestrator.sh escalations
```

## File structure

```
~/.claude/batch-pipeline/freedom-os/
├── requests/        # Outgoing batch requests (UUID.jsonl)
├── responses/       # Completed batch results (UUID.result)
├── completed/       # Processed & archived (UUID.done)
├── escalations/     # Needs human decision (UUID.escalate)
├── logs/            # Pipeline logs
├── .batch-state     # Batch ID tracking (JSON)
├── batch-config.sh  # Configuration
├── batch-submit.py  # Submit to batch API
├── batch-poll.py    # Poll for completion
├── batch-router.py  # Route results
├── batch-orchestrator.sh  # Main pipeline
└── batch-send.sh    # User-friendly sender
```

## Configuration

Edit `batch-config.sh` to change:
- `BATCH_POLL_INTERVAL` — how often cron checks (default: 120s)
- `BATCH_MODEL` — which model runs the work (default: claude-haiku-4-5-20251001)
- `ROUTER_MODEL` — which model classifies results (default: haiku)

## Request matching

Every request gets a UUID (`custom_id`). Batch API returns results unordered, but matched via custom_id → request_id → tracking file.

## Routing decisions

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
- **live_model** — needs immediate response (fallback to live Claude)

## Logs

Check pipeline activity:
```bash
tail -f logs/orchestrator.log
tail -f logs/poll.log
tail -f logs/router.log
```

## Disable

Remove cron job:
```bash
crontab -e
# Delete the batch-orchestrator.sh line
```

Or just stop sending requests; the pipeline will go idle.
