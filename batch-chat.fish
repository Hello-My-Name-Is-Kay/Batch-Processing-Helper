#!/usr/bin/env fish
# Fish shell wrapper for chat_batch.py

set -l SCRIPT_DIR (dirname (realpath (status current-filename)))
set -l PYTHON "$SCRIPT_DIR/venv/bin/python3"
if not test -x "$PYTHON"
    set PYTHON python3
end

set -l message ""
set -l system_flag ""
set -l agent_flag ""
set -l max_tokens_flag ""
set -l poll_interval 30
set -l max_wait 120

set -l i 1
set -l n (count $argv)
while test $i -le $n
    set -l arg $argv[$i]
    switch $arg
        case --system
            test $i -lt $n; or begin; echo "--system requires a value" >&2; exit 1; end
            set system_flag $argv[(math $i + 1)]
            set i (math $i + 2)
        case --agent
            test $i -lt $n; or begin; echo "--agent requires a value" >&2; exit 1; end
            set agent_flag $argv[(math $i + 1)]
            set i (math $i + 2)
        case --max-tokens
            test $i -lt $n; or begin; echo "--max-tokens requires a value" >&2; exit 1; end
            set max_tokens_flag $argv[(math $i + 1)]
            set i (math $i + 2)
        case --poll-interval
            test $i -lt $n; or begin; echo "--poll-interval requires a value" >&2; exit 1; end
            set poll_interval $argv[(math $i + 1)]
            set i (math $i + 2)
        case --max-wait
            test $i -lt $n; or begin; echo "--max-wait requires a value" >&2; exit 1; end
            set max_wait $argv[(math $i + 1)]
            set i (math $i + 2)
        case -- -h --help
            echo "Usage: batch-chat [FLAGS] 'MESSAGE'"
            echo ""
            echo "Submit ONE request as a batch and poll until complete for chat-style AI."
            echo ""
            echo "Flags:"
            echo "  --system TEXT        Set system message"
            echo "  --agent NAME         Tag the batch with an agent/session name"
            echo "  --max-tokens N       Cap reply tokens (default: provider default)"
            echo "  --poll-interval SEC  Seconds between polls (default: 30)"
            echo "  --max-wait MIN       Max minutes to wait (default: 120)"
            echo "  -h --help            Show this help"
            echo ""
            echo "Examples:"
            echo "  batch-chat 'Summarize this text'"
            echo "  batch-chat --agent my-session 'Write code'"
            echo "  echo 'Your prompt' | batch-chat"
            echo ""
            echo "Note: Batch APIs are asynchronous — expect 2+ minutes per turn."
            exit 0
        case --
            set i (math $i + 1)
            break
        case '*'
            # First non-flag arg — take everything remaining as the message
            set message $argv[$i..-1]
            set i (math $n + 1)
    end
end

# Stdin overrides positional message only if stdin is non-tty and has content
if not isatty stdin
    set -l piped (cat)
    if test -n "$piped"
        set message $piped
    end
end

if test -z "$message"
    echo "❌ No message provided. Use --help for usage." >&2
    exit 1
end

set -l py_args
if test -n "$system_flag";     set -a py_args --system "$system_flag";         end
if test -n "$agent_flag";      set -a py_args --agent "$agent_flag";           end
if test -n "$max_tokens_flag"; set -a py_args --max-tokens "$max_tokens_flag"; end
set -a py_args --poll-interval "$poll_interval" --max-wait "$max_wait"
set -a py_args -- "$message"

echo "📤 Submitting batch for chat..."
exec $PYTHON "$SCRIPT_DIR/chat_batch.py" $py_args