# Claude Batch Processing — Setup & Installation

Asynchronous batch processing for Claude Code using the Anthropic Batch API.

**What it is:** Infrastructure to submit work to the Anthropic Batch API, poll for results asynchronously, and route them (archive, escalate, or queue next step). ~50% cheaper than live API calls; ideal for async tasks.

## Quick Start

### 1. Clone and Install

```bash
git clone <repo> ~/Projects/tools/Claude-Batching
cd ~/Projects/tools/Claude-Batching
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Set Your API Key

```bash
export ANTHROPIC_API_KEY="sk-..."
# Or add to ~/.config/fish/config.fish (fish shell):
# set -gx ANTHROPIC_API_KEY "sk-..."
```

### 3. Test

```bash
source venv/bin/activate
bash batch.sh send "Test message"
bash batch.sh status
```

### 4. Install Systemd Timer (Linux/macOS with systemd)

```bash
# Copy service files
cp systemd/freedom-batch-poll.* ~/.config/systemd/user/

# Enable and start
systemctl --user daemon-reload
systemctl --user enable freedom-batch-poll.timer
systemctl --user start freedom-batch-poll.timer

# Check status
systemctl --user status freedom-batch-poll.timer
```

## Usage

**Submit work:**
```bash
bash batch.sh send "Describe your task here"
```

**Check status:**
```bash
bash batch.sh status
```

**View escalations (items needing your decision):**
```bash
bash batch.sh escalations
```

**View logs:**
```bash
tail logs/orchestrator.log
tail logs/poll.log
```

## How It Works

1. **Submit:** `batch send` → request gets UUID → submitted to Anthropic Batch API
2. **Poll:** Systemd timer (every 2 min) → checks for completed batches
3. **Route:** Haiku classifier reads results → decides: archive, escalate, or queue next batch
4. **Escalations:** Items needing human decision in `escalations/` folder

## File Structure

```
Claude-Batching/
├── batch-submit.py         # Submit requests to Batch API
├── batch-poll.py           # Poll for completions
├── batch-router.py         # Classify and route results
├── batch.sh                # Bash wrapper (main command)
├── batch.fish              # Fish shell wrapper (alternative)
├── batch-config.sh         # Configuration (edit as needed)
├── batch-orchestrator.sh   # Orchestrator (used by systemd timer)
├── requests/               # Queued requests
├── responses/              # Completed results
├── escalations/            # Awaiting human decision
├── completed/              # Processed & archived
├── logs/                   # Pipeline logs
├── requirements.txt        # Python dependencies
├── PIPELINE.md             # Full pipeline documentation
└── SETUP.md                # This file
```

## Configuration

Edit `batch-config.sh` to change:

```bash
export BATCH_MODEL="claude-haiku-4-5-20251001"      # Model for work
export ROUTER_MODEL="claude-haiku-4-5-20251001"     # Model for routing
export BATCH_POLL_INTERVAL=120                      # Poll every 2 minutes
```

## Environment Variables

Required:
- `ANTHROPIC_API_KEY` — Your Anthropic API key

Auto-set by batch-config.sh:
- `BATCH_DIR` — Base directory (`~/.claude/batch-pipeline/freedom-os/` or customized)
- `BATCH_REQUESTS_DIR`, `BATCH_RESPONSES_DIR`, etc. — Subdirectories

## For macOS without systemd

Use `launchd` instead of systemd:

```bash
# Create ~/Library/LaunchAgents/com.local.batch-poll.plist
# Copy systemd timer logic to launchd format
# Run: launchctl load ~/Library/LaunchAgents/com.local.batch-poll.plist
```

Or use `cron` (not as reliable but works):

```bash
# Add to crontab:
# */2 * * * * cd /path/to/Claude-Batching && bash batch.sh poll
```

## Troubleshooting

**"ModuleNotFoundError: No module named 'anthropic'"**
```bash
source venv/bin/activate
pip install anthropic
```

**"Could not resolve authentication method"**
- Verify `ANTHROPIC_API_KEY` is set: `echo $ANTHROPIC_API_KEY`
- Get a key from https://console.anthropic.com/keys

**No results after 10 minutes**
- Check batch status: `bash batch.sh status`
- View logs: `tail logs/poll.log`
- Check systemd: `systemctl --user status freedom-batch-poll.service -n 20`

**Escalation not appearing**
- Check folder: `ls escalations/`
- View escalation: `cat escalations/*.escalate | jq .`

## Advanced: Custom Projects

To use this for your own project:

1. Edit `batch-config.sh`:
   ```bash
   export BATCH_DIR="/path/to/your/project/.batch"
   export FREEDOM_OS_DIR="/path/to/your/project"
   ```

2. Customize `batch-router.py`:
   - Change `load_project_context()` to read your project's docs
   - Adjust classification logic for your task types

3. Run:
   ```bash
   bash batch.sh send "Your task description"
   ```

## License

Same as the parent project (check repository root).

## Support

Issues: Report to the repository.

Docs: See `PIPELINE.md` for full pipeline documentation and workflow examples.
