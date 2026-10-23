# Known Issues & Fixes

## Critical

### 1. Environment Variable Initialization
**Issue:** `batch-submit.py` receives `None` for `BATCH_REQUESTS_DIR` if called without proper env setup.

**Cause:** Python scripts rely on `batch-config.sh` to export vars, but direct calls bypass this.

**Impact:** Script fails with `TypeError: argument should be a str or an os.PathLike object`.

**Fix Applied:** Always source `batch-config.sh` before calling Python. Wrappers (`batch.sh`, `batch.fish`) handle this.

**Status:** Workaround in place. Consider adding fallback defaults in Python scripts for robustness.

```python
# batch-submit.py (suggested improvement)
BATCH_DIR = os.environ.get('BATCH_DIR', os.path.expanduser('~/.claude/batch-pipeline/freedom-os'))
requests_dir = os.environ.get('BATCH_REQUESTS_DIR', f'{BATCH_DIR}/requests')
```

---

## Moderate

### 2. File Encoding Not Explicit
**Issue:** `batch-router.py` opens files without specifying encoding.

**File:** `batch-router.py` line ~30

**Current:**
```python
with open(result_file) as f:
    result = json.load(f)
```

**Should be:**
```python
with open(result_file, encoding='utf-8') as f:
    result = json.load(f)
```

**Impact:** On systems with non-UTF-8 locale, may fail silently or corrupt data.

**Status:** Low priority, but best practice.

---

### 3. JSON Extraction in Routing (String-Based, Fragile)
**Issue:** `batch-router.py` uses string search to extract JSON from Haiku response.

**File:** `batch-router.py` line ~95

**Current:**
```python
start = response_text_full.find('{')
end = response_text_full.rfind('}') + 1
```

**Problem:** If response contains nested JSON or multiple JSON objects, extraction is unreliable.

**Better approach:** Use a JSON parser or regex to robustly extract first JSON object.

**Status:** Works for typical responses, but edge cases exist.

**Suggested fix:**
```python
import json
import re

match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text_full)
if match:
    json_str = match.group()
    classification = json.loads(json_str)
```

---

### 4. No API Timeout on Batch Retrieve
**Issue:** `batch-poll.py` calls `client.beta.messages.batches.retrieve()` without timeout.

**File:** `batch-poll.py` line ~42

**Current:**
```python
batch = client.beta.messages.batches.retrieve(batch_id)
```

**Risk:** If API is slow or unreachable, script hangs indefinitely.

**Fix:** Add timeout or circuit breaker logic.

**Status:** Low risk in practice (Anthropic API is reliable), but best practice missing.

---

## Low Priority

### 5. No Retry Logic on Transient Failures
**Issue:** `batch-poll.py` doesn't retry on network failures.

**Current behavior:** If poll fails, it logs the error and moves on.

**Suggested:** Implement exponential backoff for transient errors (timeout, connection reset).

---

### 6. Escalation Notification Missing
**Issue:** When an escalation is created, there's no active notification to the user.

**Current:** User must manually check `bash batch.sh escalations` or watch logs.

**Suggested:** Add optional hooks:
- Systemd notification
- Slack message
- Toast notification (if running in graphical environment)

---

## Testing Gaps

### Not Yet Tested in Production
- ✗ Network interruption during poll
- ✗ Disk full (batch directories)
- ✗ Very large batch results (>10MB)
- ✗ Rapid sequential submissions (race conditions)
- ✗ API rate limiting (429 responses)

### Tested
- ✓ Normal submit → poll → route flow
- ✓ JSON parsing of router output
- ✓ File creation and directory structure
- ✓ Syntax (Python and shell)

---

## Recommendations

**Before production use:**
1. Add explicit encoding to file I/O (issue #2)
2. Add fallback env vars in Python (issue #1, robustness)
3. Improve JSON extraction (issue #3, if reliability needed)
4. Add basic timeout to API calls (issue #4, safety)

**Nice-to-have (v0.1):**
- Retry logic for transient failures
- Active escalation notifications
- Integration tests for edge cases

**Not urgent:**
- Production monitoring/metrics
- Database backend instead of files
- Web dashboard (currently CLI only)

---

## How to Report Issues

Found a bug? Add to this file with:
- **Issue:** Clear description
- **Reproduce:** Steps to trigger
- **Expected:** What should happen
- **Actual:** What does happen
- **Workaround:** How to avoid (if any)
