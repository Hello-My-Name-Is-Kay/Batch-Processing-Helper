# Batch Processing Metrics & Performance

Track latency, throughput, and performance across multiple batch providers.

## What's Tracked

Each batch task is instrumented with timing and provider metadata:

- **Provider** (anthropic, openrouter, etc.)
- **Submission time** (unix timestamp + ISO format)
- **Completion time** (unix timestamp + ISO format)
- **End-to-end latency** (seconds, minutes)
- **Routing time** (milliseconds, for classification/decision)
- **Per-provider breakdown** (compare provider performance)

## Viewing Metrics

```bash
# Show formatted metrics (all providers)
bash batch.sh metrics

# Export as JSON
bash batch.sh metrics --json metrics-report.json

# View raw state (all batches)
cat ~/.claude/batch-pipeline/default/.batch-state | jq '.[] | select(.status == "completed") | {custom_id, provider, latency_minutes}'

# Per-provider summary
cat ~/.claude/batch-pipeline/default/.batch-state | jq '[.[]] | group_by(.provider) | map({provider: .[0].provider, count: length, avg_latency: (map(.latency_seconds // 0) | add / length)})'
```

## Key Metrics

### Latency (per-provider + aggregated)
- **Min/Max/Mean/Median:** Time from submission to completion (seconds)
- **StdDev:** Variability in completion time
- **Total:** Cumulative time across all batches

### Routing Time
- **Classification latency:** Time for router to classify and decide route (milliseconds)
- Typically 1-3 seconds (includes live LLM API call)

### Throughput
- **Requests/hour:** Number of batches completed per hour

### Per-Provider Comparison
When using multiple providers, metrics break down by provider to compare:
- Which provider is faster (latency)
- Which provider is more reliable (failure rate)
- Which provider is cheaper (token pricing)

## Example Output

```
=================================================================
BATCH PIPELINE METRICS
=================================================================

📊 Completed Requests: 8

⏱  Latency (seconds, 8 samples)
  ┌──────────┬────────────┐
  │ Min      │    92.34s │
  │ Max      │   312.67s │
  │ Mean     │   178.34s │
  │ Median   │   165.23s │
  │ StdDev   │    72.15s │
  └──────────┴────────────┘
  Total: 1426s (23.8m)

🏭 Per-Provider Breakdown:
  anthropic:
    Requests: 5
    Latency:  mean=145.2s  median=140.1s  range=[92.3s, 215.4s]
  openrouter:
    Requests: 3
    Latency:  mean=233.6s  median=245.5s  range=[145.2s, 312.7s]

⚡ Routing Time (ms, 8 samples)
  ┌──────────┬────────────┐
  │ Min      │      982ms │
  │ Max      │     3451ms │
  │ Mean     │     1834ms │
  │ Median   │     1756ms │
  │ StdDev   │      712ms │
  └──────────┴────────────┘

📈 Throughput: 20.2 req/hr
=================================================================
```

## Data Files

Metrics are stored in three places:

### 1. State File (`.batch-state`)
Contains all batches with timing and provider:
```json
{
  "msgbatch_014gBxiQi7EUXgnzCbxS8f6x": {
    "custom_id": "e05ebc6f-...",
    "provider": "anthropic",
    "submitted_at": "2026-10-23T16:15:00.123456",
    "submitted_at_unix": 1729704900.123456,
    "status": "completed",
    "completed_at": "2026-10-23T16:43:22.456789",
    "completed_at_unix": 1729706602.456789,
    "latency_seconds": 1702.33,
    "latency_minutes": 28.37,
    "model": "claude-haiku-4-5-20251001"
  }
}
```

### 2. Completed Files (`completed/*.done`)
Individual request metadata with routing:
```json
{
  "request_id": "e05ebc6f-...",
  "provider": "openrouter",
  "classification": { ... },
  "routed_at": "2026-10-23T16:43:22.456789",
  "routing_time_ms": 1834.5
}
```

### 3. Logs (`logs/poll.log`, `logs/router.log`)
Human-readable with provider prefix:
```
[2026-10-23T16:43:22] [anthropic] msgbatch_xxx completed in 28.37 min → responses/...
[2026-10-23T16:43:23] [anthropic] uuid-xxx → archive (1834ms) Work completed
[2026-10-23T16:45:12] [openrouter] batch_xxx completed in 15.2 min → responses/...
```

## Integration

### With Monitoring Systems
```bash
bash batch.sh metrics --json | curl -X POST -d @- http://monitoring.local/ingest
```

### With CI/CD
```bash
LATENCY=$(bash batch.sh metrics --json 2>/dev/null | jq '.latency.mean // 0')
if (( $(echo "$LATENCY > 300" | bc -l) )); then
  echo "WARNING: Batch latency exceeding threshold: ${LATENCY}s"
  exit 1
fi
```

### Real-time Dashboard Query
```bash
# Show running batches with age and provider
cat ~/.claude/batch-pipeline/default/.batch-state \
  | jq '[.[] | select(.status == "running") | {id: .custom_id, provider, age_seconds: (now - .submitted_at_unix)}]'
```

## Performance Insights

### What to Watch

- **Latency by provider:** Compare Anthropic vs OpenRouter completion times
- **Latency creeping up:** API queue growing or requests more complex
- **High routing variance (StdDev):** Some requests need more classification work
- **Low throughput:** Batch API rate limiting, or requests taking longer
- **Provider failure rates:** Track which providers are reliable

### Optimization Opportunities

1. **Model selection:** Cheaper models ≈ faster batch completion
   - Anthropic: Haiku processes faster than Sonnet
   - OpenRouter: 200+ models to choose from
2. **Batch size:** Currently single-request batches. Consider batching multiple requests together.
3. **Provider diversity:** Route simple tasks to cheaper providers, complex to powerful ones
4. **Polling frequency:** Default 2 min. Faster polling = faster notification (but more API calls)

## Historical Tracking

```bash
# Export current metrics with timestamp
bash batch.sh metrics --json metrics-$(date +%Y%m%d_%H%M%S).json

# Compare over time
jq '.latency.mean' metrics-*.json
jq '.by_provider.anthropic.latency.mean' metrics-*.json
jq '.by_provider.openrouter.latency.mean' metrics-*.json
```

## Troubleshooting

**No metrics showing?**
- Check for completed batches: `ls completed/`
- Is `.batch-state` file up to date? `ls -l .batch-state`

**Latency very high?**
- Check provider's Batch API status (external delays)
- Check polling frequency (default every 2 min)
- Try a different model or provider

**One provider slower than others?**
- Normal — different providers have different queue depths
- OpenRouter aggregates many models; latency varies by model popularity

## Future Enhancements

- [ ] Percentile latency (p50, p95, p99)
- [ ] Per-model performance (track by specific model used)
- [ ] Cost analysis (tokens used × pricing per provider)
- [ ] Failure rate tracking (by provider)
- [ ] Real-time dashboard (live metrics stream)
- [ ] Slack/webhook alerts on latency threshold breach
- [ ] Smart provider selection (route to fastest/cheapest automatically)