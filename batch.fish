#!/usr/bin/env fish
# Batch Pipeline wrapper (fish shell)
# Multi-provider support: anthropic (default), openrouter

set -l SCRIPT_DIR (dirname (realpath (status current-filename)))
set -l VENV_DIR "$SCRIPT_DIR/venv"

# Activate venv
if test -f "$VENV_DIR/bin/activate.fish"
    source "$VENV_DIR/bin/activate.fish"
end

# Load batch config
source "$SCRIPT_DIR/batch-config.sh"

# Parse global flags
set -l PROVIDER_FLAG ""
set -l MODEL_FLAG ""
set -l EXTRA_ARGS

set -l i 1
while test $i -le (count $argv)
    switch $argv[$i]
        case --provider -p
            set i (math $i + 1)
            if test $i -le (count $argv)
                set PROVIDER_FLAG $argv[$i]
                set -gx BATCH_PROVIDER $PROVIDER_FLAG
            end
        case --model -m
            set i (math $i + 1)
            if test $i -le (count $argv)
                set MODEL_FLAG $argv[$i]
            end
        case '--*' '-*'
            # Unknown flag, pass through
            set -a EXTRA_ARGS $argv[$i]
        case '*'
            # Command or argument
            set -a EXTRA_ARGS $argv[$i]
    end
    set i (math $i + 1)
end

# Route commands
if test (count $EXTRA_ARGS) -eq 0
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
    echo "  logs                     View recent logs"
    echo "  providers                List available providers"
    echo ""
    echo "Examples:"
    echo "  batch send 'Summarize this file'"
    echo "  batch --provider openrouter send 'Analyze code'"
    echo "  batch -p openrouter -m 'openai/gpt-4o' send 'Task'"
    exit 0
end

set -l cmd $EXTRA_ARGS[1]

# Build Python args
set -l PY_ARGS ""
if test -n "$PROVIDER_FLAG"
    set PY_ARGS "$PY_ARGS --provider $PROVIDER_FLAG"
end
if test -n "$MODEL_FLAG"
    set PY_ARGS "$PY_ARGS --model $MODEL_FLAG"
end

switch $cmd
    case send
        if test (count $EXTRA_ARGS) -lt 2
            echo "Usage: batch [--provider PROVIDER] send '<message>' [system_message]" >&2
            exit 1
        end
        
        set -l user_msg $EXTRA_ARGS[2]
        set -l system_msg $EXTRA_ARGS[3]
        
        python3 -I "$SCRIPT_DIR/batch-submit.py" $PY_ARGS "$user_msg" "$system_msg" \
            | jq .
        echo ""
        echo "✓ Request queued. Check status with: batch status"

    case poll
        python3 -I "$SCRIPT_DIR/batch-poll.py" $PY_ARGS
        python3 -I "$SCRIPT_DIR/batch-router.py" $PY_ARGS
        echo "✓ Poll cycle complete"

    case status
        python3 -I "$SCRIPT_DIR/batch-status.py" $EXTRA_ARGS[2..-1]

    case escalations
        bash "$SCRIPT_DIR/batch-orchestrator.sh" escalations

    case metrics
        python3 -I "$SCRIPT_DIR/batch-metrics.py" $EXTRA_ARGS[2..-1]

    case logs
        set -l log_file "$BATCH_LOGS_DIR/orchestrator.log"
        if test -f "$log_file"
            tail -20 "$log_file"
        else
            echo "No logs yet"
        end

    case providers
        echo "Available batch providers:"
        echo "  anthropic   - Anthropic Batch API (default)"
        echo "  openrouter  - OpenRouter Batch API"
        echo ""
        echo "Set provider via: set -gx BATCH_PROVIDER openrouter"
        echo "Or per-command:  batch --provider openrouter send 'Task'"
        echo ""
        echo "Current: BATCH_PROVIDER=$BATCH_PROVIDER"

    case '*'
        echo "Unknown command: $cmd" >&2
        exit 1
end