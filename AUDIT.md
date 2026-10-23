# Audit: Batch-Processing-Helper

Audit date: 2026-10-23. Commit audited: `fe3ba7b` plus the local README edits.
Scope: every file in the repo (about 5,700 lines of Python, shell and Markdown).

## How to read this report

Each finding carries one of three evidence levels, so you know what to trust:

| Tag | Meaning |
|---|---|
| **REPRODUCED** | I ran it and saw the failure (Python 3.15, fresh venv, fake providers, no real API calls). |
| **VERIFIED** | Checked against the installed Anthropic SDK types or the official OpenRouter docs. |
| **BY READING** | Concluded from the code. Not executed. Treat as very likely, not certain. |

Not tested at all: real Anthropic or OpenRouter calls (no key used), real cron, `fish` (not installed here), Linux.

## Verdict

The architecture is sound and presentable: a provider abstraction, a history layer, a TUI, an MCP server. **The pipeline does not work end to end today.** Seven independent blockers (P0) stop a first-time user from getting one result through. The test suite is green-ish because it never exercises the code that is broken. All of it is fixable; the P0 list is roughly a day of work.

## Fix status (updated after the P0 fixes)

All seven P0 items, all twenty P1 items and the redundancy / dead-code / doc-drift clean-up are done, each with regression tests in `test_batch_pipeline.py` (tests named `P0-n: ...`, `P1-n: ...` and `Cleanup: ...`). `pyproject.toml` and a GitHub Actions workflow are in place (see "Tooling" below). Still open: the hardening notes, a `LICENSE` file, `systemd/` units, and the rest of the Phase 3-4 plan (the mock provider and the other upgrades). Not verified against the real services: the Anthropic and OpenRouter calls were exercised through fakes only. The suite passes on Python 3.15 and on a real Python 3.9.6 venv.

| Item | Fix | Behaviour changes to know about |
|---|---|---|
| P0-1 | `-I` removed from `batch.sh`, `batch-orchestrator.sh`; `batch.fish` is now a two-line wrapper around `batch.sh` | `batch.sh` picks its interpreter from `BATCH_PYTHON` (project `venv/` if present) instead of activating the venv. `--provider/--model` flag parsing (P1-1) was fixed too, since `--model` is the documented way to choose an OpenRouter model |
| P0-2 | Anthropic `ended` now maps to completed; counts, timestamps and results follow the SDK types; usage is summed from results; model comes from the state file | Anthropic cost is no longer estimated (the old rates were stale and it never ran); tokens are recorded, cost is blank. Result status is `completed` / `failed` for both providers |
| P0-3 | Every routed result is renamed `<id>.result` -> `<id>.routed`; unknown routes escalate; `batch_again` / `live_model` removed from the prompt and docs | Archiving no longer deletes the model output: it stays as `<id>.routed`. A classifier outage escalates once ("Router classification failed") instead of retrying every cycle |
| P0-4 | Providers own their default model (`default_model()`); submit and router use it | OpenRouter model IDs are sent exactly as written: the `:batch` suffix is no longer appended (the OpenRouter docs use plain IDs; not tried against the live API). `batch-config.sh` no longer exports an Anthropic default for `BATCH_MODEL` / `ROUTER_MODEL` |
| P0-5 | MCP loads `batch-submit.py` from its file, uses shared folder defaults, answers unknown methods with `-32601` | Unused `mcp` dependency removed from `requirements.txt` |
| P0-6 | `.env` support (`.env.example`), orchestrator uses `BATCH_PYTHON` and logs Python's stderr, `setup-cron` honours `BATCH_POLL_INTERVAL`, quotes paths and only replaces its own entry | `BATCH_POLL_INTERVAL` takes effect when `setup-cron` runs (whole minutes, rounded up). Re-run `setup-cron` to refresh an existing entry |
| P0-7 | New `batch_common.py` resolves folders with defaults; submit checks credentials and folders before creating the batch, writes atomically, and names the batch ID if bookkeeping fails afterwards | `batch-submit.py` prints a one-line error instead of a traceback. `submit_request()` returns a dict; `submit_batch_request()` still returns `(batch_id, request_id)` |

### P1 fixes

| Item | Fix | Behaviour changes to know about |
|---|---|---|
| P1-1 | Flag parsing rewritten (done with the P0 work); `send` with no message prints usage | None |
| P1-2 | `batch.fish` delegates to `batch.sh` (done with the P0 work) | Not run here: `fish` is not installed. A test runs it where `fish` exists |
| P1-3, 4, 5 | `batch_history.py`: `show` / `aggregates` are real subcommands; `stats` prints per-model aggregates; median of an even count is the mean of the middle two | None (the stored `history.db.json` cache that could hold stale medians was removed in the clean-up) |
| P1-6 | Fixed with P0-2 (timestamps from any provider are coerced to unix time) | None |
| P1-7, 9 | One shared `read_escalations()` / `pipeline_counts()` in `batch_common.py` used by the TUI and MCP server, matching the escalation file the router writes; the dashboard counts history entries, not files | MCP `batch_status` JSON changed: `files` became `results` with `awaiting_routing` / `archived` / `escalations`; `batch_escalations` entries now carry `request_id`, `classification`, `reason`, `content_preview` |
| P1-8 | TUI: panes are plain containers (not `Screen`s) and fill in on start; the refresh method was renamed (`_auto_refresh` is a Textual internal that hid it) | Two bugs this audit had not listed: with `Screen` panes the app started on the wrong tab and key `1` stopped switching, and the 10 s timer and `r` key never worked. Refresh errors now show as a notification |
| P1-10, 11 | `Optional` imported in the TUI; `from __future__ import annotations` in the MCP server | The minimum is now Python 3.9, stated in the README and tested on a 3.9 venv |
| P1-12, 13 | Poll skips completed / failed / cancelled batches, records cancellations, and honours `--provider` | Batches already marked failed are no longer re-checked |
| P1-14 | Every state write goes through `update_state()` (file lock + atomic replace); poll merges only its own changes; a corrupt state file is moved to `.batch-state.corrupt-<time>` instead of crashing or being overwritten | A `.batch-state.lock` file appears next to the state file (git-ignored). POSIX only (`fcntl`) |
| P1-15 | Provider chat calls raise API errors; the router no longer falls back to a hidden, billed batch | A failed classification now escalates with the real error as the reason |
| P1-16 | The classifier prompt fences the result and project context as untrusted data (and defuses tags inside them); only a `text` classification can be archived, anything else is escalated | An `archive` route on any other classification is now escalated with `original_route` kept |
| P1-17 | Status, TUI, MCP and the orchestrator report running / collected / awaiting routing / escalated / archived from the state and result files | `batch.sh status` labels changed accordingly |
| P1-18 | Metrics: throughput is batches per hour of wall-clock time; completed batches come from the state file | JSON keys changed: `completed_requests` -> `completed_batches` (+ `archived_results`), `requests_per_hour` -> `batches_per_hour` |
| P1-19 | OpenRouter: `cancel_batch` and the wrong endpoint docs removed, `finalizing` handled | Cancelling an OpenRouter batch now raises `NotImplementedError` (it never worked) |
| P1-20 | `batch.sh send-file FILE` / `batch-submit.py --file` submit many prompts as one batch (text lines or JSON Lines); the router classifies each result separately; request ids are validated | `--request-id` and item ids must be 1-64 letters, digits, `-` or `_`; the router's `.done` / `.escalate` files are per request, so one batch can create several |

### Clean-up (redundancy, dead code, doc drift)

| Audit item | What was done | Things to know |
|---|---|---|
| Dead files and folders | Deleted `poll_and_results.py`, `.github-ready`, the empty top-level `requests/ responses/ completed/ escalations/ logs/` and `.batch-data/.gitkeep`; `.gitignore` now just ignores `.batch-data/` | `poll_and_results.py` was a blocking, OpenRouter-only watcher that the pipeline did not use; `git checkout -- poll_and_results.py` brings it back |
| Helpers copied 3x | `format_duration`, `format_age`, `read_state`, `load_state`, `pipeline_counts`, `read_escalations` live once in `batch_common.py`; the TUI, MCP server, status, metrics and poll use them; the one-line `load_config()` wrappers in poll, metrics and status are gone | `batch_tui._format_duration` and friends no longer exist |
| Two sources of truth for metrics | Kept both commands, made the difference explicit in METRICS.md (`metrics` = end to end from the state file; `stats` = provider side from history). Removed the `history.db.json` cache: aggregates are computed from `history.jsonl` when asked for | Reading history no longer creates the `history/` folder. An old `history.db.json` is ignored and can be deleted |
| Dead code | Removed `BatchRequest`, `format_user_message`, `register_provider`, the duplicate `beta_client`, `HISTORY_ENTRY_SCHEMA`, the history `log` subcommand, the best-effort import guards (poll, TUI, MCP), `current_screen`, the unused `Button` CSS, the `chmod` in the orchestrator, and the docstring promises of a search box and clickable rows | `register_provider()` is replaced by adding a `(module, class)` pair to `_PROVIDERS` |
| Provider imports | `providers/__init__.py` imports a provider's module only when it is used, so an OpenRouter-only install does not need `anthropic`, and a missing package gives a message saying to run `pip install -r requirements.txt` | The registry now holds `(module, class)` names instead of classes |
| Dependencies | `mcp` was removed earlier; `anthropic` lower bound raised from 0.18.0 to 0.40.0 (0.18 has no batch API). The suite passes on Python 3.9 with anthropic 0.40.0, requests 2.28.0 and textual 0.50.0 | Upper bounds and a lock file are still not set |
| Lint | `ruff check .` reports nothing (settings in `pyproject.toml`: F, E9, B at Python 3.9); a test runs it when ruff is installed | |
| Docs | Rewrote `SETUP.md`, `PIPELINE.md`, `METRICS.md`, `ISSUES.md` and the skill file so they no longer repeat the README or describe removed things (systemd, fish config, the old project path, `:batch`, `history.db.json`, `batch_again`); README layout, history and provider-registration passages fixed | `ISSUES.md` now lists only what is open or unverified |
| Tests that test nothing | Removed two that made real network calls and accepted any outcome, replaced the "pipeline flow" test (which only checked files it wrote itself) with a real submit -> poll -> route run, and made the router-parse test call the router's own parser; the harness now counts a raised `SkipTest` as skipped | The suite no longer has a "live" test that runs offline |

### Tooling (pyproject and CI)

| Item | What was done | Things to know |
|---|---|---|
| `pyproject.toml` | Project name and version, `requires-python = ">=3.9"`, the three dependencies, and the ruff settings (moved from `ruff.toml`, which is deleted: ruff prefers `ruff.toml` over `pyproject.toml`, so having both would hide one) | The project runs from a checkout and is not meant to be pip-installed; `requirements.txt` stays for `pip install -r`. It repeats the dependency list, and a test fails if the two drift apart. No `license`, `authors` or classifiers are set, because there is no `LICENSE` file yet |
| GitHub Actions | `.github/workflows/ci.yml`: on pushes to `main` and on pull requests, Python 3.9 and 3.12 on `ubuntu-latest` install `requirements.txt` plus `ruff==0.17.2`, then run `ruff check .` and `python test_batch_pipeline.py --unit` | `actions/checkout@v7` and `actions/setup-python@v7` (the current majors); read-only token; 15-minute timeout. The ruff version is pinned so a new release cannot break CI on its own; bump it on purpose |
| Consistency test | One test checks that `requires-python`, the dependency lists, the ruff target, the workflow's Python versions and the README agree | |

## P0: blockers (nothing works end to end)

The text below is the original finding for each item.

### P0-1. Every wrapper command crashes: `python3 -I` hides the `providers` package. REPRODUCED
`batch.sh` runs each script as `python3 -I script.py` (lines 79, 88, 89, 94, 102, 108, 113, 137; same in `batch.fish` and `batch-orchestrator.sh:25,31`). Isolated mode removes the script's directory from `sys.path`, but `batch-submit.py:21`, `batch-poll.py:15` and `batch-router.py:19` do `from providers import ...`.

```
$ bash batch.sh send "hello"
ModuleNotFoundError: No module named 'providers'
```
`send`, `poll` and the cron job all fail, so the README Quick Start dies at its first command. **Fix:** drop `-I` (use `-s` if you want to skip user site-packages), or make the scripts a package / insert the path explicitly.

### P0-2. Anthropic (the default provider) batches never complete. VERIFIED + REPRODUCED
`providers/anthropic_provider.py:122-128` maps `succeeded / failed / cancelled / expired`. The SDK's `processing_status` is `Literal["in_progress", "canceling", "ended"]`. A finished batch (`ended`) maps to `PENDING`, so `batch-poll.py` never collects it.

Related errors in the same method:
- `request_counts` has `succeeded, errored, canceled, expired, processing`; the code reads a non-existent `failed` (136-139).
- `batch.requests` and `batch.usage_stats` do not exist on `MessageBatch`, so model, tokens and cost are always empty (144-173). The cost block is dead code.
- The hard-coded rates ($0.25 / $1.25 per million) are stale and ignore the 50% batch discount.
- `get_results` checks `status == "error"` (207); the SDK type is `"errored"`, so errors are never captured.
- Statuses differ between providers (`succeeded` for Anthropic vs `completed` for OpenRouter).

**Fix:** map `ended` to completed, then decide success per request from `request_counts` and result types. Compute cost from the per-result `usage` and a small price table, or drop it.

### P0-3. The router re-processes the same result forever, and two routes do nothing. REPRODUCED
`batch-router.py:236-257`: only `archive` deletes the `.result` file. `escalate` writes the escalation but leaves the file, so every cron cycle re-classifies it with a billed live LLM call and rewrites the escalation. Repro: 3 cycles gave 3 LLM calls, result still present. `batch_again` and `live_model` exist only in the prompt and docs: no re-queue, no handler (3 cycles, 0 requests re-queued). The README mermaid diagram and `PIPELINE.md:172` describe a re-queue that does not exist.
**Fix:** move every routed result to a `processed/` state (or mark it in the state file), default unknown routes to escalate, and either implement or remove `batch_again` / `live_model`.

### P0-4. OpenRouter never gets the model the user configured. REPRODUCED
`batch-submit.py:29,42` always passes `BATCH_MODEL` (default `claude-haiku-4-5-20251001`). The provider's `OPENROUTER_BATCH_MODEL` fallback only applies when `model is None`, which never happens. With `OPENROUTER_BATCH_MODEL=deepseek/deepseek-chat` set, OpenRouter received `claude-haiku-4-5-20251001:batch`. The README's "falls back to BATCH_MODEL" chain is untrue in practice.
Also: the `:batch` suffix is not in OpenRouter's docs. The docs say the model goes in the batch-level `model` field, the example uses a plain ID (`anthropic/claude-haiku-5.5`), and batch-capable models are found via a `variant=batch` filter. **VERIFIED** against the docs (summary-level fetch); confirm with one real call before keeping `_ensure_batch_model`.
The same mismatch hits the router: `ROUTER_MODEL` defaults to an Anthropic ID, and `OPENROUTER_ROUTER_MODEL` (batch-config.sh:40) is never read.

### P0-5. The MCP server's `batch_send` and `batch_poll` fail. REPRODUCED
`batch-mcp.py:191` does `from batch_submit import ...`, but the file is `batch-submit.py` (hyphen), so it raises `No module named 'batch_submit'`. `batch_poll` crashes with a traceback because MCP hosts do not source `batch-config.sh`, so `BATCH_STATE` and friends are unset. Unknown JSON-RPC methods get no reply (the client waits forever). `requirements.txt` lists `mcp>=1.0.0`, which is never imported (the JSON-RPC loop is hand-rolled).

### P0-6. The installed cron job cannot work. BY READING
`setup_cron` (`batch-orchestrator.sh:51`) installs `*/2 * * * * ... poll > /dev/null 2>&1`. Cron runs with a minimal environment, so: no API keys (they are exported in your shell, not in cron), no venv (the orchestrator never activates `venv/`, so `python3` is the system one without `anthropic`), and all output is discarded, so failure is silent. Also `-I` (P0-1), and `BATCH_POLL_INTERVAL` is ignored (`*/2` is hard-coded). Paths with spaces break the cron line, and a second clone in another path is never installed (`grep -F ... poll` early return, lines 54-57).
**Fix:** have the orchestrator source a `.env` file and activate the venv, log stderr to `logs/`, quote paths.

### P0-7. A batch is created (and billed) before local setup is validated. REPRODUCED
`batch-submit.py:63` calls `provider.create_batch(...)`, then line 66 builds `Path(config['requests_dir'])`. If the env vars are unset (MCP, or calling the script directly as its docstring shows) it raises `TypeError` after the batch exists, leaving an orphan with no tracking record. `ISSUES.md` #1 claims Python now has fallback defaults; it does not (submit, poll, router and metrics all `Path(None)`). **Fix:** resolve paths with defaults first, write the tracking record before or atomically with submission.

## P1: bugs and claims that do not hold

| # | Finding | Evidence | Where |
|---|---|---|---|
| P1-1 | `--provider X --model Y send ...` fails with `Unknown command: --model`. The flag loop iterates every index and `break`s on the first value token. This is the documented example in README, SETUP and `help`. `send` with flags but no message passes the `$# -lt 2` check. | REPRODUCED | `batch.sh:29-44, 55` |
| P1-2 | `batch.fish` cannot run: it `source`s `batch-config.sh` (bash syntax), passes `$PY_ARGS` as one string, and lacks `history`, `stats`, `tui`. | BY READING (fish not installed) | `batch.fish:14, 74-80` |
| P1-3 | `batch_history.py show` crashes (`AttributeError: ... 'provider'`): the `show` and `aggregates` aliases have no arguments. | REPRODUCED | `batch_history.py:289, 316-324` |
| P1-4 | `stats` prints per-provider only. README and SKILL claim "per provider and per model". By-model data is computed and shown only in the TUI. | REPRODUCED | `batch_history.py:356-367` |
| P1-5 | Median is wrong for an even count: `_stats([1,2,3,4])['median']` returns 3, not 2.5. | REPRODUCED | `batch_history.py:170` |
| P1-6 | History logging fails for Anthropic: provider returns ISO-string timestamps, `make_history_entry` subtracts them (`TypeError`), and poll swallows it as "history logging skipped". Timestamp types differ per provider and are undocumented. | REPRODUCED | `anthropic_provider.py:140-141`, `batch_history.py:97` |
| P1-7 | TUI Escalations tab raises `KeyError: slice(None, 30)`: `classification` is a dict, the code slices it. It also reads `content` / `reason`, which the escalation file does not have (`response`, `classification.reason`), so previews are always "(no content)". The MCP `_escalations` has the same schema mismatch. | REPRODUCED | `batch_tui.py:373-374`, `batch-mcp.py:291-292` |
| P1-8 | TUI panes are empty on start: `on_screen_mounted` is not a Textual event (should be `on_mount`), so content appears only after the 10 s timer, and `_auto_refresh` swallows every exception (`except Exception: pass`), hiding bugs like P1-7. | REPRODUCED | `batch_tui.py:129,222,283,357,396,519` |
| P1-9 | Dashboard "History: N entries" counts files, not entries ("1 entries" with 5 in the log). | REPRODUCED | `batch_tui.py:165` |
| P1-10 | `Optional` is not imported in the TUI. Works on Python 3.14+ (deferred annotations), `NameError` at import on 3.9-3.13. The unit test passes on 3.15 and would fail on 3.12. | VERIFIED (3.9 snippet) + ruff F821 | `batch_tui.py:105` |
| P1-11 | Python version is inconsistent: `batch-mcp.py` uses `X \| None` (3.10+), providers use 3.9 syntax, README says "Python 3". No `requires-python`. | REPRODUCED (3.9 `TypeError`) | `batch-mcp.py:80,91,327` |
| P1-12 | Failed batches are re-polled and re-logged every cycle forever (only `completed` is skipped). `cancelled` / `expired` are never recorded, so they stay "running" forever. | REPRODUCED | `batch-poll.py:64, 160` |
| P1-13 | `batch-poll.py --provider X` is parsed and ignored (`poll_batches()` takes no argument). | REPRODUCED | `batch-poll.py:194-195` |
| P1-14 | State file read-modify-write is neither locked nor atomic. `poll` loads the state, a concurrent `send` appends, `poll` writes its old copy back and the new batch is lost. A crash mid-write corrupts the JSON and `json.load` (line 57) has no guard. | BY READING | `batch-poll.py:56,177`, `batch-submit.py:84-103` |
| P1-15 | `chat_complete` swallows all exceptions and returns `None` (bad key, 429, network). The router then falls back to submitting a billed classification batch and waits up to 60 s, which hides the real error; that batch is not tracked. | BY READING | `anthropic_provider.py:94-96`, `batch-router.py:122-152` |
| P1-16 | Router prompt injection: untrusted model output is pasted raw into the classifier prompt with no delimiters, so a result can steer its own route (`archive`). Unknown route values silently do nothing instead of failing closed to `escalate`. | BY READING | `batch-router.py:75-90, 234` |
| P1-17 | Status numbers are mislabelled: "Queued" = count of `requests/*.jsonl` (never removed, so it equals everything ever submitted), "Processing" = count of `responses/*.result` (finished, unrouted). Three places repeat it. | BY READING | `batch-status.py:64-70`, `batch_tui.py:140`, `orchestrator:119` |
| P1-18 | "Throughput" = completed requests / sum of latencies of overlapping batches. That is not throughput. `completed_requests` counts `.done` (archived only) while latency counts every completed batch. | BY READING | `batch-metrics.py:131-135` |
| P1-19 | OpenRouter provider implements `cancel_batch` and documents `/cancel` and `/results` endpoints. The OpenRouter docs list cancellation as unsupported and results as inline. The README limitation is right; the code and docstring are wrong. Status map lacks `finalizing`. | VERIFIED | `openrouter_provider.py:6,42-43,329-343,186` |
| P1-20 | One `send` = one single-request batch. There is no way to submit N prompts in one batch (the point of batch APIs) and OpenRouter rate-limits batches per account. The router also reads only `result[0]`. | BY READING + docs | `batch-submit.py`, `batch-router.py:168` |

## README and docs: claims vs reality

| Claim | Reality |
|---|---|
| "Polls every 120 s (configurable)", `BATCH_POLL_INTERVAL` | Variable is defined and never read. Cron is hard-coded to 2 min. |
| `bash batch.sh --provider openrouter --model "<model>" send "task"` | Fails (P1-1). |
| Router "adds 30+ seconds per result" (Limitations), "Router on the live API" (Roadmap), `ISSUES.md` #5 | Stale. The router already uses live `chat_complete`; the 30 s path is only the fallback. |
| `stats` reports "per provider and per model" | CLI prints per provider only (P1-4). |
| "re-queued as the next step" (diagram, `PIPELINE.md:172`) | Not implemented (P0-3). |
| Unit tests "run offline" | Need API keys set: on a fresh clone 2 tests fail (`get_provider` constructs real clients). |
| Test count "21 tests" (SKILL.md) | 23 registered, 21 run in `--unit`. |
| `:batch` suffix appended automatically | Not in OpenRouter docs (P0-4). |
| `poll_and_results.py`: "Collect results" (layout) | It is a blocking, OpenRouter-only status watcher; the pipeline does not use it. |
| `ISSUES.md`: "Tested: submit -> poll -> route (Anthropic)" | Impossible given P0-1 and P0-2. |
| `ISSUES.md` #1 "Python scripts now have fallback defaults" | False (P0-7). |
| SETUP.md: `~/Projects/tools/Claude-Batching`, `git clone <repo>`, `freedom-batch-poll.*`, file tree missing 8 files | Leftovers from the original project; `systemd/` and `LICENSE` do not exist. |
| "Tested on Linux" | Not verifiable from the repo. |
| "typically about 50%" discount; $0.000034 smoke test | Matches OpenRouter docs (50%). The smoke test is not reproducible from the repo. |

Accurate and worth keeping: the OpenRouter limitations (no cancellation, 30-day retention, no ZDR, one model per batch, text and public image URLs, `provider.only` instead of sort) match the official docs.

## Redundancy and dead code

- **Helpers copied 3x:** `_batch_data_dir / _load_state / _count_files / _format_dur` live in both `batch_tui.py` and `batch-mcp.py`; `format_duration` again in `batch-status.py`; `load_config()` is repeated in six scripts, each without defaults. Extract one `batch_common.py` (paths with defaults, atomic and locked state I/O, formatters).
- **Two sources of truth for metrics:** `batch-metrics.py` (state file + `.done` files) vs `batch_history.py` (`history.jsonl`). They can disagree. Keep one. `history.db.json` is a cache rebuilt from the whole log on every write; drop it or compute on read.
- **Dead code:** `BatchRequest` dataclass (base.py:9, tests only), `format_user_message`, `register_provider`, `beta_client` (anthropic_provider.py:26), `HISTORY_ENTRY_SCHEMA`, `routing_times_by_provider`, the `_HISTORY_AVAILABLE` stub dance (batch-poll.py:17-33), `current_screen`, unused `Button` CSS, TUI "/ search" and "click for details" promised in its docstring. ruff finds 34 issues, 24 auto-fixable (unused imports, f-strings, a re-imported `time` in the router).
- **Dead files and folders:** top-level `requests/ responses/ completed/ escalations/ logs/` plus `.gitignore` rules ("kept for compatibility"): nothing writes there. `.github-ready` is an internal checklist ("Create LICENSE", "Systemd timer integration") that tells reviewers the repo is unfinished. `poll_and_results.py` duplicates `batch-poll.py` for one provider.
- **Duplicated docs:** README, SETUP, PIPELINE, METRICS, SKILL and ISSUES restate the same architecture and config, and have drifted (table above). One README plus `docs/` for the deep dives.
- **Dependencies:** `providers/__init__.py` imports `anthropic` at import time, so OpenRouter-only users still need it (lazy-import per provider). `mcp` listed, unused. `jq` is required by `batch.sh send` (line 79) but undocumented. No upper bounds, no lock file.

## Test suite

- 23 tests in a home-grown harness; clean-clone run: **19 pass, 2 fail, 2 skipped**. The 2 failures are missing API keys, not code bugs (tests should set dummy keys). The TUI helper test also fails if `BATCH_DIR` points somewhere without "batch" in the path.
- **Tests that test nothing:** `test_pipeline_local_flow` writes files itself and asserts they exist, never calling poll or router, and is flagged `live=True` so even `--unit` skips it. `test_router_parse_json` copies the parsing logic into the test instead of calling the router.
- **No coverage** for: `batch.sh`, `batch-poll.py`, `route_result`, `batch-submit.py main`, status, metrics, orchestrator, MCP, Anthropic `retrieve_batch` / `get_results`, OpenRouter `retrieve_batch` / `get_results` (mock HTTP). Every P0 above lives in that gap.
- No CI (`.github/workflows` absent), no linter config, no `pyproject.toml`.
- `repro.py`-style fake-provider tests (what I used for this audit) are a ready template for real regression tests.

## Hardening notes (lower priority)

- `request_id` / `custom_id` becomes a filename (`<id>.escalate`, `.done`, `.result`). `--request-id ../../x` escapes the data dir. Validate against `^[A-Za-z0-9_-]{1,64}$`.
- `setup_cron` deletes every crontab line containing `batch-orchestrator.sh` (line 60), not only its own.
- If `project_dir` has no context file, the router sends the first 2,000 characters of that project's `README.md` to the LLM provider (batch-router.py:50-60). Document it or make it opt-in.
- Untyped, unvalidated JSON everywhere (`result['custom_id']`, `batch_info['custom_id']`): one malformed file raises `KeyError` and aborts the cycle for all.
- No retries, no timeouts on the Anthropic client (already in ISSUES.md), no backoff on 429.
- `batch-config.sh` prints key warnings even for `help` and creates directories as a side effect of being sourced.

## Plan to make it CV-ready

**Phase 1: make it work (P0, about a day).** Remove `-I`; fix the Anthropic status / result mapping; router consumption and default-to-escalate; model wiring per provider; orchestrator env + venv + logging; reorder submit; fix the MCP import and env; fix flag parsing with a `while`/`shift` loop.
**Phase 2: prove it works.** Port the repro script into `pytest` (fake providers, mocked HTTP), hermetic fixtures, a GitHub Actions matrix on Python 3.10-3.13 with ruff. Add a real end-to-end test per provider using recorded responses.
**Phase 3: clean up.** `batch_common.py`, atomic and locked state writes (`fcntl`), delete legacy dirs and `.github-ready`, `pyproject.toml` with `requires-python`, lazy provider imports, one source of metrics, a real `LICENSE`, trim docs to README + `docs/`.
**Phase 4: make it shine.**
- A `mock` provider so anyone can run the full pipeline with no API key (best single upgrade for a CV repo).
- `send-file prompts.jsonl` to batch N prompts in one batch.
- Retry with backoff, an escalation webhook, `--json` output on every command, a TUI screenshot or GIF, and a short "design decisions" section.

## What is already good

Clean provider abstraction with a documented extension path; thoughtful OpenRouter limitations section that matches the official docs; append-only history with aggregates; a real TUI and MCP integration (once fixed); explicit UTF-8 handling; no secrets in the repo and `.env` ignored.
