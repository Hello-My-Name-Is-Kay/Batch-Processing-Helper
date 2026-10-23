#!/bin/bash
# Batch Pipeline wrapper (bash shell)
# Multi-provider support: anthropic (default), openrouter
# Activates venv and runs batch commands

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/venv"

# Activate venv
if [ -f "${VENV_DIR}/bin/activate" ]; then
    source "${VENV_DIR}/bin/activate"
fi

# Load batch config
source "${SCRIPT_DIR}/batch-config.sh"

# Route commands
cmd="${1:-help}"

# Parse global flags
PROVIDER_FLAG=""
MODEL_FLAG=""

# Check for --provider or -p before the command
shift_args=0
args=("$@")
for i in "${!args[@]}"; do
    if [[ "${args[$i]}" == "--provider" || "${args[$i]}" == "-p" ]]; then
        if [[ $((i+1)) -lt ${#args[@]} ]]; then
            PROVIDER_FLAG="${args[$i+1]}"
            export BATCH_PROVIDER="$PROVIDER_FLAG"
            shift_args=$((shift_args + 2))
        fi
    elif [[ "${args[$i]}" == "--model" || "${args[$i]}" == "-m" ]]; then
        if [[ $((i+1)) -lt ${#args[@]} ]]; then
            MODEL_FLAG="${args[$i+1]}"
            shift_args=$((shift_args + 2))
        fi
    else
        break
    fi
done

# Shift past flags to get the command
if [ $shift_args -gt 0 ]; then
    cmd="${args[$shift_args]:-help}"
else
    cmd="${1:-help}"
fi

case "$cmd" in
    send)
        if [ $# -lt 2 ]; then
            echo "Usage: batch [--provider anthropic|openrouter] send '<message>' [system_message]" >&2
            echo ""
            echo "Examples:"
            echo "  batch send 'Write a summary'"
            echo "  batch --provider openrouter send 'Analyze this code'"
            echo "  batch -p openrouter -m 'openai/gpt-4o' send 'Task description'"
            exit 1
        fi
        
        # Extract message and system_message from remaining args after flags
        if [ $shift_args -gt 0 ]; then
            user_msg="${args[$((shift_args+1))]:-}"
            system_msg="${args[$((shift_args+2))]:-}"
        else
            user_msg="$2"
            system_msg="${3:-}"
        fi
        
        # Build provider args
        PY_ARGS=""
        [ -n "$PROVIDER_FLAG" ] && PY_ARGS="$PY_ARGS --provider $PROVIDER_FLAG"
        [ -n "$MODEL_FLAG" ] && PY_ARGS="$PY_ARGS --model $MODEL_FLAG"
        
        python3 -I "${SCRIPT_DIR}/batch-submit.py" $PY_ARGS "$user_msg" "$system_msg" | jq .
        echo ""
        echo "✓ Request queued. Check status with: batch status"
        ;;
    
    poll)
        PY_ARGS=""
        [ -n "$PROVIDER_FLAG" ] && PY_ARGS="$PY_ARGS --provider $PROVIDER_FLAG"
        
        python3 -I "${SCRIPT_DIR}/batch-poll.py" $PY_ARGS > /dev/null
        python3 -I "${SCRIPT_DIR}/batch-router.py" $PY_ARGS > /dev/null
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
    
    history|hist)
        python3 -I "${SCRIPT_DIR}/batch_history.py" list --limit "${2:-10}"
        ;;
    
    stats)
        python3 -I "${SCRIPT_DIR}/batch_history.py" stats
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
        python3 -I "${SCRIPT_DIR}/batch_tui.py"
        ;;

    help|--help|-h)
        echo "Batch Pipeline — Multi-Provider Batch Processing"
        echo ""
        echo "Usage: batch [--provider PROVIDER] COMMAND [args...]"
        echo ""
        echo "Global flags:"
        echo "  --provider, -p   Provider: anthropic (default), openrouter"
        echo "  --model, -m      Model name (provider-specific)"
        echo ""
        echo "Commands:"
        echo "  send '<msg>' [sys_msg]   Submit a batch request"
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
        echo "  batch status"
        echo "  batch tui                # Launch the TUI"
        ;;
    
    *)
        echo "Unknown command: $cmd" >&2
        echo "Usage: batch [--provider PROVIDER] {send|poll|status|escalations|metrics|history|stats|logs|providers|tui}" >&2
        exit 1
        ;;
esac