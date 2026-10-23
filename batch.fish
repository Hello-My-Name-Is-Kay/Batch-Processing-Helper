#!/usr/bin/env fish
# Freedom-OS Batch Pipeline wrapper (fish shell)
# Activates venv and runs batch commands

set -l VENV_DIR (dirname (dirname (dirname (realpath (status current-filename))))); /venv
set -l SCRIPT_DIR (dirname (realpath (status current-filename)))
set -l BATCH_CONFIG "$SCRIPT_DIR/batch-config.sh"

# Activate venv
source $VENV_DIR/bin/activate.fish

# Load batch config
export BATCH_DIR="$HOME/.claude/batch-pipeline/freedom-os"
export BATCH_REQUESTS_DIR="$BATCH_DIR/requests"
export BATCH_RESPONSES_DIR="$BATCH_DIR/responses"
export BATCH_COMPLETED_DIR="$BATCH_DIR/completed"
export BATCH_ESCALATIONS_DIR="$BATCH_DIR/escalations"
export BATCH_LOGS_DIR="$BATCH_DIR/logs"
export BATCH_STATE="$BATCH_DIR/.batch-state"
export FREEDOM_OS_DIR="$HOME/Projects/Freedom-OS"
export BATCH_MODEL="claude-haiku-4-5-20251001"
export ROUTER_MODEL="claude-haiku-4-5-20251001"

# Route commands
switch (count $argv)
    case 0
        echo "Freedom-OS Batch Pipeline"
        echo ""
        echo "Usage: batch send '<message>' [system_message]"
        echo "       batch status"
        echo "       batch poll"
        echo "       batch escalations"
        echo "       batch logs"
        exit 0
end

set -l cmd $argv[1]

switch $cmd
    case send
        if test (count $argv) -lt 2
            echo "Usage: batch send '<message>' [system_message]" >&2
            exit 1
        end
        python3 -I "$SCRIPT_DIR/batch-submit.py" "$argv[2]" "$argv[3]" \
            | jq .
        echo ""
        echo "✓ Request queued. Check status with: batch status"

    case poll
        python3 -I "$SCRIPT_DIR/batch-poll.py"
        python3 -I "$SCRIPT_DIR/batch-router.py"

    case status
        echo "=== Batch Pipeline Status ==="
        echo "Requests:    $(find $BATCH_REQUESTS_DIR -name '*.jsonl' 2>/dev/null | wc -l)"
        echo "Responses:   $(find $BATCH_RESPONSES_DIR -name '*.result' 2>/dev/null | wc -l)"
        echo "Escalations: $(find $BATCH_ESCALATIONS_DIR -name '*.escalate' 2>/dev/null | wc -l)"
        echo "Completed:   $(find $BATCH_COMPLETED_DIR -name '*.done' 2>/dev/null | wc -l)"
        echo ""

        # Show escalations if any
        set -l escalations (find $BATCH_ESCALATIONS_DIR -name '*.escalate' 2>/dev/null)
        if test -n "$escalations"
            echo "⚠  ESCALATIONS AWAITING REVIEW:"
            for f in $escalations
                set -l req_id (basename $f .escalate)
                echo "   $req_id"
            end
        end

    case escalations
        bash "$SCRIPT_DIR/batch-orchestrator.sh" escalations

    case logs
        set -l log_file "$BATCH_LOGS_DIR/orchestrator.log"
        if test -f "$log_file"
            tail -20 "$log_file"
        else
            echo "No logs yet"
        end

    case '*'
        echo "Unknown command: $cmd" >&2
        exit 1
end
