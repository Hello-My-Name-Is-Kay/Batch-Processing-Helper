#!/usr/bin/env bash
# Start the local Batch Helper web console.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PYTHON="$PROJECT_DIR/venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    printf 'Missing virtualenv Python: %s\n' "$PYTHON" >&2
    printf 'Create it with: python3 -m venv %q\n' "$PROJECT_DIR/venv" >&2
    exit 1
fi
exec "$PYTHON" "$PROJECT_DIR/batch_console.py" "$@"
