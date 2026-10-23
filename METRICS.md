# Batch Processing Metrics & Performance

Track latency, throughput, and performance of batch processing.

## What's Tracked

Each batch task is now instrumented with timing:

- **Submission time** (unix timestamp + ISO format)
- **Completion time** (unix timestamp + ISO format)
- **End-to-end latency** (seconds, minutes)
- **Routing time** (milliseconds, for classification/decision)

## Viewing Metrics

```bash
# Show formatted metrics summary
bash batch-metrics.py

# Export as JSON
bash batch-metrics.py --json metrics-report.json

# View raw state (all batches)
cat ~/.claude/batch-pipeline/freedom-os/.batch-state | jq '.[] | select(.status == "completed") | {custom_id, latency_minutes}'
```

## Key Metrics

### Latency
- **Min/Max/Mean/Median:** Time from submission to completion (seconds)
- **StdDev:** Variability in completion time
- **Total:** Cumulative time across all batches

### Routing Time
- **Classification latency:** Time for router to classify and decide route (milliseconds)
- Typically 1-3 seconds (includes live Haiku API call)

### Throughput
- **Requests/hour:** Number of batches completed per hour

## Example Output

```
============================================================
BATCH PIPELINE METRICS
============================================================

Completed Requests: 5

--- Latency (seconds, 5 samples) ---
  Min:     120.45s
  Max:     245.67s
  Mean:    178.34s
  Median:  165.23s
  StdDev:  48.92s
  Total:   891s (14.8 min)

--- Routing Time (milliseconds, 5 samples) ---
  Min:     1245ms
  Max:     2890ms
  Mean:    1834ms
  Median:  1756ms
  StdDev:  612ms
  Total:   9170ms

--- Throughput ---
  Requests/hour: 20.1

============================================================
```

## Data Files

Metrics are stored in three places:

### 1. State File (`.batch-state`)
Contains all batches, including timing:
```json
{
  "msgbatch_014gBxiQi7EUXgnzCbxS8f6x": {
    "custom_id": "e05ebc6f-d81b-407f-b4e4-88214716f241",
    "submitted_at": "2026-10-23T16:15:00.123456",
    "submitted_at_unix": 1729704900.123456,
    "status": "completed",
    "completed_at": "2026-10-23T16:43:22.456789",
    "completed_at_unix": 1729706602.456789,
    "latency_seconds": 1702.333333,
    "latency_minutes": 28.37
  }
}
```

### 2. Completed Files (`completed/*.done`)
Individual completed request metadata:
```json
{
  "request_id": "e05ebc6f-d81b-407f-b4e4-88214716f241",
  "classification": { ... },
  "routed_at": "2026-10-23T16:43:22.456789",
  "routing_time_ms": 1834.5
}
```

### 3. Logs (`logs/poll.log`, `logs/router.log`)
Human-readable log entries with latency:
```
[2026-10-23T16:43:22.456789] msgbatch_014gBxiQi7EUXgnzCbxS8f6x completed in 28.37 min → responses/...
[2026-10-23T16:43:23.567890] e05ebc6f-d81b-407f-b4e4-88214716f241 → archive (1834ms) Work completed
```

## Integration

### With Monitoring Systems

Export metrics to JSON for integration with monitoring:
```bash
bash batch-metrics.py --json | curl -X POST -d @- http://monitoring.local/ingest
```

### With CI/CD

Check latency thresholds in automated tests:
```bash
LATENCY=$(bash batch-metrics.py --json | jq '.latency.mean')
if (( $(echo "$LATENCY > 300" | bc -l) )); then
  echo "WARNING: Batch latency exceeding threshold: ${LATENCY}s"
  exit 1
fi
```

### Dashboard Query

Query the state file for real-time dashboard:
```bash
cat ~/.claude/batch-pipeline/freedom-os/.batch-state | jq '[.[] | select(.status == "running") | {id: .custom_id, age_seconds: (now - .submitted_at_unix)}]'
```

## Performance Insights

### What to Watch

- **Latency creeping up:** Indicates API queue is growing or requests are more complex
- **High routing variance (StdDev):** Some requests need more classification work
- **Low throughput:** Batch API is limiting, or requests take longer than expected

### Optimization Opportunities

1. **Batch size:** Currently single-request batches. Consider batching multiple requests together.
2. **Model selection:** Routing uses Haiku. Could use cheaper model if accuracy acceptable.
3. **Timeout tuning:** Polling interval (default 2 min) affects latency perception. Faster polling = faster notification.

## Historical Tracking

Metrics are cumulative. To track changes over time:

```bash
# Export current metrics
bash batch-metrics.py --json > metrics-$(date +%Y%m%d_%H%M%S).json

# Compare over time
jq '.latency.mean' metrics-20261023_*.json | gnuplot
```

## Troubleshooting

**No metrics showing?**
- Check: Are there completed batches? `ls completed/`
- Check: Is `.batch-state` file up to date? `ls -l .batch-state`

**Latency very high?**
- Check Anthropic Batch API status (external delays)
- Check polling frequency (every 2 min by default)
- Check router classification time (may be doing extra work)

**Missing timing data?**
- Old batches (before metrics added) won't have timestamps
- New batches should have `submitted_at_unix` and `completed_at_unix`

## Future Enhancements

- [ ] Percentile latency (p50, p95, p99)
- [ ] Per-model performance (track by Claude model used)
- [ ] Cost analysis (tokens used × pricing)
- [ ] Failure rate tracking (failed vs completed)
- [ ] Real-time dashboard (live metrics stream)
- [ ] Slack/webhook alerts on latency threshold breach
