#!/bin/bash
# Batch Pipeline wrapper (bash shell)
# Multi-provider support: anthropic (default), openrouter
# Runs batch commands with the project's Python (see BATCH_PYTHON in batch-config.sh)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse global flags: they come before the command.
PROVIDER_FLAG=""
MODEL_FLAG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --provider|-p|--model|-m)
            if [ $# -lt 2 ]; then
                echo "Missing value for $1" >&2
                exit 1
            fi
            if [ "$1" = "--provider" ] || [ "$1" = "-p" ]; then
                PROVIDER_FLAG="$2"
                export BATCH_PROVIDER="$PROVIDER_FLAG"
            else
                MODEL_FLAG="$2"
            fi
            shift 2
            ;;
        *)
            break
            ;;
    esac
done

# Load batch config (after the flags, so --provider decides which API key is checked)
source "${SCRIPT_DIR}/batch-config.sh"

# Submit through batch-submit.py, pretty-printing its JSON summary when jq is installed
run_submit() {
    if command -v jq >/dev/null 2>&1; then
        "$BATCH_PYTHON" "${SCRIPT_DIR}/batch-submit.py" "$@" | jq .
    else
        "$BATCH_PYTHON" "${SCRIPT_DIR}/batch-submit.py" "$@"
    fi
}

# Route commands
cmd="${1:-help}"
if [ $# -gt 0 ]; then
    shift
fi

case "$cmd" in
    send)
        if [ $# -lt 1 ]; then
            echo "Usage: batch [--provider anthropic|openrouter] [--model MODEL] send '<message>' [system_message]" >&2
            echo ""
            echo "Examples:"
            echo "  batch send 'Write a summary'"
            echo "  batch --provider openrouter send 'Analyze this code'"
            echo "  batch -p openrouter -m 'openai/gpt-4o' send 'Task description'"
            exit 1
        fi

        user_msg="$1"
        system_msg="${2:-}"

        # Build provider args ("--" keeps a message that starts with "-" from being read as a flag)
        PY_ARGS=()
        [ -n "$PROVIDER_FLAG" ] && PY_ARGS+=(--provider "$PROVIDER_FLAG")
        [ -n "$MODEL_FLAG" ] && PY_ARGS+=(--model "$MODEL_FLAG")
        PY_ARGS+=(-- "$user_msg")
        [ -n "$system_msg" ] && PY_ARGS+=("$system_msg")

        run_submit "${PY_ARGS[@]}"
        echo ""
        echo "✓ Request queued. Check status with: batch status"
        ;;

    send-file)
        if [ $# -lt 1 ]; then
            echo "Usage: batch [--provider anthropic|openrouter] [--model MODEL] send-file <prompts-file> [system_message]" >&2
            echo ""
            echo "One prompt per line (blank lines ignored); a .jsonl file may use"
            echo '{"message": "...", "system": "...", "id": "..."} objects. All prompts go in ONE batch.'
            exit 1
        fi

        PY_ARGS=()
        [ -n "$PROVIDER_FLAG" ] && PY_ARGS+=(--provider "$PROVIDER_FLAG")
        [ -n "$MODEL_FLAG" ] && PY_ARGS+=(--model "$MODEL_FLAG")
        PY_ARGS+=(--file "$1")
        [ -n "${2:-}" ] && PY_ARGS+=(--system "$2")

        run_submit "${PY_ARGS[@]}"
        echo ""
        echo "✓ Batch queued. Check status with: batch status"
        ;;

    poll)
        PY_ARGS=()
        [ -n "$PROVIDER_FLAG" ] && PY_ARGS+=(--provider "$PROVIDER_FLAG")

        "$BATCH_PYTHON" "${SCRIPT_DIR}/batch-poll.py" ${PY_ARGS[@]+"${PY_ARGS[@]}"} > /dev/null
        "$BATCH_PYTHON" "${SCRIPT_DIR}/batch-router.py" ${PY_ARGS[@]+"${PY_ARGS[@]}"} > /dev/null
        echo "✓ Poll cycle complete"
        ;;

    status)
        "$BATCH_PYTHON" "${SCRIPT_DIR}/batch-status.py" "$@"
        ;;

    escalations)
        bash "${SCRIPT_DIR}/batch-orchestrator.sh" escalations
        ;;

    metrics)
        "$BATCH_PYTHON" "${SCRIPT_DIR}/batch-metrics.py" "$@"
        ;;

    history|hist)
        "$BATCH_PYTHON" "${SCRIPT_DIR}/batch_history.py" list --limit "${1:-10}"
        ;;

    stats)
        "$BATCH_PYTHON" "${SCRIPT_DIR}/batch_history.py" stats
        ;;

    logs)
        log_file="${BATCH_LOGS_DIR}/orchestrator.log"
        if [ -f "$log_file" ]; then
            tail -20 "$log_file"
        else
            echo "No logs yet"
        fi
        ;;

    providers)
        echo "Available batch providers:"
        echo "  anthropic   - Anthropic Batch API (default)"
        echo "  openrouter  - OpenRouter Batch API"
        echo ""
        echo "Set provider via: export BATCH_PROVIDER=openrouter"
        echo "Or per-command:  batch --provider openrouter send 'Task'"
        echo ""
        echo "Current: BATCH_PROVIDER=${BATCH_PROVIDER:-anthropic}"
        ;;

    tui)
        "$BATCH_PYTHON" "${SCRIPT_DIR}/batch_tui.py"
        ;;

    help|--help|-h)
        echo "Batch Pipeline — Multi-Provider Batch Processing"
        echo ""
        echo "Usage: batch [--provider PROVIDER] [--model MODEL] COMMAND [args...]"
        echo ""
        echo "Global flags:"
        echo "  --provider, -p   Provider: anthropic (default), openrouter"
        echo "  --model, -m      Model name (provider-specific)"
        echo ""
        echo "Commands:"
        echo "  send '<msg>' [sys_msg]   Submit a batch request"
        echo "  send-file FILE [sys_msg] Submit every prompt in FILE as one batch"
        echo "  poll                     Poll for completed batches"
        echo "  status                   Show pipeline status"
        echo "  escalations              View items needing review"
        echo "  metrics [--json FILE]    Show performance metrics"
        echo "  history [N]              Show last N history entries (default: 10)"
        echo "  stats                    Show aggregate stats per provider/model"
        echo "  logs                     View recent logs"
        echo "  providers                List available providers"
        echo "  tui                      Launch interactive TUI (mouse+keyboard)"
        echo ""
        echo "Examples:"
        echo "  batch send 'Summarize this file'"
        echo "  batch --provider openrouter send 'Analyze code'"
        echo "  batch -p openrouter -m 'openai/gpt-4o' send 'Task'"
        echo "  batch send-file prompts.txt"
        echo "  batch status"
        echo "  batch tui                # Launch the TUI"
        ;;

    *)
        echo "Unknown command: $cmd" >&2
        echo "Usage: batch [--provider PROVIDER] {send|send-file|poll|status|escalations|metrics|history|stats|logs|providers|tui}" >&2
        exit 1
        ;;
esac
