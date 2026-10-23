# Batch Processing — Setup & Installation

Multi-provider asynchronous batch processing for LLM APIs (Anthropic, OpenRouter, etc.).

**What it is:** Infrastructure to submit work to any supported Batch API (Anthropic, OpenRouter), poll for results asynchronously, and route them (archive, escalate, or queue next step). ~50-80% cheaper than live API calls; ideal for async tasks.

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

Choose your provider:

**Anthropic:**
```bash
export ANTHROPIC_API_KEY="sk-..."
```

**OpenRouter:**
```bash
export OPENROUTER_API_KEY="sk-..."
export BATCH_PROVIDER=openrouter
```

Add to shell config (fish):
```fish
set -gx ANTHROPIC_API_KEY "sk-..."
# or
set -gx OPENROUTER_API_KEY "sk-..."
set -gx BATCH_PROVIDER openrouter
```

### 3. Test

```bash
source venv/bin/activate

# Test with Anthropic (default)
bash batch.sh send "Test message from setup"
bash batch.sh status

# Test with OpenRouter
bash batch.sh --provider openrouter send "Test via OpenRouter"
bash batch.sh status
```

### 4. Install Cron Timer (Linux/macOS)

```bash
# Run setup
bash batch-orchestrator.sh setup-cron

# Verify it's active
crontab -l | grep batch-orchestrator
```

For systemd (alternative to cron):
```bash
cp systemd/*.service ~/.config/systemd/user/
cp systemd/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable freedom-batch-poll.timer
systemctl --user start freedom-batch-poll.timer
systemctl --user status freedom-batch-poll.timer
```

## Usage

**Submit work (default provider):**
```bash
bash batch.sh send "Describe your task here"
```

**Submit via OpenRouter with custom model:**
```bash
bash batch.sh --provider openrouter --model "openai/gpt-4o" send "Analyze this"
```

**Check status:**
```bash
bash batch.sh status
```

**View escalations (items needing your decision):**
```bash
bash batch.sh escalations
```

**View performance metrics:**
```bash
bash batch.sh metrics
```

**View logs:**
```bash
tail logs/orchestrator.log
tail logs/poll.log
```

## How It Works

1. **Submit:** `batch send [--provider X]` → request gets UUID → provider-specific formatting → submitted to provider's Batch API
2. **Poll:** Cron/systemd timer (every 2 min) → discovers provider from state file → checks for completed batches
3. **Route:** LLM classifier reads results → decides: archive, escalate, or queue next batch
4. **Escalations:** Items needing human decision in `escalations/` folder

## File Structure

```
Claude-Batching/
├── batch-submit.py         # Submit requests to provider's Batch API
├── batch-poll.py           # Poll for completions (all providers)
├── batch-router.py         # Classify and route results
├── batch-status.py         # Pipeline status display
├── batch-metrics.py        # Performance metrics
├── batch.sh                # Bash wrapper (main command)
├── batch.fish              # Fish shell wrapper (alternative)
├── batch-config.sh         # Configuration (edit as needed)
├── batch-orchestrator.sh   # Orchestrator (used by cron)
├── providers/              # Provider abstraction layer
│   ├── __init__.py         # Provider registry & factory
│   ├── base.py             # Abstract base class
│   ├── anthropic_provider.py  # Anthropic Batch API
│   └── openrouter_provider.py # OpenRouter Batch API
├── requests/               # Queued requests
├── responses/              # Completed results
├── escalations/            # Awaiting human decision
├── completed/              # Processed & archived
├── logs/                   # Pipeline logs
├── requirements.txt        # Python dependencies
├── PIPELINE.md             # Full pipeline documentation
├── METRICS.md              # Performance tracking
└── SETUP.md                # This file
```

## Configuration

Edit `batch-config.sh` or set environment variables:

```bash
# Provider
export BATCH_PROVIDER="anthropic"                # anthropic or openrouter

# Anthropic
export ANTHROPIC_API_KEY="sk-..."                # Your Anthropic key
export BATCH_MODEL="claude-haiku-4-5-20251001"   # Model for batch work

# OpenRouter
export OPENROUTER_API_KEY="sk-..."               # Your OpenRouter key
export OPENROUTER_BATCH_MODEL=""                 # Override model for OpenRouter
export OPENROUTER_REFERER=""                     # Identify your app
export OPENROUTER_APP_NAME="batch-pipeline"      # Identify your app

# Routing
export ROUTER_MODEL="claude-haiku-4-5-20251001"   # Model for routing
export PROJECT_DIR=""                              # Project context path

# Timing
export BATCH_POLL_INTERVAL=120                     # Poll every 2 minutes
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | For Anthropic | Your Anthropic API key |
| `OPENROUTER_API_KEY` | For OpenRouter | Your OpenRouter API key |
| `BATCH_PROVIDER` | Optional | Provider: `anthropic` (default) or `openrouter` |
| `BATCH_MODEL` | Optional | Model for batch work (provider-specific) |
| `BATCH_DIR` | Optional | Base directory for pipeline files |
| `ROUTER_MODEL` | Optional | Model for routing classification |

Auto-set by `batch-config.sh`:
- `BATCH_DIR`, `BATCH_REQUESTS_DIR`, `BATCH_RESPONSES_DIR`, `BATCH_COMPLETED_DIR`, `BATCH_ESCALATIONS_DIR`, `BATCH_LOGS_DIR`, `BATCH_STATE`

## For macOS without systemd

Use `launchd` instead of systemd (note: timers less reliable on macOS):

```bash
# Create ~/Library/LaunchAgents/com.local.batch-poll.plist
# Or use cron as shown in section 4 above
```

## Troubleshooting

**"ModuleNotFoundError: No module named 'anthropic'"**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

**"OPENROUTER_API_KEY is required"**
- Set the key for your chosen provider
- Verify with: `echo $OPENROUTER_API_KEY`

**"ANTHROPIC_API_KEY is required"**
- Set the key for your chosen provider
- Verify with: `echo $ANTHROPIC_API_KEY`

**"Could not resolve authentication method"**
- For Anthropic: Verify `ANTHROPIC_API_KEY` is set, get key from https://console.anthropic.com/keys
- For OpenRouter: Verify `OPENROUTER_API_KEY` is set, get key from https://openrouter.ai/keys

**No results after 10 minutes**
- Check batch status: `bash batch.sh status`
- View logs: `tail logs/poll.log`
- Check provider: `bash batch.sh providers`

**Escalation not appearing**
- Check folder: `ls escalations/`
- View escalation: `cat escalations/*.escalate | jq .`

## Advanced: Custom Projects

To use this for your own project:

1. Edit `batch-config.sh`:
   ```bash
   export BATCH_DIR="/path/to/your/project/.batch"
   export PROJECT_DIR="/path/to/your/project"
   export PROJECT_CONTEXT_FILE="/path/to/your/project/CONTEXT.md"
   ```

2. Customize `batch-router.py`:
   - The `load_project_context()` function reads your project's docs
   - Adjust classification logic for your task types

3. Run:
   ```bash
   bash batch.sh send "Your task description"
   bash batch.sh --provider openrouter send "Cross-provider task"
   ```

## License

Same as the parent project (check repository root).

## Support

Issues: Report to the repository.

Docs: See `PIPELINE.md` for full pipeline architecture and `METRICS.md` for performance tracking.