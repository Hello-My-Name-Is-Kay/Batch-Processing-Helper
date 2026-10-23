#!/bin/bash
# Batch pipeline orchestrator: polls, processes, routes, checks for escalations
# Multi-provider support (anthropic, openrouter, etc.)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/batch-config.sh"

# Ensure Python scripts are executable
chmod +x "${SCRIPT_DIR}"/{batch-submit,batch-poll,batch-router}.py 2>/dev/null || true

log_msg() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >> "${BATCH_LOGS_DIR}/orchestrator.log"
}

poll_and_process() {
    local provider="${1:-}"
    log_msg "Starting batch poll cycle (provider: ${provider:-all})..."

    POLL_ARGS=""
    [ -n "$provider" ] && POLL_ARGS="--provider $provider"

    # Poll for completed batches
    python3 -I "${SCRIPT_DIR}/batch-poll.py" $POLL_ARGS > /dev/null 2>&1 || {
        log_msg "Poll failed: $?"
        return 1
    }

    # Route completed results
    python3 -I "${SCRIPT_DIR}/batch-router.py" $POLL_ARGS > /dev/null 2>&1 || {
        log_msg "Routing failed: $?"
        return 1
    }

    # Check for escalations
    local escalation_count=$(find "${BATCH_ESCALATIONS_DIR}" -name "*.escalate" 2>/dev/null | wc -l)

    if [ "$escalation_count" -gt 0 ]; then
        log_msg "⚠ $escalation_count escalations awaiting user review"
        echo "⚠ Batch escalations: $(ls -1 "${BATCH_ESCALATIONS_DIR}"/*.escalate 2>/dev/null | head -1)"
        return 0
    fi

    log_msg "✓ Poll cycle complete (no escalations)"
}

setup_cron() {
    log_msg "Setting up cron job..."

    cron_job="*/2 * * * * cd ${SCRIPT_DIR} && ${SCRIPT_DIR}/batch-orchestrator.sh poll > /dev/null 2>&1"

    # Check if already in crontab
    if crontab -l 2>/dev/null | grep -F "batch-orchestrator.sh poll" > /dev/null; then
        log_msg "Cron job already installed"
        return 0
    fi

    # Add to crontab
    (crontab -l 2>/dev/null || echo "") | grep -v "batch-orchestrator.sh" | {
        cat
        echo "$cron_job"
    } | crontab -

    log_msg "✓ Cron job installed (every 2 minutes)"
}

check_escalations() {
    log_msg "Checking escalations..."

    if [ ! -d "${BATCH_ESCALATIONS_DIR}" ]; then
        return 0
    fi

    local escalations
    escalations=$(find "${BATCH_ESCALATIONS_DIR}" -name "*.escalate" -type f 2>/dev/null || true)

    if [ -n "$escalations" ]; then
        echo ""
        echo "════════════════════════════════════════════════════════════"
        echo "⚠  BATCH ESCALATIONS AWAITING REVIEW"
        echo "════════════════════════════════════════════════════════════"

        while IFS= read -r escalation_file; do
            local request_id
            request_id=$(basename "$escalation_file" .escalate)
            echo ""
            echo "Request: $request_id"
            echo "File: $escalation_file"
            echo ""

            # Show classification
            if command -v jq &>/dev/null; then
                jq '.classification' "$escalation_file"
            else
                cat "$escalation_file"
            fi

        done <<< "$escalations"

        echo ""
        echo "════════════════════════════════════════════════════════════"
    fi
}

case "${1:-status}" in
    poll)
        poll_and_process "${2:-}"
        ;;
    setup-cron)
        setup_cron
        ;;
    escalations)
        check_escalations
        ;;
    status)
        log_msg "Pipeline status check"
        echo "Batch Provider: ${BATCH_PROVIDER:-anthropic}"
        echo "Requests: $(find "${BATCH_REQUESTS_DIR}" -name "*.jsonl" 2>/dev/null | wc -l)"
        echo "Responses: $(find "${BATCH_RESPONSES_DIR}" -name "*.result" 2>/dev/null | wc -l)"
        echo "Escalations: $(find "${BATCH_ESCALATIONS_DIR}" -name "*.escalate" 2>/dev/null | wc -l)"
        echo "Completed: $(find "${BATCH_COMPLETED_DIR}" -name "*.done" 2>/dev/null | wc -l)"
        check_escalations
        ;;
    *)
        echo "Usage: $0 {poll [provider]|setup-cron|escalations|status}"
        echo ""
        echo "Commands:"
        echo "  poll [provider]    Poll for completions (all providers if unspecified)"
        echo "  setup-cron         Install 2-min cron job"
        echo "  escalations        Check for items needing review"
        echo "  status             Pipeline status"
        exit 1
        ;;
esac