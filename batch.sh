#!/bin/bash
# Batch Pipeline wrapper (bash shell)
# Supported providers: anthropic (default), openrouter, groq
# Runs batch commands with the project's Python (see BATCH_PYTHON in batch-config.sh)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse global flags: they come before the command.
PROVIDER_FLAG=""
MODEL_FLAG=""
AGENT_FLAG=""
SYSTEM_FLAG=""
MAX_TOKENS_FLAG=""
DRY_RUN=""
while [ $# -gt 0 ]; do
    case "$1" in
        --provider|-p|--model|-m|--agent|-a|--system|-s|--max-tokens)
            if [ $# -lt 2 ]; then
                echo "Missing value for $1" >&2
                exit 1
            fi
            case "$1" in
                --provider|-p)
                    PROVIDER_FLAG="$2"
                    export BATCH_PROVIDER="$PROVIDER_FLAG"
                    ;;
                --model|-m) MODEL_FLAG="$2" ;;
                --agent|-a) AGENT_FLAG="$2" ;;
                --system|-s) SYSTEM_FLAG="$2" ;;
                --max-tokens) MAX_TOKENS_FLAG="$2" ;;
            esac
            shift 2
            ;;
        --dry-run|-n)
            DRY_RUN="yes"
            shift
            ;;
        *)
            break
            ;;
    esac
done

# Load batch config (after the flags, so --provider decides which API key is checked)
source "${SCRIPT_DIR}/batch-config.sh"

# Arguments shared by send and send-file, in SUBMIT_ARGS
build_submit_args() {
    SUBMIT_ARGS=()
    [ -n "$PROVIDER_FLAG" ] && SUBMIT_ARGS+=(--provider "$PROVIDER_FLAG")
    [ -n "$MODEL_FLAG" ] && SUBMIT_ARGS+=(--model "$MODEL_FLAG")
    [ -n "$AGENT_FLAG" ] && SUBMIT_ARGS+=(--agent "$AGENT_FLAG")
    [ -n "$SYSTEM_FLAG" ] && SUBMIT_ARGS+=(--system "$SYSTEM_FLAG")
    [ -n "$MAX_TOKENS_FLAG" ] && SUBMIT_ARGS+=(--max-tokens "$MAX_TOKENS_FLAG")
    [ -n "$DRY_RUN" ] && SUBMIT_ARGS+=(--dry-run)
    return 0
}

# Submit through batch-submit.py, pretty-printing its JSON summary when jq is installed
run_submit() {
    if command -v jq >/dev/null 2>&1; then
        "$BATCH_PYTHON" "${SCRIPT_DIR}/batch-submit.py" "$@" | jq .
    else
        "$BATCH_PYTHON" "${SCRIPT_DIR}/batch-submit.py" "$@"
    fi
}

# What to say after a successful submit (or a preview)
submit_done() {
    echo ""
    if [ -n "$DRY_RUN" ]; then
        echo "Dry run: nothing was sent. Run the same command without --dry-run to submit."
    else
        echo "✓ Batch queued. Check status with: batch status"
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
            echo "Usage: batch [flags] send '<message>' ['<message>' ...]" >&2
            echo ""
            echo "Flags: --provider P  --model M  --agent NAME  --system TEXT  --max-tokens N  --dry-run"
            echo ""
            echo "Examples:"
            echo "  batch send 'Write a summary'"
            echo "  batch send 'Task 1' 'Task 2' 'Task 3'       # several requests, one batch"
            echo "  batch --provider openrouter send 'Analyze this code'"
            echo "  batch -p openrouter -m 'openai/gpt-4o' send 'Task description'"
            echo "  batch --agent 'my-session' send 'Task'"
            echo "  batch --dry-run send 'Task'                 # preview, send nothing"
            exit 1
        fi

        # "--" keeps a message that starts with "-" from being read as a flag
        build_submit_args
        run_submit "${SUBMIT_ARGS[@]+"${SUBMIT_ARGS[@]}"}" -- "$@"
        submit_done
        ;;

    send-file)
        if [ $# -lt 1 ]; then
            echo "Usage: batch [flags] send-file <prompts-file>" >&2
            echo ""
            echo "One prompt per line (blank lines ignored); a .jsonl file may use"
            echo '{"message": "...", "system": "...", "id": "..."} objects. All prompts go in ONE batch.'
            exit 1
        fi

        build_submit_args
        run_submit "${SUBMIT_ARGS[@]+"${SUBMIT_ARGS[@]}"}" --file "$1"
        submit_done
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
        echo "  groq        - Groq Batch API"
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
        echo "Usage: batch [flags] COMMAND [args...]"
        echo ""
        echo "Flags (before the command):"
        echo "  --provider, -p   Provider: anthropic (default), openrouter, groq"
        echo "  --model, -m      Model name (provider-specific)"
        echo "  --agent, -a      Agent/session that owns the batch"
        echo "  --system, -s     System message for the requests"
        echo "  --max-tokens N   Cap on each reply's tokens (default 2048)"
        echo "  --dry-run, -n    Preview the batch without submitting it"
        echo ""
        echo "Commands:"
        echo "  send '<msg>' [...]       Submit one or more requests as one batch"
        echo "  send-file FILE           Submit every prompt in FILE as one batch"
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
        echo "  batch send 'Task 1' 'Task 2' 'Task 3'     # multi-request batch"
        echo "  batch send-file prompts.txt"
        echo "  batch --provider openrouter send 'Analyze code'"
        echo "  batch -p openrouter -m 'openai/gpt-4o' send 'Task'"
        echo "  batch --agent 'my-session' send 'Task'    # agent ownership"
        echo "  batch --dry-run send 'Task'               # preview before sending"
        echo "  batch status"
        echo "  batch tui                # Launch the TUI"
        ;;

    *)
        echo "Unknown command: $cmd" >&2
        echo "Usage: batch [flags] {send|send-file|poll|status|escalations|metrics|history|stats|logs|providers|tui}" >&2
        exit 1
        ;;
esac
