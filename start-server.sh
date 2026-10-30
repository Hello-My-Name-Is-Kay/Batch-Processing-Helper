#!/usr/bin/env bash
# Start the batch gateway (and optionally the web console), show status, or run
# the separate stdio MCP server. Resolves paths relative to this script; no
# virtualenv activation is needed.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PYTHON="$PROJECT_DIR/venv/bin/python"
MODE=start
WITH_CONSOLE=0

usage() {
    printf '%s\n' \
        'Usage: ./start-server.sh [--console | --foreground | --status | --mcp | --help]' \
        '' \
        'No options:   Start the batch gateway in the background.' \
        '--console:    Start the gateway AND the web console, both in the background.' \
        '--status:     Show whether the gateway and web console are running.' \
        '--foreground: Run only the gateway in this terminal (Ctrl+C to stop).' \
        '--mcp:        Run the stdio MCP server; an MCP host must provide stdin/stdout.' \
        '' \
        'Gateway (OpenAI-compatible API for Pi): http://127.0.0.1:8787/v1' \
        'Web console (setup, batches, metrics):  http://127.0.0.1:8788/' \
        '                                        (stop with: ./start-console.sh stop)' \
        'Credentials:  saved --setup keys, exported variables, system/global env files, .env, Pi auth.' \
        'Logs:         ~/.local/state/batch-gateway/gateway.log' \
        '              ~/.local/state/batch-console/console.log'
}

if (( $# > 1 )); then
    usage >&2
    exit 2
fi

case "${1:-}" in
    '') ;;
    --help|-h) usage; exit 0 ;;
    --console) WITH_CONSOLE=1 ;;
    --status) MODE=status ;;
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

case "$MODE" in
    mcp)
        # Do not print banners: stdout belongs to the JSON-RPC transport.
        exec "$PYTHON" "$PROJECT_DIR/batch-mcp.py"
        ;;
    status)
        "$PYTHON" "$PROJECT_DIR/batch_console.py" status || true
        exit 0
        ;;
    serve)
        exec "$PYTHON" "$PROJECT_DIR/batch_gateway.py" serve
        ;;
    start)
        "$PYTHON" "$PROJECT_DIR/batch_gateway.py" start
        if (( WITH_CONSOLE )); then
            "$PYTHON" "$PROJECT_DIR/batch_console.py" start
        fi
        ;;
esac
