#!/usr/bin/env fish
# Batch Pipeline wrapper (fish shell)
# Delegates to batch.sh so both shells share one implementation: batch.sh
# loads batch-config.sh (bash syntax) and picks the project's Python itself.

set -l SCRIPT_DIR (dirname (realpath (status current-filename)))

bash "$SCRIPT_DIR/batch.sh" $argv
