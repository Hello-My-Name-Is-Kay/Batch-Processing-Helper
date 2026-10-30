#!/usr/bin/env fish
# Start the HTTP batch gateway, or run the separate stdio MCP server.
# Resolves paths relative to this script; no virtualenv activation is needed.

set -l project_dir (path resolve (dirname (status filename)))
set -l python "$project_dir/venv/bin/python"
set -l mode start

if test (count $argv) -gt 1
    echo "Usage: start-server.fish [--foreground|--mcp|--help]" >&2
    exit 2
end

if test (count $argv) -eq 1
    switch $argv[1]
        case --help -h
            echo 'Usage: ./start-server.fish [--foreground|--mcp|--help]'
            echo ''
            echo 'No options:   Start the Groq/OpenRouter HTTP batch gateway in the background.'
            echo '--foreground: Run the HTTP gateway in this terminal (Ctrl+C to stop).'
            echo '--mcp:        Run the stdio MCP server; an MCP host must provide stdin/stdout.'
            echo ''
            echo 'HTTP gateway: http://127.0.0.1:8787/v1'
            echo 'Credentials:  saved --setup keys, environment, or Pi auth (OpenRouter).'
            echo 'Logs:         $BATCH_GATEWAY_STATE/gateway.log, or'
            echo '              ~/.local/state/batch-gateway/gateway.log'
            exit 0
        case --foreground
            set mode serve
        case --mcp
            set mode mcp
        case '*'
            echo "Unknown option: $argv[1]. Use --help." >&2
            exit 2
    end
end

if not test -x "$python"
    echo "Missing virtualenv Python: $python" >&2
    echo "Create it with: python3 -m venv '$project_dir/venv'" >&2
    echo "Then install: '$python' -m pip install -r '$project_dir/requirements.txt'" >&2
    exit 1
end

if test "$mode" = mcp
    # Do not print banners: stdout belongs to the JSON-RPC transport.
    exec "$python" "$project_dir/batch-mcp.py"
else
    exec "$python" "$project_dir/batch_gateway.py" "$mode"
end
