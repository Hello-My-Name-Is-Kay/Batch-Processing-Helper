# Design Note: Request Outbox, Bundling, and Batch Scheduling

> **Status: WIP — proposal only.** Nothing in this document is implemented.
> The current release (`v1.0`) sends each `batch send` immediately as its own provider batch.
> Open decisions are listed in [§12](#12-open-decisions-and-proposed-defaults); implementation should not start until they are resolved.

- **Document:** `DESIGN_REQUEST_OUTBOX.md`
- **Written against:** `main` after commit `72d2b70` (`v1.0`)
- **Related:** [`INDUSTRIAL_READINESS_REVIEW.md`](INDUSTRIAL_READINESS_REVIEW.md) (sections 3.1, 3.3, 3.5, 3.6, 3.7 and 3.8), [`PIPELINE.md`](PIPELINE.md), [`README.md`](README.md) (Batch management)

---

## 1. Problem

Today the helper has bundling and batch management, but no request manager:

- Every `batch send`, `send-file`, console submit or gateway merge window creates a provider batch **immediately**.
- Nothing holds unsent requests, so there is no way to group work into fewer, larger batches over time, to cancel work before it is billed, or to enforce budgets and provider limits before upload.
- The only automatic grouping is the gateway's **one-second** merge window (`batch_gateway.py`, `Dispatcher`, `window=1.0`, `max_batch=100`).

Consequences observed in the code:

| Area | Current behaviour | Consequence |
|---|---|---|
| Batch count | One provider batch per submission | Many small batches; more overhead and polling |
| Cancel before send | Not possible | Work that could be dropped is already billed |
| Limits | Groq file limits checked (`MAX_LINES = 50_000`, `MAX_FILE_BYTES = 200 MB`); Anthropic and OpenRouter have no local checks | Oversized input fails at the provider, after submission |
| Budget | No ceiling per flush or per day | A loop of sends can spend without a cap |
| Crash during submit | Provider batch may exist without local record | Orphan detection exists, but no reconciliation workflow |

## 2. Goals

1. **Hold, then send.** Requests can wait in a local outbox and are sent as one batch per `(provider, model)` when a trigger fires.
2. **Cancel before send.** A pending request can be removed at no provider cost.
3. **Bounded, explainable batches.** Each batch respects a configured maximum count, byte size and age, and any provider hard limit.
4. **Never double-bill.** A failure that might have created a provider batch is never retried automatically.
5. **Backpressure.** A full outbox refuses new work with a clear error instead of growing without limit.
6. **Same tracking afterwards.** Once submitted, a batch uses the existing state file, history, polling, routing and batch management.
7. **No breaking change.** `batch send` keeps its current immediate behaviour until the queue is opted into.

## 3. Non-goals (this phase)

- Distributed queueing or multi-host workers. This is a single-node design; see `INDUSTRIAL_READINESS_REVIEW.md` §4 for the later architecture.
- Automatic retry of paid submissions. Reconciliation is explicit (§8).
- Changing the interactive gateway path. Pi requests stay on the current immediate merge window unless §12 decides otherwise.
- Cross-provider batches. Each provider batch has exactly one provider.
- Exact token pricing. Cost figures are estimates until provider usage is available.

## 4. Terminology

| Term | Meaning |
|---|---|
| **Request** | One prompt with its `custom_id`, owner, provider, model and options |
| **Outbox** | The local SQLite database holding requests that are not yet sent |
| **Flush** | Selecting pending requests and creating one provider batch from them |
| **Intent** | A local record written *before* calling the provider, so a crash can be explained afterwards |
| **Batch group** | The set of requests sharing `(provider, model)` (and owner, if §12 requires it) |
| **Reconciliation** | Operator-led resolution of an intent whose outcome is unknown |

## 5. Current code this design builds on

- `batch_submit.py` — `submit_batch()` validates ids, builds provider requests, calls `provider.create_batch()`, then writes `.batch-state` and the tracking file.
- `providers/base.py` — `BatchProvider.create_batch(requests)` is the only submission entry point.
- `providers/groq_provider.py` — `validate_requests()` runs **before** upload and raises `ValueError` on invalid input, so a validation failure creates nothing at the provider.
- `batch_common.py` — `update_state()` (flock + atomic replace) and `resolve_paths()` (folder layout under `.batch-data/`).
- `batch_management.py` — list, detail, poll-one, cancel (where supported), archive.
- `batch-orchestrator.sh` — cron entry point, runs `batch-poll.py` and `batch-router.py` on `BATCH_POLL_INTERVAL`.
- `batch_gateway.py` — `Dispatcher` merges concurrent requests per model and keeps a separate queue per OpenRouter model.

The outbox adds a layer **in front of** `submit_batch()`. It does not replace the state file, polling, routing or history.

## 6. Proposed design

```text
batch send / send-file / console / MCP
        │
        │  (default today: immediate)            (new: --queue or outbox mode)
        ├──────────────► submit_batch() ──► provider batch ──► .batch-state (unchanged)
        │
        └──────────────► outbox.sqlite (state = pending)
                                 │
                 flush trigger: count | age | explicit "batch flush" | budget
                                 │
                 intent recorded (creating) ──► provider.create_batch() ──► intent created
                                 │                                   └─► requests submitted
                                 │                                        + .batch-state entry
                                 └─ ambiguous failure ─► intent unknown ─► reconciliation (§8)
```

### 6.1 Components

| Component | Responsibility |
|---|---|
| `batch_outbox.py` (new) | Schema, enqueue, cancel, list, flush selection, intent bookkeeping |
| Flush runner | Invoked by `batch flush`, by the cron job, or by the console "Flush now" action |
| Adapters | Thin wrappers that call the existing `submit_batch()` internals for the actual provider call, so validation and tracking stay in one place |
| Console "Queue" page (new) | Pending requests, next flush time, intents needing reconciliation |
| CLI (new subcommands) | `batch queue`, `batch flush`, `batch queue cancel`, `batch reconcile` |

### 6.2 What is *not* changed

- `.batch-state`, the tracking files, polling, the router, history, metrics and the batch management page keep their formats.
- The gateway's merge window stays as it is.
- Existing `batch send` behaviour is unchanged unless `--queue` (or an explicit configuration switch) is given.

## 7. Data model

Storage: `.batch-data/outbox.sqlite`, opened with `journal_mode=WAL`, `synchronous=FULL`, `busy_timeout` set, and file mode `0600`.

```sql
CREATE TABLE requests (
    id              TEXT PRIMARY KEY,              -- custom_id; validated with validate_custom_id()
    request_group   TEXT NOT NULL,                 -- caller grouping id (today's request_id)
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    owner           TEXT,                          -- agent/session, for attribution
    priority        INTEGER NOT NULL DEFAULT 0,
    payload         TEXT NOT NULL,                 -- provider-neutral: message, system, max_tokens, options
    payload_bytes   INTEGER NOT NULL,
    est_tokens      INTEGER,                       -- heuristic estimate, see §9.3
    state           TEXT NOT NULL CHECK (state IN
                    ('pending','reserved','submitting','submitted','cancelled','unknown','rejected')),
    batch_id        TEXT,                          -- set when submitted
    intent_id       TEXT REFERENCES batch_intents(intent_id),
    not_before      REAL,                          -- optional earliest flush time
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    last_error      TEXT                           -- redacted, bounded length
);

CREATE TABLE batch_intents (
    intent_id       TEXT PRIMARY KEY,              -- uuid4
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    request_ids     TEXT NOT NULL,                 -- JSON array of request ids, in order
    state           TEXT NOT NULL CHECK (state IN ('creating','created','unknown','rejected','resolved')),
    batch_id        TEXT,                          -- set when created
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    resolution      TEXT                           -- operator note when resolved
);

CREATE INDEX requests_flush ON requests (provider, model, state, priority DESC, created_at);
CREATE INDEX requests_group ON requests (request_group);
```

Notes:

- `payload` holds prompt text, so it is subject to the privacy rules in §10.
- `request_group` preserves today's behaviour where a multi-prompt `send` shares one request id and custom ids of the form `<group>-0000`, `-0001`, …
- `intent_id` lets every request be traced to the attempt that sent it.

## 8. Lifecycle and crash safety

### 8.1 Request states

```text
           enqueue
              │
              ▼
          pending ──cancel──► cancelled (final, nothing billed)
              │
        flush selects
              ▼
          reserved ──(flush aborted before provider call)──► pending
              │
        intent 'creating' written, provider call starts
              ▼
          submitting
         ┌────┴─────────────────────────┐
  provider returns batch_id     provider call fails
         ▼                       ┌──────┴────────────────┐
     submitted            definitively rejected    outcome unknown
   (tracked in .batch-state)      ▼                        ▼
                               rejected (final)         unknown  ──► reconciliation (§8.3)
```

### 8.2 Two-phase submission

For each flush:

1. **Transaction A (local):** select the batch members, set them to `reserved`, and insert the intent with state `creating`. Commit.
2. **Provider call:** `provider.create_batch(requests)` via the existing adapter. No retry inside this call.
3. **Transaction B (local):** on success, set the intent to `created` with `batch_id`, set members to `submitted`, and append the batch to `.batch-state` (through `update_state()`).
4. On failure, classify the error:

| Failure class | Examples | Action |
|---|---|---|
| **Rejected before any network call** | Local validation (`validate_requests`), missing key, oversized payload | Members → `pending` (with `last_error`) or `rejected` if the content is at fault; intent → `rejected` |
| **Provider definitively refused** | HTTP 4xx other than 408/429 with a clear validation message | Intent → `rejected`; members → `rejected` for content errors, `pending` otherwise |
| **Ambiguous** | Timeout, connection reset after upload, HTTP 5xx, 429 after the body was sent, process killed mid-call | Intent → `unknown`; members → `unknown`. **Never retried automatically.** |

The conservative rule: anything after the first byte of the provider request is treated as ambiguous unless the provider response proves otherwise.

### 8.3 Startup recovery

On every flush or console start:

- Intents still in `creating` (process died between A and B) are moved to `unknown`.
- Their members are shown as **Needs reconciliation**, with the intent id, provider, model and time.
- Nothing is resubmitted.

### 8.4 Reconciliation

`batch reconcile <intent_id>` offers three outcomes:

1. **Found at provider:** the operator supplies or selects the provider batch id. The intent becomes `created`, members become `submitted`, and the batch is added to `.batch-state`.
2. **Confirmed not created:** the operator confirms that no batch exists. Members return to `pending` (new intent, new flush).
3. **Leave alone:** intent stays `unknown` with a note.

Provider batch listing is used to *assist* the operator where the provider offers it. The design does not depend on it.

## 9. Flush policy

### 9.1 Triggers

A `(provider, model)` group is flushed when **any** of these holds:

| Trigger | Default | Configuration |
|---|---|---|
| Count | `pending >= max_batch_requests` | `BATCH_OUTBOX_MAX_REQUESTS` |
| Age | `oldest pending age >= max_age` | `BATCH_OUTBOX_MAX_AGE_MINUTES` |
| Bytes | `sum(payload_bytes) >= max_batch_bytes` | `BATCH_OUTBOX_MAX_BYTES` |
| Explicit | `batch flush` or console "Flush now" | always available |

Before a flush is created, the batch must also satisfy:

- `provider` hard limits (count and bytes), enforced locally and configured per provider (§9.4);
- the **budget** check (§9.3);
- the **concurrency** limit (§9.5).

### 9.2 Selection

Within a group, members are chosen by `priority DESC, created_at ASC`, up to the smaller of the count, byte and budget limits. Requests with a `not_before` in the future are skipped. Remaining requests stay `pending` for the next flush.

### 9.3 Budget and cost

- Each request stores `est_tokens` = a heuristic (characters / 4 for input, plus `max_tokens` for output). The heuristic is labelled an estimate everywhere it is shown.
- Budgets (proposed): `BATCH_OUTBOX_DAILY_TOKEN_BUDGET` and `BATCH_OUTBOX_MAX_FLUSH_TOKENS`. A flush that would exceed either is skipped and reported; it is not split silently.
- Real usage and cost, when the provider reports them, are recorded in history as today. Budgets use estimates until real usage is known, then reconcile.

### 9.4 Provider limits

Limits are data, not scattered constants:

| Provider | Limit source | Status |
|---|---|---|
| Groq | `MAX_LINES = 50_000`, `MAX_FILE_BYTES = 200 MB` (already in `groq_provider.py`) | Enforced today |
| Anthropic | Per-batch request count and size | **To be confirmed** from current provider documentation, then configured |
| OpenRouter | Per-batch request count and size; one model per batch | **To be confirmed**; model grouping is required by design (§9.6) |

The outbox refuses to create a batch that violates a configured limit, instead of letting the provider reject it after submission. Default limits are deliberately conservative until confirmed.

### 9.5 Concurrency and rate

- At most `BATCH_OUTBOX_MAX_IN_FLIGHT_PER_PROVIDER` batches created by the outbox may be running per provider (default 5, proposed). Flushes beyond that wait.
- At most one flush runs per provider at a time (advisory lock, reusing the `flock` approach in `batch_common.state_lock`).

### 9.6 Grouping rules

- Group key: `(provider, model)`. Required because OpenRouter batches must share a model.
- Optional owner grouping (`BATCH_OUTBOX_GROUP_BY_OWNER=1`) keeps cost attribution clean at the price of smaller batches. Default: off (§12).

## 10. Backpressure, privacy and security

- **Backpressure:** `BATCH_OUTBOX_MAX_PENDING` (proposed default 10,000). `enqueue` refuses with a clear message when full. Nothing is silently dropped.
- **Privacy:** pending payloads contain prompt text. The database is owner-only (`0600`, directory `0700`). Payloads are deleted (or replaced by a hash) once a request is `submitted`, unless history retention says otherwise. Encryption at rest is an open question (§12).
- **Redaction:** `last_error` and console output pass through the existing `redact()` rules.
- **No secrets in the database.** Credentials stay in the existing credential/environment sources (`batch_credentials.py`, `batch_environment.py`).
- **Input validation:** request ids use `validate_custom_id()`; payload size is capped before insertion.

## 11. Interfaces

### 11.1 CLI

| Command | Behaviour |
|---|---|
| `batch send --queue "task" ...` | Enqueue instead of sending; prints request ids and the next flush estimate |
| `batch queue` | Pending requests grouped by provider/model, oldest age, budget used |
| `batch queue cancel <request_id>` | Cancel a pending request (no provider cost) |
| `batch flush [--provider P] [--model M] [--dry-run]` | Run the flush rules now; `--dry-run` shows what would be sent |
| `batch reconcile <intent_id>` | Resolve an `unknown` intent (§8.4) |

### 11.2 Console

- **Queue page:** pending counts per group, next trigger time, budget bars, "Flush now" (confirmation required, as for submissions), per-request cancel.
- **Batches page:** a batch created by the outbox shows its intent id and the requests it contains.
- **Attention panel:** intents in `unknown` appear on the Overview.

### 11.3 MCP

- `batch_queue_status` (read-only).
- `batch_send` gains an optional `queue: true`. Flushing and cancelling are **not** exposed to MCP in the first version, to avoid an agent spending budget unattended.

### 11.4 Cron

`batch-orchestrator.sh poll` gains a `flush` step after poll/route, executed only when outbox mode is enabled. Flush errors are logged and do not stop polling.

## 12. Open decisions and proposed defaults

| # | Question | Proposed default | Why |
|---|---|---|---|
| 1 | Flush size and wait | 100 requests **or** 30 minutes, whichever first | Batch providers are already slow, so waiting costs little; 100 matches the gateway and console limit |
| 2 | Interactive gateway (Pi) | Stays immediate | Users expect a prompt start; the existing one-second window still merges near-simultaneous calls |
| 3 | Cancel before send | Yes, free | The main benefit of holding requests |
| 4 | Budget caps | Required before auto-flush is enabled; daily token cap unset until the user sets it | Prevents unattended spending |
| 5 | Grouping | Provider + model; owner grouping off | Matches provider constraints; owner grouping is opt-in |
| 6 | Default mode | `--queue` opt-in for now; default switch decided after M5 | No behaviour change for existing users |
| 7 | Encryption at rest | Not in the first version; owner-only file permissions only | Adds key management; revisit with the industrial work |
| 8 | Scheduler | Cron + explicit `flush` first; long-running scheduler later | Matches the existing operational model |
| 9 | Provider limits | Conservative defaults until confirmed from documentation | Avoids invented numbers |

## 13. Failure modes

| Scenario | Expected behaviour |
|---|---|
| Crash after intent `creating`, before provider call | Intent → `unknown` on restart; members held; no resubmission |
| Crash after provider accepted, before local write | Same as above; reconciliation finds the batch (or the operator records it) |
| Provider timeout | Intent `unknown`; reconciliation |
| Validation failure in a member | That member → `rejected` with reason; the rest of the batch is rebuilt and retried on the next flush, not in place |
| Budget exceeded | Flush skipped and reported; requests stay `pending` |
| Outbox full | Enqueue refused with a clear message |
| Provider outage | Flushes fail as ambiguous or rejected; groups back off; requests keep waiting |
| Two flushes at once | Prevented by the per-provider lock |
| Disk full during Transaction A | Nothing is reserved; error returned to the caller |
| Corrupt `outbox.sqlite` | Moved aside (as `.batch-state` is today) and reported; nothing is deleted |

## 14. Testing plan

All tests run offline by default, using fake providers. Live provider calls are opt-in and capped.

1. **State machine:** every legal transition, and rejection of illegal ones.
2. **Flush triggers:** count, age, bytes, explicit flush, using an injected clock.
3. **Selection:** priority, age order, `not_before`, limit clipping.
4. **Limits and budgets:** refusal before provider call; no partial batch.
5. **Two-phase submission:** provider success, validation failure, timeout, and an exception injected after the provider call returns but before transaction B.
6. **Crash injection:** kill the process at each step (subprocess + signal) and verify recovery and absence of resubmission.
7. **Concurrency:** many concurrent enqueues; multiple flush processes; no lost or duplicated request.
8. **Idempotency:** replaying a flush after `created` does nothing.
9. **Cancel:** cancelled requests are never sent; cancel after submission is refused.
10. **Backpressure:** enqueue beyond the cap is refused, nothing lost.
11. **Compatibility:** `batch send` without `--queue` produces identical state, tracking and history to today (golden-file comparison).
12. **Security:** database and directory permissions; no secrets in rows or logs; redaction of errors.
13. **Load:** a soak test with synthetic requests (for example 50,000 enqueues over several hours) measuring memory, lock wait and flush latency, before any default is changed.

Live smoke test (opt-in, budget-capped): one flush of two requests per enabled provider, after the operator approves the cost.

## 15. Milestones

| Milestone | Deliverable | Exit criteria |
|---|---|---|
| **M0** | This design accepted; §12 resolved | Decisions recorded in this file |
| **M1** | `batch_outbox.py` storage, enqueue, list, cancel (no network) | Tests 1, 10, 12 pass |
| **M2** | Flush with fake provider, intents, startup recovery | Tests 2–9 pass |
| **M3** | CLI (`--queue`, `queue`, `flush`, `cancel`) and cron `flush` step | Test 11 passes; docs updated |
| **M4** | Console Queue page, reconciliation UI, Overview attention item | Browser verification; reconciliation tested end-to-end with fakes |
| **M5** | Limits and budgets per provider; soak test (test 13) | Limits confirmed from provider docs; soak within agreed memory and latency bounds |
| **M6** | Decide default mode | Decision recorded; migration note written |

## 16. Acceptance criteria

- No request is ever sent twice by the outbox, including across crashes (verified by crash-injection tests).
- No request is silently dropped: every enqueued request ends as `submitted`, `cancelled`, `rejected` or `pending`/`unknown` with a visible reason.
- Pending work is visible in the CLI and the console, with age and estimated size.
- Existing `batch send` behaviour is byte-for-byte unchanged when the queue is not used.
- Provider limits and budgets are enforced before upload.

## 17. Risks

| Risk | Mitigation |
|---|---|
| Users expect instant results from queued work | Clear UI labels; queued requests are never presented as answered |
| Budget estimates are inaccurate | Labelled as estimates; conservative caps; reconcile with real usage |
| Unknown provider limits | Conservative defaults; limits are configuration, verified before enabling |
| Prompt data sits in the outbox longer | Owner-only files; deletion on submission; retention setting |
| Larger batches delay the first results | Age trigger caps the wait; explicit flush available |
| Reconciliation burden | Visible in console; minimised by two-phase intents and not retrying |
| Scope creep into a distributed queue | Single-node scope; later architecture is in the industrial review |

## 18. Relationship to the industrial readiness review

This design addresses the single-node part of the review:

- §3.5 (state scaling): the outbox uses SQLite WAL, a step toward the state migration.
- §3.6 and §3.7 (durability, idempotency): intents and two-phase submission.
- §3.3 (outbound concurrency and cost): flush-time limits, budgets and in-flight caps.
- §3.8 (dead letter and replay): `rejected` and `unknown` states are the start of that workflow.

It does **not** address the thread-per-request gateway (§3.2) or the distributed architecture (§4). Those stay in the review's roadmap.
