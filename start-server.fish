#!/usr/bin/env fish
# Start the batch gateway (and optionally the web console), show status, or run
# the separate stdio MCP server. Resolves paths relative to this script; no
# virtualenv activation is needed.

set -l project_dir (path resolve (dirname (status filename)))
set -l python "$project_dir/venv/bin/python"
set -l mode start
set -l with_console 0

function __usage
    echo 'Usage: ./start-server.fish [--console | --foreground | --status | --mcp | --help]'
    echo ''
    echo 'No options:   Start the batch gateway in the background.'
    echo '--console:    Start the gateway AND the web console, both in the background.'
    echo '--status:     Show whether the gateway and web console are running.'
    echo '--foreground: Run only the gateway in this terminal (Ctrl+C to stop).'
    echo '--mcp:        Run the stdio MCP server; an MCP host must provide stdin/stdout.'
    echo ''
    echo 'Gateway (OpenAI-compatible API for Pi): http://127.0.0.1:8787/v1'
    echo 'Web console (setup, batches, metrics):  http://127.0.0.1:8788/'
    echo '                                        (stop with: ./start-console.fish stop)'
    echo 'Credentials:  saved --setup keys, exported variables, system/global env files, .env, Pi auth.'
    echo 'Logs:         ~/.local/state/batch-gateway/gateway.log'
    echo '              ~/.local/state/batch-console/console.log'
end

if test (count $argv) -gt 1
    echo "Usage: start-server.fish [--console|--foreground|--status|--mcp|--help]" >&2
    exit 2
end

if test (count $argv) -eq 1
    switch $argv[1]
        case --help -h
            __usage
            exit 0
        case --console
            set with_console 1
        case --status
            set mode status
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

switch $mode
    case mcp
        # Do not print banners: stdout belongs to the JSON-RPC transport.
        exec "$python" "$project_dir/batch-mcp.py"
    case status
        "$python" "$project_dir/batch_console.py" status
        exit 0
    case serve
        exec "$python" "$project_dir/batch_gateway.py" serve
    case start
        "$python" "$project_dir/batch_gateway.py" start
        or exit $status
        if test $with_console -eq 1
            "$python" "$project_dir/batch_console.py" start
            or exit $status
        end
end
