#!/bin/bash
# Batch pipeline orchestrator: polls, processes, routes, checks for escalations
# Multi-provider support (anthropic, openrouter, etc.)
#
# Also what cron runs, so it must not depend on your interactive shell:
# API keys come from the environment or .env (see batch-config.sh), Python is
# the project's venv when present, and Python's error output goes to
# logs/orchestrator.log instead of being thrown away.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/batch-config.sh"

log_msg() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >> "${BATCH_LOGS_DIR}/orchestrator.log"
}

poll_and_process() {
    local provider="${1:-}"
    log_msg "Starting batch poll cycle (provider: ${provider:-all})..."

    local poll_args=()
    [ -n "$provider" ] && poll_args+=(--provider "$provider")

    # Poll for completed batches (stdout is just a JSON summary; errors go to the log)
    "$BATCH_PYTHON" "${SCRIPT_DIR}/batch-poll.py" ${poll_args[@]+"${poll_args[@]}"} \
        > /dev/null 2>> "${BATCH_LOGS_DIR}/orchestrator.log" || {
        log_msg "Poll failed: $?"
        return 1
    }

    # Route completed results
    "$BATCH_PYTHON" "${SCRIPT_DIR}/batch-router.py" ${poll_args[@]+"${poll_args[@]}"} \
        > /dev/null 2>> "${BATCH_LOGS_DIR}/orchestrator.log" || {
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

    # Cron works in whole minutes: round BATCH_POLL_INTERVAL (seconds) up.
    case "$BATCH_POLL_INTERVAL" in
        ''|*[!0-9]*)
            echo "BATCH_POLL_INTERVAL must be a whole number of seconds (got '$BATCH_POLL_INTERVAL')" >&2
            return 1
            ;;
    esac
    local minutes=$(( (BATCH_POLL_INTERVAL + 59) / 60 ))
    [ "$minutes" -lt 1 ] && minutes=1
    [ "$minutes" -gt 59 ] && minutes=59

    # Quote the paths (they may contain spaces) and escape % (cron treats it as a newline).
    local script_q dir_q
    script_q="$(printf '%q' "${SCRIPT_DIR}/batch-orchestrator.sh")"
    dir_q="$(printf '%q' "${SCRIPT_DIR}")"
    local cron_job="*/${minutes} * * * * cd ${dir_q} && ${script_q} poll > /dev/null 2>&1"
    cron_job="${cron_job//%/\\%}"

    # Replace this project's own entry (if any) and keep every other line,
    # including entries for other copies of this tool.
    local existing filtered
    existing="$(crontab -l 2>/dev/null || true)"
    filtered="$(printf '%s\n' "$existing" | grep -vF -- "${script_q} poll" || true)"

    {
        [ -n "$filtered" ] && printf '%s\n' "$filtered"
        printf '%s\n' "$cron_job"
    } | crontab -

    log_msg "✓ Cron job installed (every ${minutes} minute(s))"
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
        echo "Requests submitted: $(find "${BATCH_REQUESTS_DIR}" -name "*.jsonl" 2>/dev/null | wc -l)"
        echo "Results awaiting routing: $(find "${BATCH_RESPONSES_DIR}" -name "*.result" 2>/dev/null | wc -l)"
        echo "Escalations: $(find "${BATCH_ESCALATIONS_DIR}" -name "*.escalate" 2>/dev/null | wc -l)"
        echo "Archived: $(find "${BATCH_COMPLETED_DIR}" -name "*.done" 2>/dev/null | wc -l)"
        check_escalations
        ;;
    *)
        echo "Usage: $0 {poll [provider]|setup-cron|escalations|status}"
        echo ""
        echo "Commands:"
        echo "  poll [provider]    Poll for completions (all providers if unspecified)"
        echo "  setup-cron         Install the cron job (interval from BATCH_POLL_INTERVAL)"
        echo "  escalations        Check for items needing review"
        echo "  status             Pipeline status"
        exit 1
        ;;
esac
