# Frank Lloyd — Stage 1 Data Model
*Status: DESIGN PASS — no implementation exists.*  
*Last updated: 2026-04-11*  
*Reference: STAGE1_FLOW.md, SPEC_SCHEMA.md, STAGING_MODEL.md*

---

## Why this document exists

STAGE1_FLOW.md defined the lifecycle. STAGING_MODEL.md defined the directory structure.
SPEC_SCHEMA.md defined the spec format. But the four contracts that BUILD-002 and the
approval workflow must read and write were not formally specified, and two inconsistencies
existed in prior docs:

1. **spec.json vs spec.yaml** — STAGING_MODEL referenced `spec.json` + `spec.md` separately;
   SPEC_SCHEMA defines a single `spec.yaml`. Resolution: `spec.yaml` is canonical.

2. **Build log event names** — STAGING_MODEL listed events like `approved`, `promoted`, `staged`
   which are Stage 2+ concerns. This doc defines Stage 1–only events.

This doc is the authoritative schema contract. When BUILD-002 is implemented,
it reads these schemas — not STAGING_MODEL or STAGE1_FLOW.

---

## Directory layout (Stage 1 only)

```
data/frank_lloyd/                        ← tracked in git
  build_log.jsonl                    ← append-only, one entry per event
  requests/
    BUILD-001_request.json           ← Peter writes, immutable after creation
    BUILD-002_request.json
  archives/
    BUILD-001/                       ← written at stage completion
      request.json                   ← copy of request
      spec.yaml                      ← copy of approved spec
      preflight.md                   ← copy of pre-flight answers
      decision.json                  ← operator decision record
      manifest.json                  ← archive contents index

staging/frank_lloyd/                     ← gitignored, ephemeral
  BUILD-002/
    spec.yaml                        ← Frank Lloyd writes during spec production
    preflight.md                     ← Frank Lloyd writes during spec production
    .build.lock                      ← created on build start, deleted on completion

data/frank_lloyd/build_log.jsonl         ← programmatic record of all events
```

**What is tracked in git:** everything under `data/frank_lloyd/`  
**What is gitignored:** everything under `staging/`  
**File that must pre-exist for `GET /frank-lloyd/status` to work:** none — all reads handle missing files gracefully

---

## Schema 1: Request JSON

**File:** `data/frank_lloyd/requests/{build_id}_request.json`  
**Who creates it:** Peter (written immediately when request is queued)  
**Mutability:** Immutable after creation — Frank Lloyd and the operator never modify this file  
**Peter writes all fields except the ones the operator supplies via chat**

### Field table

| Field | Type | Required | Author | Notes |
|---|---|---|---|---|
| `request_id` | string | Yes | Peter | e.g. `"BUILD-002"` — assigned by Peter |
| `title` | string | Yes | Operator via Peter | Short human-readable name |
| `description` | string | Yes | Operator via Peter | Plain English — what is wanted and why |
| `requester` | string | Yes | Peter | Always `"operator"` at Stage 1 |
| `requested_at` | ISO 8601 | Yes | Peter | Timestamp when request was queued |
| `success_criteria` | string | Yes | Operator via Peter | Specific and testable — not "works correctly" |
| `build_type_hint` | string | No | Operator via Peter | Peter's best guess from SPEC_SCHEMA build types |
| `context_refs` | string[] | No | Operator via Peter | Relevant doc/file paths |
| `constraints` | string[] | No | Operator via Peter | Explicit "do not" list |
| `urgency` | string | No | Operator via Peter | `"normal"` or `"high"`. Default: `"normal"` |

### Example — BUILD-002

```json
{
  "request_id": "BUILD-002",
  "title": "Frank Lloyd status endpoint",
  "description": "Read-only GET /frank-lloyd/status endpoint that returns pending and completed builds. Reads data/frank_lloyd/requests/ and data/frank_lloyd/build_log.jsonl. Must not crash if data/frank_lloyd/ is empty or missing.",
  "requester": "operator",
  "requested_at": "2026-04-11T15:00:00+00:00",
  "success_criteria": "GET /frank-lloyd/status returns valid JSON with pending_builds, completed_builds, and summary. Returns empty lists when no builds exist. Returns 200 if data/frank_lloyd/ does not exist.",
  "build_type_hint": "platform_capability",
  "context_refs": [
    "docs/frank_lloyd/STAGE1_FLOW.md",
    "docs/frank_lloyd/DATA_MODEL.md"
  ],
  "constraints": [
    "Read-only — no writes to any file",
    "Must read from disk, not return static state",
    "Handle missing data/frank_lloyd/ gracefully"
  ],
  "urgency": "normal"
}
```

---

## Schema 2: Build log line

**File:** `data/frank_lloyd/build_log.jsonl`  
**Format:** One JSON object per line (JSONL), append-only — never rewritten or truncated  
**Pattern:** Same as `observability/event_log.py` — swallow write errors, skip malformed lines on read  
**Who writes:** Peter writes `request_queued`; Frank Lloyd writes all subsequent events

### Stage 1 valid events

| Event | Written by | When | Terminal? |
|---|---|---|---|
| `request_queued` | Peter | Immediately when request file is created | No |
| `spec_ready` | Frank Lloyd | When spec.yaml and preflight.md land in staging | No |
| `spec_approved` | Frank Lloyd | After operator gives approval | Yes |
| `spec_rejected` | Frank Lloyd | After operator rejects (within a revision cycle) | Yes |
| `abandoned` | Frank Lloyd | After 3rd rejection cycle with no resolution | Yes |
| `blocked` | Frank Lloyd | When LM is unavailable and spec cannot be generated | No |

> **`blocked` event semantics:** Non-terminal, non-advancing. The build stays in
> `pending_spec` state — `blocked` is not in the status derivation table below,
> so it does not change the derived status. Frank Lloyd writes `blocked.md` to the
> staging directory alongside this event. The build can be retried once the LM is
> available; the next spec generation attempt will overwrite the blocked state.
>
> **Future events (Stage 2+, not valid at Stage 1):** `build_started`, `staged`, `sentinel_passed`,
> `sentinel_failed`, `code_approved`, `promoted`. Do not write these at Stage 1.

### Field table (core — present in every line)

| Field | Type | Required | Notes |
|---|---|---|---|
| `timestamp` | ISO 8601 | Yes | When this event was written |
| `build_id` | string | Yes | e.g. `"BUILD-002"` |
| `event` | string | Yes | One of the Stage 1 valid events above |
| `notes` | string\|null | No | Free-text context — null if not provided |
| `extra` | object\|null | No | Event-specific structured data — see below |

### Extra fields by event type

**`request_queued` extra:**
```json
"extra": {
  "title": "Frank Lloyd status endpoint",
  "build_type_hint": "platform_capability",
  "requester": "operator"
}
```

**`spec_ready` extra:**
```json
"extra": {
  "staging_path": "staging/frank_lloyd/BUILD-002"
}
```

**`spec_approved` extra:**
```json
"extra": {
  "build_type": "platform_capability",
  "risk_level": "critical",
  "new_files": ["app/routes/builder_status.py"],
  "modified_files": ["app/main.py"],
  "sentinel_scope": "targeted",
  "stage_completed": 1,
  "stage2_authorized": false
}
```

**`spec_rejected` extra:**
```json
"extra": {
  "revision_cycle": 1,
  "reason": "Scope too wide — asked to add pagination"
}
```

**`abandoned` extra:**
```json
"extra": {
  "revision_cycles_completed": 3,
  "reason": "No resolution after 3 revision cycles"
}
```

### Example log sequence — BUILD-002 lifecycle

```jsonl
{"timestamp":"2026-04-11T15:00:00+00:00","build_id":"BUILD-002","event":"request_queued","notes":null,"extra":{"title":"Frank Lloyd status endpoint","build_type_hint":"platform_capability","requester":"operator"}}
{"timestamp":"2026-04-11T15:20:00+00:00","build_id":"BUILD-002","event":"spec_ready","notes":null,"extra":{"staging_path":"staging/frank_lloyd/BUILD-002"}}
{"timestamp":"2026-04-11T15:45:00+00:00","build_id":"BUILD-002","event":"spec_approved","notes":"Scope is right. Handle missing dir gracefully.","extra":{"build_type":"platform_capability","risk_level":"critical","new_files":["app/routes/builder_status.py"],"modified_files":["app/main.py"],"sentinel_scope":"targeted","stage_completed":1,"stage2_authorized":false}}
```

### Status derivation (for GET /frank-lloyd/status)

The current status of any build is derived from its latest event in the log:

| Latest event | Derived status | Bucket |
|---|---|---|
| `request_queued` | `pending_spec` | pending |
| `spec_ready` | `pending_review` | pending |
| `spec_approved` | `spec_approved` | completed |
| `spec_rejected` | `spec_rejected` | completed |
| `abandoned` | `abandoned` | completed |

No request file read is required for status derivation — the log is the authoritative source.
The request file is needed only for full build detail (`GET /frank-lloyd/{build_id}`).

---

## Schema 3: Archive manifest

**File:** `data/frank_lloyd/archives/{build_id}/manifest.json`  
**Who creates it:** Frank Lloyd, written as the last step of archive creation  
**When:** At every terminal outcome: `spec_approved`, `spec_rejected`, `abandoned`  
**Mutability:** Immutable once written  

> Rejected and abandoned builds get archives too. The archive is the governance record —
> it exists for every build that reached a terminal state, regardless of outcome.

### Field table

| Field | Type | Required | Author | Notes |
|---|---|---|---|---|
| `build_id` | string | Yes | Frank Lloyd | |
| `archived_at` | ISO 8601 | Yes | Frank Lloyd | When this manifest was written |
| `stage` | int | Yes | Frank Lloyd | Always `1` at Stage 1 |
| `outcome` | string | Yes | Frank Lloyd | `spec_approved`, `spec_rejected`, or `abandoned` |
| `contents` | object[] | Yes | Frank Lloyd | One entry per file in the archive |
| `contents[].filename` | string | Yes | Frank Lloyd | Filename only (no path — relative to archive dir) |
| `contents[].author` | string | Yes | Frank Lloyd | `"peter"`, `"builder"`, or `"operator"` |
| `contents[].written_at` | ISO 8601 | Yes | Frank Lloyd | When the original file was written |
| `contents[].sha256` | string\|null | No | Frank Lloyd | Hash of file contents — null is acceptable at Stage 1 |

> `manifest.json` does not include itself in `contents` (circular reference).

### Standard archive contents at Stage 1

| Filename | Author | Present when |
|---|---|---|
| `request.json` | Peter | Always (copy of request packet) |
| `spec.yaml` | Frank Lloyd | Always (even for rejected — last spec revision is archived) |
| `preflight.md` | Frank Lloyd | Always |
| `decision.json` | Frank Lloyd | Always |

### Example — BUILD-002 after approval

```json
{
  "build_id": "BUILD-002",
  "archived_at": "2026-04-11T15:46:00+00:00",
  "stage": 1,
  "outcome": "spec_approved",
  "contents": [
    {
      "filename": "request.json",
      "author": "peter",
      "written_at": "2026-04-11T15:00:00+00:00",
      "sha256": null
    },
    {
      "filename": "spec.yaml",
      "author": "builder",
      "written_at": "2026-04-11T15:20:00+00:00",
      "sha256": null
    },
    {
      "filename": "preflight.md",
      "author": "builder",
      "written_at": "2026-04-11T15:20:00+00:00",
      "sha256": null
    },
    {
      "filename": "decision.json",
      "author": "builder",
      "written_at": "2026-04-11T15:45:00+00:00",
      "sha256": null
    }
  ]
}
```

---

## Schema 3b: Decision record

**File:** `data/frank_lloyd/archives/{build_id}/decision.json`  
**Who creates it:** Frank Lloyd, written immediately after operator makes a decision  
**Covers:** Both approval and rejection (outcome field distinguishes them)

> Named `decision.json`, not `approval.json`, because it records approval OR rejection.

### Field table

| Field | Type | Required | Author | Notes |
|---|---|---|---|---|
| `build_id` | string | Yes | Frank Lloyd | |
| `outcome` | string | Yes | Frank Lloyd | `"spec_approved"`, `"spec_rejected"`, or `"abandoned"` |
| `stage` | int | Yes | Frank Lloyd | Always `1` at Stage 1 |
| `decided_at` | ISO 8601 | Yes | Frank Lloyd | When this record was written |
| `decided_by` | string | Yes | Frank Lloyd | Always `"operator"` at Stage 1 |
| `notes` | string\|null | Yes | Operator (recorded by Frank Lloyd) | Operator's stated reason or approval note |
| `deferred_items` | string[] | No | Operator (recorded by Frank Lloyd) | Items explicitly deferred to later pass. Null or empty for rejections. |
| `stage2_authorized` | bool | No | Operator (recorded by Frank Lloyd) | Explicit authorization to proceed to Stage 2. Default: `false`. Null for rejections. |
| `spec_hash` | string\|null | No | Frank Lloyd | SHA256 of approved spec.yaml. Optional at Stage 1. |
| `revision_cycle` | int\|null | No | Frank Lloyd | Which revision cycle this decision ends. Null if first attempt. |

### Example — approved

```json
{
  "build_id": "BUILD-002",
  "outcome": "spec_approved",
  "stage": 1,
  "decided_at": "2026-04-11T15:45:00+00:00",
  "decided_by": "operator",
  "notes": "Scope is right. Must handle missing data/frank_lloyd/ gracefully — return empty lists.",
  "deferred_items": ["Pagination for large build lists — add when build count > 20"],
  "stage2_authorized": false,
  "spec_hash": null,
  "revision_cycle": null
}
```

### Example — rejected (revision requested)

```json
{
  "build_id": "BUILD-002",
  "outcome": "spec_rejected",
  "stage": 1,
  "decided_at": "2026-04-11T15:30:00+00:00",
  "decided_by": "operator",
  "notes": "Scope too wide — do not show staging directory contents in status response.",
  "deferred_items": null,
  "stage2_authorized": null,
  "spec_hash": null,
  "revision_cycle": 1
}
```

---

## Schema 4: Frank Lloyd status response

**Endpoint:** `GET /frank-lloyd/status`  
**Data sources:** `data/frank_lloyd/build_log.jsonl` (primary) + `data/frank_lloyd/requests/` (for title fallback only)  
**Not required:** staging directory read — status is derived entirely from the log

### Field table

| Field | Type | Required | Notes |
|---|---|---|---|
| `builder_stage` | int | Yes | Hardcoded `1` until Stage 2 criteria are formally met |
| `pending_builds` | object[] | Yes | Builds with latest event `request_queued` or `spec_ready` |
| `completed_builds` | object[] | Yes | Builds with latest event `spec_approved`, `spec_rejected`, or `abandoned` |
| `summary` | object | Yes | Counts |
| `summary.pending_count` | int | Yes | |
| `summary.completed_count` | int | Yes | |
| `summary.approved_count` | int | Yes | Subset of completed |
| `summary.rejected_count` | int | Yes | Subset of completed |
| `summary.abandoned_count` | int | Yes | Subset of completed |

### Pending build item fields

| Field | Type | Present when |
|---|---|---|
| `build_id` | string | Always |
| `title` | string | From `request_queued` event's extra.title |
| `status` | string | `"pending_spec"` or `"pending_review"` |
| `requested_at` | ISO 8601 | From `request_queued` event timestamp |
| `build_type_hint` | string\|null | From `request_queued` event extra |

### Completed build item fields

| Field | Type | Present when |
|---|---|---|
| `build_id` | string | Always |
| `title` | string | From `request_queued` event's extra.title |
| `status` | string | `"spec_approved"`, `"spec_rejected"`, or `"abandoned"` |
| `stage_completed` | int | From terminal event extra (null for rejected/abandoned) |
| `requested_at` | ISO 8601 | From `request_queued` event timestamp |
| `resolved_at` | ISO 8601 | From terminal event timestamp |
| `build_type` | string\|null | From `spec_approved` extra (null if rejected/abandoned) |
| `risk_level` | string\|null | From `spec_approved` extra (null if rejected/abandoned) |

### Example — one pending, one completed

```json
{
  "builder_stage": 1,
  "pending_builds": [
    {
      "build_id": "BUILD-002",
      "title": "Frank Lloyd status endpoint",
      "status": "pending_review",
      "requested_at": "2026-04-11T15:00:00+00:00",
      "build_type_hint": "platform_capability"
    }
  ],
  "completed_builds": [
    {
      "build_id": "BUILD-001",
      "title": "Event log query endpoint",
      "status": "spec_approved",
      "stage_completed": 1,
      "requested_at": "2026-04-11T10:00:00+00:00",
      "resolved_at": "2026-04-11T10:30:00+00:00",
      "build_type": "platform_capability",
      "risk_level": "critical"
    }
  ],
  "summary": {
    "pending_count": 1,
    "completed_count": 1,
    "approved_count": 1,
    "rejected_count": 0,
    "abandoned_count": 0
  }
}
```

### Example — empty (no builds exist)

```json
{
  "builder_stage": 1,
  "pending_builds": [],
  "completed_builds": [],
  "summary": {
    "pending_count": 0,
    "completed_count": 0,
    "approved_count": 0,
    "rejected_count": 0,
    "abandoned_count": 0
  }
}
```

---

## Data ownership summary

| File / field | Written by | Read by | Immutable after? |
|---|---|---|---|
| `requests/{id}_request.json` | Peter | Frank Lloyd, GET /builder/{id} | Yes — never modified |
| `build_log.jsonl` (request_queued) | Peter | GET /frank-lloyd/status | Yes — append-only |
| `build_log.jsonl` (all other events) | Frank Lloyd | GET /frank-lloyd/status | Yes — append-only |
| `staging/BUILD-N/spec.yaml` | Frank Lloyd | Operator, Frank Lloyd | No — revised during rejection cycles |
| `staging/BUILD-N/preflight.md` | Frank Lloyd | Operator | No — revised during rejection cycles |
| `archives/{id}/request.json` | Frank Lloyd (copy) | Audit only | Yes |
| `archives/{id}/spec.yaml` | Frank Lloyd (copy) | Audit only | Yes |
| `archives/{id}/preflight.md` | Frank Lloyd (copy) | Audit only | Yes |
| `archives/{id}/decision.json` | Frank Lloyd (records operator decision) | GET /builder/{id} | Yes |
| `archives/{id}/manifest.json` | Frank Lloyd | Audit only | Yes |

---

## Full lifecycle example using BUILD-002

This traces the exact sequence of file operations for a successful Stage 1 build.

```
T=15:00  Operator: "I want a GET /frank-lloyd/status endpoint that reads from disk."

T=15:01  Peter: assigns BUILD-002
         Peter writes: data/frank_lloyd/requests/BUILD-002_request.json
         Peter writes: build_log.jsonl ← event: request_queued
         Peter responds: "Queued BUILD-002: Frank Lloyd status endpoint."

T=15:05  Frank Lloyd session starts
         Frank Lloyd reads: data/frank_lloyd/requests/BUILD-002_request.json
         Frank Lloyd creates: staging/frank_lloyd/BUILD-002/ + .build.lock

T=15:15  Frank Lloyd runs pre-flight (8 questions):
         - CAPABILITY_REGISTRY: no existing status endpoint
         - House domain: platform capability, not house-specific
         - File set: app/routes/builder_status.py (new) + app/main.py (modified)
         - Off-limits: app/main.py is critical (one include line, same as BUILD-001)
         - Layer: Operating services layer, read-only
         - Blast radius: wrong code → 200 with bad data or 500; no state corrupted
         - Test coverage: tests/test_builder_status.py (new)
         - Approval: spec approval + main.py include line approval + promotion approval

T=15:20  Frank Lloyd writes: staging/frank_lloyd/BUILD-002/spec.yaml
         Frank Lloyd writes: staging/frank_lloyd/BUILD-002/preflight.md
         Frank Lloyd writes: build_log.jsonl ← event: spec_ready
         Frank Lloyd: "Spec ready: staging/frank_lloyd/BUILD-002/"

T=15:20  Operator reads spec.yaml and preflight.md

T=15:45  Operator: "Approved. Handle missing dir gracefully. Defer pagination."

T=15:45  Frank Lloyd writes: data/frank_lloyd/archives/BUILD-002/request.json   (copy)
         Frank Lloyd writes: data/frank_lloyd/archives/BUILD-002/spec.yaml       (copy)
         Frank Lloyd writes: data/frank_lloyd/archives/BUILD-002/preflight.md    (copy)
         Frank Lloyd writes: data/frank_lloyd/archives/BUILD-002/decision.json   (approval record)
         Frank Lloyd writes: data/frank_lloyd/archives/BUILD-002/manifest.json   (contents index)
         Frank Lloyd writes: build_log.jsonl ← event: spec_approved
         Frank Lloyd removes: staging/frank_lloyd/BUILD-002/.build.lock

T=15:46  Frank Lloyd confirms: "BUILD-002 spec approved. Stage 1 complete."
         "stage2_authorized=false — Stage 2 code generation is a separate decision."

--- Stage 1 ends ---

Now GET /frank-lloyd/status would return:
  pending_builds: []
  completed_builds: [{build_id: BUILD-002, status: spec_approved, ...}]
```

---

## Naming and path decisions requiring human direction

These are open questions. Defaults are noted but the operator should confirm before BUILD-002 is implemented.

### 1. BUILD-N ID format
**Default:** Zero-padded 3 digits — `BUILD-001`, `BUILD-002`.  
**Alternative:** Plain — `BUILD-1`, `BUILD-2`.  
**Why it matters:** Affects lexicographic sorting in directory listings and log reads.  
**Recommendation:** Keep zero-padded (consistent with existing `BUILD-001` reference).

### 2. Request file naming
**Default:** `data/frank_lloyd/requests/BUILD-002_request.json`  
**Alternative:** `data/frank_lloyd/requests/BUILD-002.json`  
**Why it matters:** The `_request` suffix disambiguates from other per-build files.  
**Recommendation:** Keep `_request` suffix.

### 3. Staging directory cleanup policy
**Question:** When does `staging/frank_lloyd/BUILD-N/` get cleaned up?  
**Options:**  
- (a) After `spec_approved` — staging is irrelevant once archived
- (b) Only after Stage 2 promotion — staging may be needed for code generation
- (c) Never explicitly — gitignore handles it; developer cleans manually  
**Recommendation:** Option (a) for Stage 1 — spec is archived, staging is ephemeral. At Stage 2, defer cleanup until code is promoted.

### 4. Build log: one event per line vs one summary per build
**Decision made in this document:** One event per line (append-only events).  
**Alternative considered and rejected:** One comprehensive summary per build (requires updating in place).  
**Rationale:** Append-only follows event_log.py pattern; allows status reconstruction from log alone.

### 5. Archives for rejected/abandoned builds
**Default (this document):** Yes — archives created for all terminal outcomes.  
**Alternative:** Only archive approved builds.  
**Recommendation:** Archive all terminal outcomes. The audit trail is most valuable for rejected builds — it shows what was considered and why it wasn't accepted.

### 6. `decision.json` vs `approval.json`
**Decision made in this document:** `decision.json` (covers approval AND rejection).  
**Alternative:** `approval.json` (rename rejection to `rejection.json`; two separate file names).  
**Recommendation:** Keep `decision.json` — one filename, `outcome` field disambiguates.

---

## Docs vs checked-in example JSON files

**Recommendation: docs only for now. Test fixtures when BUILD-002 tests are written.**

### Do not create
`data/frank_lloyd/` example files in the actual runtime directory — that path is for real data.
Any JSON placed there would appear as a real build record in `GET /frank-lloyd/status`.

### Create when BUILD-002 test file is written
```
tests/fixtures/frank_lloyd/
  BUILD-001_request.json     ← example request for a completed build
  build_log_sample.jsonl     ← 3–4 events covering a full lifecycle
  BUILD-001_decision.json    ← example approval record
  BUILD-001_manifest.json    ← example archive manifest
```

These fixtures support `test_builder_status.py` without polluting `data/frank_lloyd/`.
The test file patches the data directory to a temp path (same pattern as `test_event_query.py`
patching `el._LOG_PATH`).

### Schemas live in this document only
BUILD-002 is implemented against this doc's schema definitions. If an implementation
question arises, update this doc — do not invent new fields at implementation time
without updating the schema first.

---

## What Stage 2 adds (for reference only — not implemented at Stage 1)

The following fields and events are NOT valid at Stage 1. Listed here so the schemas
can be extended cleanly when Stage 2 design begins.

**New build log events at Stage 2:**
`build_started`, `staged`, `sentinel_requested`, `sentinel_passed`, `sentinel_failed`,
`code_approved`, `promoted`

**New archive contents at Stage 2:**
`sentinel_report.json` (Sentinel output), `build_manifest.json` (file list with hashes),
`integration_notes.md` (promotion steps)

**New decision.json fields at Stage 2:**
`code_approved` (bool), `sentinel_verdict` (string), `promoted_at` (ISO 8601)

**New status response fields at Stage 2:**
Pending builds may have `status: "building"`, `status: "sentinel_running"`, `status: "pending_code_review"`

No Stage 2 field should appear in a Stage 1 record. A log reader that encounters a
Stage 2 event name should treat it as an unknown event and skip it without crashing.
