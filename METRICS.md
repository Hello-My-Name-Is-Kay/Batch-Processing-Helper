# Metrics and history

Two commands report on completed work. They answer different questions and read different data.

| | `bash batch.sh metrics` | `bash batch.sh stats` |
|---|---|---|
| Question | How long does the pipeline take, end to end? | What did the provider's batches cost, and how fast were they? |
| Reads | `.batch-state` and `completed/*.done` | `history/history.jsonl` |
| Latency means | Submit → collected by the poller | Batch created → ended, at the provider |
| Also shows | Routing time, throughput | Tokens, cost, per-model breakdown |

`bash batch.sh history [N]` lists the last N entries of `history.jsonl`.

## `metrics`

```bash
bash batch.sh metrics                   # table, then the same numbers as JSON
bash batch.sh metrics --json out.json   # write the JSON to a file instead
```

- **Completed batches:** batches in the state file with status `completed`. `archived_results` is the number of results the router archived (`completed/*.done`); a batch of several prompts archives several results, and escalated results are not counted there.
- **Latency:** min, max, mean, median and standard deviation of submit → collected, overall and per provider. It includes the time until the next poll noticed the batch had finished.
- **Routing time:** how long the router took to classify and file each archived result (a live LLM call, typically one to a few seconds).
- **Throughput:** batches completed per hour of wall-clock time, from the first submission to the last completion. It needs at least two completed batches, and overlapping batches are not added up.

JSON keys: `completed_batches`, `archived_results`, `total_latency_seconds`, `total_routing_time_ms`, `latency`, `routing_time`, `by_provider`, `throughput` (`batches_per_hour`, `window_seconds`).

## `stats` and `history`

`history.jsonl` gets one line when the poller collects a batch: provider, model, created and ended times, request counts, tokens and cost when the provider reports them. Anthropic does not return a cost, so its entries have tokens only; OpenRouter reports the cost it charged. Aggregates (count, min, max, mean, median, sum) are computed from the log whenever they are asked for, per provider and per `provider/model`.

From Python:

```python
from batch_history import read_history, get_aggregates
read_history()[:5]          # newest first
get_aggregates()["by_model"]
```

## Examples

```bash
# Export with a timestamp, then compare runs
bash batch.sh metrics --json metrics-$(date +%Y%m%d_%H%M%S).json
jq '.latency.mean' metrics-*.json
jq '.by_provider.anthropic.latency.mean' metrics-*.json

# Alert if mean end-to-end latency passes five minutes
bash batch.sh metrics --json /tmp/m.json >/dev/null
jq -e '(.latency.mean // 0) < 300' /tmp/m.json >/dev/null || echo "WARNING: batch latency above 300s"

# Running batches, oldest first, straight from the state file
jq '[to_entries[] | select(.value.status == "running")
     | {batch: .key, provider: .value.provider, age_seconds: (now - .value.submitted_at_unix)}]
    | sort_by(-.age_seconds)' .batch-data/.batch-state
```

## Reading the numbers

- **Latency rising:** the provider's queue is longer, or the requests are bigger. Compare `metrics` (end to end) with `stats` (provider side); a gap that grows means polling is the delay.
- **One provider slower:** normal. Providers have different queue depths, and OpenRouter latency depends on the model.
- **Nothing shown:** `metrics` needs a completed batch in `.batch-state`; `stats` and `history` need a line in `history.jsonl`. Both appear after the first poll that collects a batch.
