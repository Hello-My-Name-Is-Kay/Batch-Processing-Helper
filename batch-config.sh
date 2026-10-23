#!/bin/bash
# Batch pipeline configuration for Freedom-OS

export BATCH_DIR="${HOME}/.claude/batch-pipeline/freedom-os"
export BATCH_REQUESTS_DIR="${BATCH_DIR}/requests"
export BATCH_RESPONSES_DIR="${BATCH_DIR}/responses"
export BATCH_COMPLETED_DIR="${BATCH_DIR}/completed"
export BATCH_ESCALATIONS_DIR="${BATCH_DIR}/escalations"
export BATCH_LOGS_DIR="${BATCH_DIR}/logs"
export BATCH_STATE="${BATCH_DIR}/.batch-state"

export FREEDOM_OS_DIR="/home/kapha/Projects/Freedom-OS"
export BATCH_MODEL="claude-haiku-4-5-20251001"
export ROUTER_MODEL="claude-haiku-4-5-20251001"
export BATCH_POLL_INTERVAL=120  # seconds (cron: every 2 min)

# Ensure directories exist
mkdir -p "$BATCH_REQUESTS_DIR" "$BATCH_RESPONSES_DIR" "$BATCH_COMPLETED_DIR" \
         "$BATCH_ESCALATIONS_DIR" "$BATCH_LOGS_DIR"
