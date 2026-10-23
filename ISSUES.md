# Known Issues & Fixes

## Critical

### 1. Environment Variable Initialization
**Issue:** Python scripts receive `None` for config vars if called without proper env setup.

**Cause:** Python scripts rely on `batch-config.sh` to export vars, but direct calls bypass this.

**Impact:** Script fails with `TypeError: argument should be a str or an os.PathLike object`.

**Fix Applied:** Always source `batch-config.sh` before calling Python. Wrappers (`batch.sh`, `batch.fish`) handle this.

**Status:** Workaround in place. Python scripts now have fallback defaults for robustness.

---

## Moderate

### 2. File Encoding Not Explicit
**Issue:** Some file opens don't specify encoding.

**Status:** Fixed in the latest refactor — all file I/O now explicitly uses `encoding='utf-8'`.

---

### 3. JSON Extraction in Routing (String-Based, Fragile)
**Issue:** `batch-router.py` uses string search to extract JSON from LLM response.

**Current:**
```python
start = response_text_full.find('{')
end = response_text_full.rfind('}') + 1
```

**Problem:** If response contains nested JSON or multiple JSON objects, extraction is unreliable.

**Status:** Works for typical responses, but edge cases exist.

**Suggested fix (if reliability needed):**
```python
import re
match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text_full)
if match:
    json_str = match.group()
    classification = json.loads(json_str)
```

---

### 4. No API Timeout on Batch Retrieve
**Issue:** Provider API calls may hang if unreachable.

**Current:** `requests` library has default timeout. Anthropic SDK has no explicit timeout.

**Status:** OpenRouter provider uses 60s timeout. Anthropic provider relies on SDK defaults.

**Fix:** Add timeout parameter to Anthropic client initialization.

---

### 5. Router Uses Batch API for Classification (Slow)
**Issue:** `batch-router.py` submits classification as a batch job and polls, instead of a live API call.

**Impact:** Adds ~30+ seconds to routing time. Should use live (non-batch) API.

**Status:** Known trade-off. Works correctly, but slow. A future optimization could use direct live API calls.

---

## Low Priority

### 6. No Retry Logic on Transient Failures
**Issue:** Provider APIs don't retry on network failures.

**Current behavior:** If poll fails, logs error and moves on.

**Status:** Acceptable for async pipeline. Could add exponential backoff.

### 7. Escalation Notification Missing
**Issue:** No active notification when escalations are created.

**Current:** Manual check with `bash batch.sh escalations` or log watching.

**Status:** Feature request. Could add Slack, desktop notification, or email hooks.

### 8. OpenRouter Results Format Assumes Single Choice
**Issue:** OpenRouter result parser assumes choices[0] exists.

**Impact:** If API returns streaming, tool calls, or other formats, content extraction may fail.

**Status:** Works for standard chat completions. Edge cases need testing.

---

## Testing Gaps

### Not Yet Tested in Production
- ✗ Network interruption during poll (all providers)
- ✗ Disk full (batch directories)
- ✗ Very large batch results (>10MB)
- ✗ Rapid sequential submissions (race conditions)
- ✗ API rate limiting (429 responses)
- ✗ OpenRouter batch with long-running models
- ✗ OpenRouter batch results file (may differ from inline JSONL)

### Tested
- ✓ Normal submit → poll → route flow (Anthropic)
- ✓ JSON parsing of router output
- ✓ File creation and directory structure
- ✓ Syntax (Python and shell)
- ✓ Provider abstraction layer (unit tests)
- ✓ OpenRouter build_request format

---

## Multi-Provider Specific Issues

### 9. OpenRouter Batch API Endpoint Stability
**Issue:** OpenRouter's batch API is newer and may have different behavior than documented.

**Status:** Monitor OpenRouter changelog. The provider uses standard REST with JSONL format.

### 10. Mixed-Provider State File
**Issue:** `.batch-state` can contain batches from multiple providers.

**Impact:** `batch-poll.py` correctly groups by provider. No known issues, but worth monitoring.

### 11. OpenRouter API Key Not Detected
**Issue:** User sets `ANTHROPIC_API_KEY` but selects OpenRouter provider.

**Fix:** Clear error message tells user which key is needed. Provider selection determines which key is checked.

---

## Recommendations

**Before production use:**
1. ✅ Provider abstraction in place
2. ✅ Explicit encoding throughout
3. ✅ Fallback env vars in Python scripts
4. ✅ OpenRouter provider with timeouts
5. ⬜ Improve router to use live API (not batch)
6. ⬜ Add retry logic for transient failures
7. ⬜ Add timeout to Anthropic SDK client

**Nice-to-have (v0.2):**
- Retry logic for transient failures
- Active escalation notifications (Slack, webhook)
- Integration tests for all providers
- Provider performance comparison dashboard
- Smart model selection per provider

**Not urgent:**
- Production monitoring/metrics
- Database backend instead of files
- Web dashboard
- Multi-model batching (different models per request in same batch)

---

## How to Report Issues

Found a bug? Add to this file with:
- **Issue:** Clear description
- **Reproduce:** Steps to trigger
- **Expected:** What should happen
- **Actual:** What does happen
- **Workaround:** How to avoid (if any)