#!/bin/bash
# Batch pipeline configuration
# Supports multiple providers: anthropic (default), openrouter

# --- Provider Selection ---
# Set to "anthropic" or "openrouter"
export BATCH_PROVIDER="${BATCH_PROVIDER:-anthropic}"

# --- Base Directory ---
# Default: inside the project directory (self-contained)
SCRIPT_DIR_BATCH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || echo "${BATCH_SCRIPT_DIR:-.}")"
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
# Optional: identify your app to OpenRouter
export OPENROUTER_REFERER="${OPENROUTER_REFERER:-}"
export OPENROUTER_APP_NAME="${OPENROUTER_APP_NAME:-batch-pipeline}"

# --- Models ---
# Model for batch work (provider-specific)
# Anthropic: claude-haiku-4-5-20251001, claude-sonnet-4-20250514, etc.
# OpenRouter: anthropic/claude-3.5-haiku, openai/gpt-4o, google/gemini-2.0-flash-001, etc.
export BATCH_MODEL="${BATCH_MODEL:-claude-haiku-4-5-20251001}"
# OpenRouter-specific override (defaults to BATCH_MODEL if not set)
export OPENROUTER_BATCH_MODEL="${OPENROUTER_BATCH_MODEL:-}"

# Model for routing/classification (always uses live API, configurable)
export ROUTER_MODEL="${ROUTER_MODEL:-claude-haiku-4-5-20251001}"
# OpenRouter model for routing (if different from Anthropic)
export OPENROUTER_ROUTER_MODEL="${OPENROUTER_ROUTER_MODEL:-}"

# --- Timing ---
export BATCH_POLL_INTERVAL=${BATCH_POLL_INTERVAL:-120}  # seconds

# --- Project Context (for routing decisions) ---
export PROJECT_DIR="${PROJECT_DIR:-}"
export PROJECT_CONTEXT_FILE="${PROJECT_CONTEXT_FILE:-}"

# ── Validate API keys ──
case "${BATCH_PROVIDER}" in
    anthropic)
        if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
            echo "⚠️  WARNING: BATCH_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set." >&2
            echo "   Set it in your shell rc or export it:" >&2
            echo "     export ANTHROPIC_API_KEY='sk-...'" >&2
        fi
        ;;
    openrouter)
        if [ -z "${OPENROUTER_API_KEY:-}" ]; then
            echo "⚠️  WARNING: BATCH_PROVIDER=openrouter but OPENROUTER_API_KEY is not set." >&2
            echo "   Set it in your shell rc or export it:" >&2
            echo "     export OPENROUTER_API_KEY='sk-...'" >&2
        fi
        ;;
    groq)
        if [ -z "${GROQ_API_KEY:-}" ]; then
            echo "⚠️  WARNING: BATCH_PROVIDER=groq but GROQ_API_KEY is not set." >&2
            echo "   Set it in your shell rc or export it:" >&2
            echo "     export GROQ_API_KEY='gsk_...'" >&2
        fi
        ;;
esac

# Ensure directories exist
mkdir -p "$BATCH_REQUESTS_DIR" "$BATCH_RESPONSES_DIR" "$BATCH_COMPLETED_DIR" \
         "$BATCH_ESCALATIONS_DIR" "$BATCH_LOGS_DIR"