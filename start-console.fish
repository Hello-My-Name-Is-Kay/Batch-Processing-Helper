#!/usr/bin/env fish
# Start the local Batch Helper web console.
set -l SCRIPT_DIR (dirname (realpath (status current-filename)))
set -l PYTHON "$SCRIPT_DIR/venv/bin/python"
if not test -x "$PYTHON"
    echo "Missing virtualenv Python: $PYTHON" >&2
    echo "Create it with: python3 -m venv '$SCRIPT_DIR/venv'" >&2
    exit 1
end
exec "$PYTHON" "$SCRIPT_DIR/batch_console.py" $argv
