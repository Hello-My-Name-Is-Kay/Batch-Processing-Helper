#!/usr/bin/env bash
# Start the HTTP batch gateway, or run the separate stdio MCP server.
# Resolves paths relative to this script; no virtualenv activation is needed.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PYTHON="$PROJECT_DIR/venv/bin/python"
MODE=start

usage() {
    printf '%s\n' \
        'Usage: ./start-server.sh [--foreground|--mcp|--help]' \
        '' \
        'No options:   Start the Groq/OpenRouter HTTP batch gateway in the background.' \
        '--foreground: Run the HTTP gateway in this terminal (Ctrl+C to stop).' \
        '--mcp:        Run the stdio MCP server; an MCP host must provide stdin/stdout.' \
        '' \
        'HTTP gateway: http://127.0.0.1:8787/v1' \
        'Credentials:  saved --setup keys, environment, or Pi auth (OpenRouter).' \
        'Logs:         $BATCH_GATEWAY_STATE/gateway.log, or' \
        '              ~/.local/state/batch-gateway/gateway.log'
}

if (( $# > 1 )); then
    usage >&2
    exit 2
fi

case "${1:-}" in
    '') ;;
    --help|-h) usage; exit 0 ;;
    --foreground) MODE=serve ;;
    --mcp) MODE=mcp ;;
    *) printf 'Unknown option: %s. Use --help.\n' "$1" >&2; exit 2 ;;
esac

if [[ ! -x "$PYTHON" ]]; then
    printf 'Missing virtualenv Python: %s\n' "$PYTHON" >&2
    printf 'Create it with: python3 -m venv %q\n' "$PROJECT_DIR/venv" >&2
    printf 'Then install: %q -m pip install -r %q\n' "$PYTHON" "$PROJECT_DIR/requirements.txt" >&2
    exit 1
fi

if [[ "$MODE" == mcp ]]; then
    # Do not print banners: stdout belongs to the JSON-RPC transport.
    exec "$PYTHON" "$PROJECT_DIR/batch-mcp.py"
else
    exec "$PYTHON" "$PROJECT_DIR/batch_gateway.py" "$MODE"
fi
