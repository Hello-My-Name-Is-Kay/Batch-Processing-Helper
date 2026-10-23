#!/bin/bash
# Freedom-OS Batch Pipeline wrapper (bash shell)
# Activates venv and runs batch commands

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$(dirname "$SCRIPT_DIR")/venv"

# Activate venv
source "${VENV_DIR}/bin/activate"

# Load batch config
source "${SCRIPT_DIR}/batch-config.sh"

# Route commands
cmd="${1:-status}"

case "$cmd" in
    send)
        if [ $# -lt 2 ]; then
            echo "Usage: batch send '<message>' [system_message]" >&2
            exit 1
        fi
        python3 -I "${SCRIPT_DIR}/batch-submit.py" "$2" "${3:-}" | jq .
        echo ""
        echo "✓ Request queued. Check status with: batch status"
        ;;
    poll)
        python3 -I "${SCRIPT_DIR}/batch-poll.py" > /dev/null
        python3 -I "${SCRIPT_DIR}/batch-router.py" > /dev/null
        echo "✓ Poll cycle complete"
        ;;
    status)
        python3 -I "${SCRIPT_DIR}/batch-status.py" "${@:2}"
        ;;
    escalations)
        bash "${SCRIPT_DIR}/batch-orchestrator.sh" escalations
        ;;
    metrics)
        python3 -I "${SCRIPT_DIR}/batch-metrics.py" "${@:2}"
        ;;
    logs)
        log_file="${BATCH_LOGS_DIR}/orchestrator.log"
        if [ -f "$log_file" ]; then
            tail -20 "$log_file"
        else
            echo "No logs yet"
        fi
        ;;
    *)
        echo "Unknown command: $cmd" >&2
        echo "Usage: batch {send|poll|status|escalations|metrics|logs}" >&2
        exit 1
        ;;
esac
