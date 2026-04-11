# Frank Lloyd — Stage 1 Execution Flow
*Status: DESIGN PASS — no implementation exists.*  
*Last updated: 2026-04-11*  
*Grounding example: BUILD-001 (event log query endpoint — manually executed 2026-04-11)*

---

## 1. What Stage 1 actually is

Stage 1 = **spec writer**. Frank Lloyd accepts intent and produces a structured spec document.
No code generation. No staging directory writes beyond the spec itself. No repo changes.

Stage 1 exists to prove one thing: Frank Lloyd can take a vague human request and turn it into
a spec that is precise, architecture-compliant, and reviewable — before anyone writes a
line of code. If Frank Lloyd can't do this reliably, Stage 2 (draft generator) is unsafe to attempt.

BUILD-001 was executed **manually** — by the operator, not by Frank Lloyd infrastructure. It is
the reference example for what a correct Stage 1 output looks like, not proof that Frank Lloyd
is already functional.

---

## 2. How Peter hands work to Frank Lloyd

Peter is Frank Lloyd's only upstream interface. Frank Lloyd never talks to the operator directly.

### Intake flow

```
Operator intent (Peter chat or command)
    │
    ▼
Peter: classify as build intent?
    │ yes
    ▼
Peter: is intent specific enough to spec?
    ├── no → ask operator clarifying questions (max 2 rounds)
    │         required: title, what you want, why, any constraints
    │
    └── yes
          │
          ▼
        Peter assembles BuildRequest packet
          │
          ▼
        Peter writes request to disk:
        data/frank_lloyd/requests/{build_id}_request.json
          │
          ▼
        Peter responds:
        "Queued BUILD-{N}: {title}. Spec production next."
```

**What Peter never does:**
- Write the spec (that's Frank Lloyd's job)
- Skip the pre-flight (no spec without it)
- Route to Frank Lloyd if the request touches another house's active domain without flagging it
- Route if the intent is too vague to spec (clarify first, max 2 rounds)

**What counts as "specific enough":**
A request is specific enough when Peter can fill in `title`, `description`, `build_type` hint,
`success_criteria`, and at least one constraint. If any of those is missing, Peter asks.

---

## 3. The Frank Lloyd request packet

Written to `data/frank_lloyd/requests/{build_id}_request.json` by Peter.

```json
{
  "request_id": "BUILD-002",
  "title": "Frank Lloyd status endpoint",
  "description": "Read-only GET /frank-lloyd/status endpoint that returns pending/active/completed builds from data/frank_lloyd/. Useful for Peter and the operator to see what Frank Lloyd has in flight.",
  "build_type_hint": "platform_capability",
  "requester": "operator",
  "requested_at": "2026-04-11T14:00:00+00:00",
  "context_refs": [
    "docs/frank_lloyd/STAGE1_FLOW.md",
    "docs/frank_lloyd/STAGING_MODEL.md"
  ],
  "constraints": [
    "Read-only — no writes",
    "Must read from data/frank_lloyd/requests/ and data/frank_lloyd/build_log.jsonl",
    "Do not invent state that isn't on disk"
  ],
  "success_criteria": "GET /frank-lloyd/status returns a list of builds with their current status. Empty list if no builds exist. No crash if files are missing.",
  "urgency": "normal"
}
```

**Required fields:** `request_id`, `title`, `description`, `requester`, `requested_at`, `success_criteria`  
**Optional:** `build_type_hint`, `context_refs`, `constraints`, `urgency`

The `build_type_hint` is Peter's best guess — Frank Lloyd may correct it in the spec.
The `request_id` is assigned by Peter using the next available BUILD-N from the build log.

---

## 4. What Frank Lloyd produces before any code is written

Frank Lloyd's Stage 1 output is a **build packet**: two artifacts written to staging.

```
staging/frank_lloyd/{build_id}/
├── spec.yaml          ← SPEC_SCHEMA format (YAML frontmatter + markdown body)
└── preflight.md       ← answers to the pre-flight checklist
```

### 4a. The spec (spec.yaml)

Full SPEC_SCHEMA format — see `docs/frank_lloyd/SPEC_SCHEMA.md` for field definitions.

The spec answers: what will be built, which files will be touched, what risk level,
what Sentinel scope, what success criteria, and what design assumptions.

**A spec is not complete until it answers:**
- What files are created (with paths)
- What files are modified (each one named explicitly)
- What is reused from existing platform capabilities
- What the Sentinel scope is (`smoke`, `targeted`, `full`)
- What the success criterion is (specific and testable, not "works correctly")
- What the risk level is, with rationale

### 4b. The pre-flight checklist (preflight.md)

Eight mandatory questions Frank Lloyd must answer before the spec is considered ready for review.

```markdown
# Pre-flight Checklist — BUILD-{N}: {title}

## 1. Capability reuse check
Does an existing capability in CAPABILITY_REGISTRY cover any part of this request?
[Yes/No + what was found or not found]

## 2. Existing house domain check
Does this belong inside an existing house's domain rather than as a new capability?
[Yes/No + rationale]

## 3. Minimum file set
What is the smallest set of files that satisfies the request?
[List of files and why each one is needed]

## 4. Off-limits file check
Does this request involve any permanently off-limits files?
(app/main.py, scripts/ctl.sh, app/loop.py, app/routes/neighborhood.py)
[Yes/No — if yes, name the file and the specific change required]

## 5. Architecture layer compliance
Where does this artifact sit in the 4-layer model?
Does it cross a layer boundary? If so, is that crossing justified?
[Layer placement + any boundary concerns]

## 6. Blast radius
What is the worst-case impact if this artifact contains a bug?
[Description of failure mode and scope]

## 7. Test coverage
What existing tests will cover this? What new tests are needed?
[Specific file → test file mapping]

## 8. Approval checkpoints
List every approval checkpoint this build will require.
[e.g., "spec approval", "main.py include line approval", "promotion approval"]
```

**Frank Lloyd may not omit any question.** If the answer is "not applicable", it must state why.

---

## 5. What the operator reviews and approves

The operator receives a **review packet** — the spec and preflight rendered for reading,
plus any flagged concerns Frank Lloyd surfaced.

### Review packet contents

1. **Spec summary** (key frontmatter fields: build_type, risk_level, new_files, modified_files, reuses, sentinel_scope, success_criteria)
2. **Design assumptions** (from the spec markdown body)
3. **Pre-flight answers** (full preflight.md)
4. **Flagged concerns** — Frank Lloyd must explicitly surface:
   - Off-limits files involved (named specifically)
   - Architecture layer concerns
   - Any criterion in the pre-flight that returned an unexpected answer
   - Any capability it couldn't find and chose not to reuse
5. **Approval decision form**

### What the operator decides

The approval decision is binary: **approve** or **reject with reason**.

Approving means:
- The scope is correct (not too wide, not too narrow)
- The file set is right
- The risk level assessment is accurate
- The success criterion is testable
- The reuse decisions are correct
- The test coverage plan is adequate

Approving does NOT mean:
- The code is correct (no code exists yet at Stage 1)
- Stage 2 is authorized (separate decision — see §6)

If the operator wants changes before approval: reject with a specific revision request.
Frank Lloyd revises the spec and re-presents. Max 3 revision cycles before the build is abandoned.

---

## 6. The approval record

On operator approval, Frank Lloyd writes two artifacts:

### approval.json → data/frank_lloyd/archives/{build_id}/

```json
{
  "build_id": "BUILD-002",
  "approved_at": "2026-04-11T14:30:00+00:00",
  "approved_by": "operator",
  "spec_hash": "sha256:abc123...",
  "approval_notes": "Scope is right. Must read from disk, not mock.",
  "deferred_items": [
    "Pagination — defer to after first build proves the data model"
  ],
  "stage2_authorized": false,
  "stage": 1,
  "outcome": "spec_approved"
}
```

`stage2_authorized: true` means the operator explicitly authorizes Frank Lloyd to proceed
to code generation in the same session. Default is `false` — Stage 2 is a separate decision.

### build_log.jsonl → data/frank_lloyd/build_log.jsonl (one appended line)

```json
{
  "build_id": "BUILD-002",
  "title": "Frank Lloyd status endpoint",
  "build_type": "platform_capability",
  "risk_level": "critical",
  "stage_completed": 1,
  "status": "spec_approved",
  "requested_at": "2026-04-11T14:00:00+00:00",
  "spec_produced_at": "2026-04-11T14:20:00+00:00",
  "approved_at": "2026-04-11T14:30:00+00:00",
  "operator_notes": "Scope is right.",
  "sentinel_scope": "targeted",
  "new_files": ["app/routes/builder_status.py"],
  "modified_files": ["app/main.py"]
}
```

### Archive contents at Stage 1 completion

```
data/frank_lloyd/archives/{build_id}/
├── request.json       ← copy of the original request packet
├── spec.yaml          ← copy of the approved spec
├── preflight.md       ← copy of the pre-flight answers
└── approval.json      ← approval record
```

Code artifacts are not in the archive at Stage 1 (none exist yet).

---

## 7. What changes when Frank Lloyd moves to Stage 2

Stage 2 = draft generator. Frank Lloyd produces code in addition to the spec.

### Additional Stage 2 artifacts (in staging)

```
staging/frank_lloyd/{build_id}/
├── spec.yaml            ← same as Stage 1 (already approved)
├── preflight.md         ← same as Stage 1
├── {new_file_1}.py      ← code artifacts (new files only at Stage 2)
├── build_manifest.json  ← what files exist, how they integrate
└── integration_notes.md ← step-by-step instructions for the operator
```

### Additional Stage 2 approval gates

Stage 1 had one gate: spec approval.
Stage 2 has two gates:

```
Gate 1: Spec approval (identical to Stage 1)
    │ approved
    ▼
Frank Lloyd generates code into staging
    │
    ▼
Sentinel runs automatically on staged files
    ├── not_ready → code sent back to Frank Lloyd (not to operator)
    │               Frank Lloyd revises → Sentinel re-runs
    │               Max 3 Sentinel cycles before escalation to operator
    │
    └── safe / review
          │
          ▼
Gate 2: Code + Sentinel approval
    Operator sees: code diff, Sentinel verdict, integration notes
    Decides: promote or reject
    │ promote
    ▼
Code copied from staging to live repo
Archive updated with code artifacts + Sentinel report
Build log updated: stage_completed=2, status=promoted
```

### What stays identical from Stage 1 → Stage 2

- Request packet format (unchanged)
- Spec format (unchanged — Stage 1 spec IS the Stage 2 input)
- Pre-flight checklist (unchanged)
- Archive format (extended, not replaced)
- Build log format (extended with Stage 2 fields)
- Approval record format (extended with code_approved and sentinel_verdict fields)

---

## 8. How Sentinel fits into the approval flow

### At Stage 1
Sentinel is **not triggered** — no code exists yet.

But the spec must include `sentinel_scope` and identify which test files will cover the
new code. This is Frank Lloyd's forward commitment: "when code exists, these tests will validate it."

BUILD-001 established the pattern: `app/routes/event_query.py` → `tests/test_event_query.py`
is now in FILE_TEST_MAP. A Stage 1 spec for a new route file should include:
```yaml
sentinel_scope: targeted
new_test_files:
  - tests/test_{module_name}.py
file_test_map_entries:
  - source: app/routes/{module_name}.py
    tests: [test_{module_name}.py]
```

### At Stage 2
Sentinel is **automatically triggered** after Frank Lloyd writes code to staging. The sequence:

1. Frank Lloyd completes staged code
2. Frank Lloyd calls Sentinel with the staged files as `files` param, `scope=auto`
3. Sentinel maps staged files → test files using FILE_TEST_MAP
4. Sentinel runs tests in `_TESTS_DIR` (live tests, not staged tests)
5. Verdict returned to Frank Lloyd before the operator sees anything
6. `not_ready` → Frank Lloyd revises, re-stages, re-runs Sentinel (up to 3 cycles)
7. `safe` or `review` → operator review proceeds

**Key point:** Sentinel runs against the LIVE test suite, not staged tests. Staged test files
must be in the archive but are not run by Sentinel until they are promoted to the live repo.
This means new test files written by Frank Lloyd must be included in the promotion alongside the
code — not after.

---

## 9. Full Stage 1 lifecycle: user request to approved build packet

```
TRIGGER: Operator asks Peter for something new

─────────────────────────────────────────────────────────
PHASE 1: INTAKE (Peter)
─────────────────────────────────────────────────────────

1. Operator expresses intent via Peter chat or command

2. Peter classifies: is this a build request?
   - If no: handle as normal Peter request
   - If yes: proceed

3. Peter checks completeness:
   - Has title, description, success criteria? → proceed
   - Missing fields? → ask (max 2 rounds of clarification)

4. Peter assigns BUILD-N ID (next in sequence from build_log)

5. Peter writes:
   data/frank_lloyd/requests/BUILD-N_request.json

6. Peter responds to operator:
   "Queued BUILD-N: {title}. Ready for spec production."

Status: pending_spec

─────────────────────────────────────────────────────────
PHASE 2: SPEC PRODUCTION (Frank Lloyd)
─────────────────────────────────────────────────────────

Frank Lloyd runs in a Claude Code session (Stage 1: operator-present, not autonomous)

7. Frank Lloyd reads request from data/frank_lloyd/requests/BUILD-N_request.json

8. Frank Lloyd runs pre-flight:
   a. Check CAPABILITY_REGISTRY for existing overlap
   b. Check BUILDER_SPEC §13 reuse list
   c. Identify minimum file set
   d. Check for off-limits files
   e. Map the 4-layer placement
   f. Assess blast radius
   g. Map test coverage
   h. List approval checkpoints

9. Frank Lloyd creates staging directory:
   staging/frank_lloyd/BUILD-N/

10. Frank Lloyd writes:
    staging/frank_lloyd/BUILD-N/preflight.md (eight checklist answers)
    staging/frank_lloyd/BUILD-N/spec.yaml    (SPEC_SCHEMA format)

11. Frank Lloyd signals readiness:
    "Spec ready for review: staging/frank_lloyd/BUILD-N/"

Status: pending_operator_review

─────────────────────────────────────────────────────────
PHASE 3: OPERATOR SPEC REVIEW
─────────────────────────────────────────────────────────

12. Operator reads spec.yaml and preflight.md

13. Operator may ask questions — Frank Lloyd answers from spec context only

14. Operator decides: approve or reject

If REJECTED:
  15a. Operator states revision request
  16a. Frank Lloyd revises spec and preflight (max 3 cycles)
  17a. Return to step 12
  18a. If 3rd rejection: build abandoned, status=abandoned, log entry written

If APPROVED:
  15b. Operator states approval notes (optional)

─────────────────────────────────────────────────────────
PHASE 4: APPROVAL RECORD
─────────────────────────────────────────────────────────

16. Frank Lloyd writes:
    data/frank_lloyd/archives/BUILD-N/request.json  (copy)
    data/frank_lloyd/archives/BUILD-N/spec.yaml     (copy)
    data/frank_lloyd/archives/BUILD-N/preflight.md  (copy)
    data/frank_lloyd/archives/BUILD-N/approval.json (new)

17. Frank Lloyd appends to:
    data/frank_lloyd/build_log.jsonl

18. Frank Lloyd confirms to operator:
    "BUILD-N spec approved. Archived. Stage 1 complete."
    "Next: [Stage 2 code generation | separate decision when ready]"

Status: spec_approved

─────────────────────────────────────────────────────────
STAGE 1 ENDS HERE
─────────────────────────────────────────────────────────

Stage 2 (code generation) is a separate decision, triggered separately.
The approved spec is the input. It does not expire or need re-approval
unless the scope changes.
```

---

## 10. What can stay manual vs what must be formalized

### Can stay manual at Stage 1

| Item | Why manual is acceptable |
|---|---|
| Request submission | Operator + Peter interaction can produce the request JSON in-session; no daemon needed |
| Spec production | Claude Code session produces spec.yaml and preflight.md; no autonomous execution needed |
| Staging directory creation | `mkdir staging/frank_lloyd/BUILD-N/` per build; trivial |
| BUILD-N ID assignment | Read last build_log entry or count request files; no registry needed |
| Preflight execution | Frank Lloyd runs checklist in-session; checklist is a structured prompt, not a separate service |

### Must be formalized before Stage 1 is "real"

| Item | Why it must be formalized |
|---|---|
| Request file format | Consistent JSON schema so Peter and Frank Lloyd read/write the same structure |
| Spec format | Already done — SPEC_SCHEMA.md is complete |
| Build log format | Must be consistent for status reads; one line dropped per build |
| Archive format | Must be consistent for audit trail; approval.json fields must be stable |
| Status visibility | Operator must be able to see what's in flight without reading raw JSON files |

The first three (request, log, archive format) are **data schemas** — they can be defined in a
short schema doc without writing a single route. The status visibility requires exactly one
read-only endpoint.

### Minimum API surface for Stage 1 to be real

**Required before first live Stage 1 build:**

```
GET  /frank-lloyd/status         — pending/active/completed builds from disk
GET  /frank-lloyd/{build_id}     — spec + preflight + current status for one build
POST /frank-lloyd/{build_id}/approve  — write approval.json + log entry
POST /frank-lloyd/{build_id}/reject   — write rejection record + log entry
```

**Not required yet:**

```
POST /frank-lloyd/request        — request submission (manual file write is fine at Stage 1)
GET  /frank-lloyd/{build_id}/diff    — code diff (no code at Stage 1)
POST /frank-lloyd/{build_id}/promote — promotion (Stage 2+)
```

The four required endpoints are the minimum for the approval flow to have a real paper trail
that isn't dependent on the operator remembering to write JSON files by hand.

---

## 11. BUILD-002 recommendation

**Build BUILD-002 after Stage 1 flow, not before.**

### Why

BUILD-002 as originally described is `GET /frank-lloyd/status` returning static data (autonomy
stage: 0, queue: empty, stage: 0). That stub would be immediately obsolete once Stage 1
infrastructure exists — the endpoint should read real data from `data/frank_lloyd/requests/`
and `data/frank_lloyd/build_log.jsonl`.

If BUILD-002 is built now, it will be rewritten when Stage 1 data model is implemented.
That is waste. The spec is incomplete without knowing what the status endpoint actually reads.

### Recommended sequence

```
Step 1: This design pass (done)

Step 2: Data model pass (no routes)
   Define and document:
   - Request file schema (JSON)
   - Build log line schema (JSONL)
   - Archive manifest (what files must be in each archive)
   - Status summary schema (what GET /frank-lloyd/status returns)
   This is a tiny docs/schema pass — creates no route files, no app/ code.
   Risk level: docs_only.

Step 3: BUILD-002 (status endpoint)
   Now the endpoint has a real spec:
   reads data/frank_lloyd/requests/*.json + data/frank_lloyd/build_log.jsonl
   returns live state, not mocked state
   This is a real BUILD-002, not a placeholder

Step 4: First live Stage 1 build
   BUILD-003 (or BUILD-002 itself) becomes the first build that goes through
   the Stage 1 lifecycle as defined in this document — complete with request
   packet, spec production, pre-flight, operator review, and approval record.
   This is the true proof of the Stage 1 flow.
```

BUILD-002 built against a real data model is also a more honest second reference build:
it exercises the full approval lane, including `data/frank_lloyd/` reads, which confirms that
the archive and log formats are correct before Stage 2 code generation is attempted.

---

*This document defines the Stage 1 flow only.*  
*Stage 2 (draft generator) design is a separate pass, preceded by demonstrated Stage 1 success.*  
*Do not implement Stage 2 mechanics before Stage 1 has completed at least one live build.*
