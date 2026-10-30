#!/bin/bash
# Batch pipeline configuration
# Supports three providers: anthropic (default), openrouter, groq

SCRIPT_DIR_BATCH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || echo "${BATCH_SCRIPT_DIR:-.}")"

# --- Optional .env file ---
# cron and other non-interactive callers do not inherit the exports from your
# shell, so API keys and overrides can live in a KEY=VALUE file instead.
# Default: .env next to this script (git-ignored); override with BATCH_ENV_FILE.
# Plain KEY=VALUE lines only (optional quotes, no expansion, no inline
# comments). The file is parsed, never executed, and variables that are
# already set in the environment win over it.
_batch_load_env_file() {
    local file="$1" line key val
    [ -f "$file" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line#export }"
        case "$line" in
            ''|'#'*) continue ;;
            *=*) ;;
            *) continue ;;
        esac
        key="${line%%=*}"
        val="${line#*=}"
        case "$key" in
            ''|[0-9]*|*[!A-Za-z0-9_]*) continue ;;
        esac
        case "$val" in
            \"*\") val="${val#\"}"; val="${val%\"}" ;;
            \'*\') val="${val#\'}"; val="${val%\'}" ;;
        esac
        if [ -z "${!key+x}" ]; then
            export "$key=$val"
        fi
    done < "$file"
}
_batch_load_env_file "${BATCH_ENV_FILE:-${SCRIPT_DIR_BATCH}/.env}"
unset -f _batch_load_env_file

# --- Provider Selection ---
# Set to "anthropic", "openrouter", or "groq"
export BATCH_PROVIDER="${BATCH_PROVIDER:-anthropic}"

# --- Python interpreter ---
# Used by batch.sh and the cron job: BATCH_PYTHON if set, else the project's
# venv, else python3 from PATH.
if [ -z "${BATCH_PYTHON:-}" ]; then
    if [ -x "${SCRIPT_DIR_BATCH}/venv/bin/python3" ]; then
        BATCH_PYTHON="${SCRIPT_DIR_BATCH}/venv/bin/python3"
    else
        BATCH_PYTHON="python3"
    fi
fi
export BATCH_PYTHON

# Check both inherited/.env values and the owner-only private credential store.
credential_available() {
    "$BATCH_PYTHON" "${SCRIPT_DIR_BATCH}/batch_credentials.py" has "$1" >/dev/null 2>&1
}

# --- Base Directory ---
# Default: inside the project directory (self-contained)
export BATCH_DIR="${BATCH_DIR:-${SCRIPT_DIR_BATCH}/.batch-data}"
export BATCH_REQUESTS_DIR="${BATCH_DIR}/requests"
export BATCH_RESPONSES_DIR="${BATCH_DIR}/responses"
export BATCH_COMPLETED_DIR="${BATCH_DIR}/completed"
export BATCH_ESCALATIONS_DIR="${BATCH_DIR}/escalations"
export BATCH_LOGS_DIR="${BATCH_DIR}/logs"
export BATCH_STATE="${BATCH_DIR}/.batch-state"

# --- Provider-specific API Keys ---
# Anthropic (required if BATCH_PROVIDER=anthropic)
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
# OpenRouter (required if BATCH_PROVIDER=openrouter)
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
# Groq (required if BATCH_PROVIDER=groq)
export GROQ_API_KEY="${GROQ_API_KEY:-}"
# Optional: identify your app to OpenRouter
export OPENROUTER_REFERER="${OPENROUTER_REFERER:-}"
export OPENROUTER_APP_NAME="${OPENROUTER_APP_NAME:-batch-pipeline}"

# --- Models ---
# Model for batch work (provider-specific). Leave unset to use the selected
# provider's default: claude-haiku-4-5-20251001 for Anthropic, or
# OPENROUTER_BATCH_MODEL (else deepseek/deepseek-v4.1-flash) for OpenRouter.
# Anthropic: claude-haiku-4-5-20251001, claude-sonnet-4-20250514, etc.
# OpenRouter: anthropic/claude-3.5-haiku, openai/gpt-4o, google/gemini-2.0-flash-001, etc.
# OpenRouter model IDs are sent exactly as written; pick one that offers a batch variant.
export BATCH_MODEL="${BATCH_MODEL:-}"
# OpenRouter-specific override (defaults to BATCH_MODEL if not set)
export OPENROUTER_BATCH_MODEL="${OPENROUTER_BATCH_MODEL:-}"

# Model for routing/classification (always uses live API, configurable).
# Leave unset to use claude-haiku-4-5-20251001 (Anthropic) or the provider default.
export ROUTER_MODEL="${ROUTER_MODEL:-}"
# OpenRouter model for routing (if different from ROUTER_MODEL)
export OPENROUTER_ROUTER_MODEL="${OPENROUTER_ROUTER_MODEL:-}"

# --- Timing ---
# Seconds between polls. Applied when you run "batch-orchestrator.sh setup-cron"
# (cron works in whole minutes, so this is rounded up; minimum 1 minute).
export BATCH_POLL_INTERVAL=${BATCH_POLL_INTERVAL:-120}  # seconds

# --- Project Context (for routing decisions) ---
export PROJECT_DIR="${PROJECT_DIR:-}"
export PROJECT_CONTEXT_FILE="${PROJECT_CONTEXT_FILE:-}"

# ── Validate API keys ──
case "${BATCH_PROVIDER}" in
    anthropic)
        if ! credential_available anthropic; then
            echo "⚠️  WARNING: BATCH_PROVIDER=anthropic but no Anthropic credential is available." >&2
            echo "   Set it with batch_credentials.py, in .env, or in the environment." >&2
        fi
        ;;
    groq)
        if ! credential_available groq; then
            echo "⚠️  WARNING: BATCH_PROVIDER=groq but no Groq credential is available." >&2
            echo "   Set it with batch_credentials.py, in .env, or in the environment." >&2
        fi
        ;;
    openrouter)
        if ! credential_available openrouter; then
            echo "⚠️  WARNING: BATCH_PROVIDER=openrouter but no OpenRouter credential is available." >&2
            echo "   Set it with batch_credentials.py, in .env, or in the environment." >&2
        fi
        ;;
esac

# Ensure directories exist
mkdir -p "$BATCH_REQUESTS_DIR" "$BATCH_RESPONSES_DIR" "$BATCH_COMPLETED_DIR" \
         "$BATCH_ESCALATIONS_DIR" "$BATCH_LOGS_DIR"
