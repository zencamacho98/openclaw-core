# Frank Lloyd — First Proof Task
*Status: REFERENCE BUILD COMPLETE — manually executed 2026-04-11.*  
*Last updated: 2026-04-11*

> **BUILD-001 has been implemented as a manual reference build.**
> `app/routes/event_query.py` (25 tests, all pass) was built by hand to validate
> the spec schema, staging design, and main.py approval boundary *before* Frank Lloyd
> infrastructure exists. It is the canonical reference example for what a
> bounded Frank Lloyd-style build looks like: new isolated file, one main.py include
> line, reuses existing platform capability (`read_recent_events`), full test
> coverage, zero side effects. Sentinel coverage is wired:
> `app/routes/event_query.py` → `tests/test_event_query.py` in `FILE_TEST_MAP`.

---

## What the proof task must demonstrate

The first task Frank Lloyd proves itself on must validate:
1. The spec schema is usable — Frank Lloyd can produce a spec that is complete, unambiguous, and reviewable
2. The staging model works — artifacts land correctly, Sentinel runs, operator can review
3. The approval workflow is correct — the main.py approval boundary is exercised
4. Frank Lloyd's outputs are genuinely useful — not a toy, not a stub
5. The blast radius if Frank Lloyd gets it wrong is near zero

---

## Candidate 1: Add Custodian health history logging

**What**: Add `/custodian/history` endpoint that returns the last N health check results. Each health check result is appended to a new `data/custodian_health_history.jsonl` file.

**Build type**: `modification`  
**Risk level**: `critical` — modifies existing files `app/routes/custodian.py` and `app/custodian.py`; any existing-file modification is critical  
**Files**: modify `app/routes/custodian.py`, modify `app/custodian.py`, create `data/custodian_health_history.jsonl`

**Pros:**
- Genuinely useful: currently no history of health checks exists, only the last result
- Reuses `observability/event_log.py` pattern directly (append-only JSONL)
- Small enough to be bounded

**Cons:**
- Modifying two existing files makes this a `modification` build — this is the highest-risk build type
- Frank Lloyd should prove itself on new file creation before it proves itself on existing file modification
- If Frank Lloyd makes a mistake in `custodian.py`, the health monitoring for the entire system breaks until fixed
- The approval path for existing file modification is the hardest path — not where to start

**Verdict:** Too risky as a first proof task. Modifying existing files is a later-stage capability. Start with new file creation.

---

## Candidate 2: Event log query endpoint — `GET /events`

**What**: New read-only FastAPI endpoint that exposes the event log with query filters: `?agent=`, `?severity=`, `?since=`, `?limit=`. New file `app/routes/event_query.py` + one-line addition to `app/main.py`.

**Build type**: `platform_capability`  
**Risk level**: `critical` — requires modifying `app/main.py` for route registration  
**Files**: create `app/routes/event_query.py`, modify `app/main.py` (one line)

**Pros:**
- Genuinely useful capability: there is currently no way to query the event log with filters via the API
- Primarily a new file creation — the only existing file modification is one include line in main.py
- Directly reuses `observability/event_log.read_recent_events()` — tests reuse workflow
- Immediately testable: `curl http://localhost:8001/events?limit=3`
- The main.py modification is the most important approval boundary in the system — testing it early is the right call
- Read-only endpoint with no side effects — if the code is wrong, it errors or returns wrong data; it doesn't corrupt anything
- Risk-appropriate: `app/routes/event_query.py` is a new isolated file; the main.py touch is one line; rollback is trivial (delete the new file, remove the one include line)
- Sets a clean pattern for future query endpoints (research log query, build log query)

**Cons:**
- The main.py modification makes the risk level `high` — some might argue this is too sensitive for a first proof
- Frank Lloyd must understand the existing router registration pattern to get main.py right
- If Frank Lloyd generates a route name collision (unlikely but possible), it could break startup

**Verdict:** Strong candidate. The cons are real but manageable: the main.py change is minimal and the operator reviews it explicitly before promotion. The genuine utility and the clean success criterion make this the best first task.

---

## Candidate 3: Frank Lloyd status stub — `GET /builder/status`

**What**: New file `app/routes/builder.py` exposing `GET /builder/status` that returns Frank Lloyd's current state: autonomy stage (0), build queue (empty list), platform capabilities available (list from CAPABILITY_REGISTRY), staging path, spec doc location.

**Build type**: `new_service`  
**Risk level**: `critical` — requires modifying `app/main.py` for route registration  
**Files**: create `app/routes/builder.py`, modify `app/main.py` (one line)

**Pros:**
- Elegant: Frank Lloyd's first act is creating its own minimal presence in the system
- The endpoint is immediately useful for Peter to query Frank Lloyd's state
- New file creation only (aside from main.py) — lowest blast radius
- If the output is wrong, it only affects what `/builder/status` returns — nothing else
- Sets the foundation for Frank Lloyd's future route file (which will eventually grow to include queue management, build history, etc.)

**Cons:**
- The status endpoint at Stage 0 is mostly static data: autonomy stage is 0, queue is empty, nothing is building. It's honest but thin.
- Does not exercise any reuse (no existing platform capability is needed to return a static dict)
- The success criterion ("returns valid JSON") is trivially easy to meet — doesn't stress-test Frank Lloyd
- Frank Lloyd creating its own route is slightly circular: Frank Lloyd is not yet built, so who produces the spec? The operator writes the spec and Frank Lloyd executes it — but at Stage 0, Frank Lloyd is not executing anything yet. This task is really just testing the workflow, not Frank Lloyd's intelligence.
- Does not validate that Frank Lloyd understands the existing codebase patterns (since it produces a nearly empty file)

**Verdict:** Elegant framing but too thin. The reuse workflow isn't tested. The success criterion is too easy. Save this for right after the first real proof task — it's a natural second step once Frank Lloyd has proven it can produce a useful capability.

---

## Final recommendation: Candidate 2 — Event log query endpoint

### Why this is the right first test

**It is genuinely useful.** No current event log query capability exists. After this build, the operator can query `GET /events?agent=belfort&limit=10` and see recent Belfort events. That is real value, not a toy. If Frank Lloyd gets this right, the operator has something they didn't have before.

**It exercises the critical approval path.** The `app/main.py` route registration boundary is the most important approval boundary in the system — it gates every new API capability. The proof task must include this path to validate that Frank Lloyd handles it correctly and that the approval workflow catches it. Deferring it would leave the most important safety check untested.

**The blast radius is near zero.** `app/routes/event_query.py` is a new isolated read-only file. If Frank Lloyd produces wrong code, the endpoint errors or returns incorrect data — no existing capability is affected. The one main.py change is one include line; rollback is deleting the new file and removing that line.

**The success criteria are specific and immediately verifiable.** The operator can run three curl commands and know whether Frank Lloyd got it right. There's no ambiguity in the verdict.

**It validates reuse discipline.** Frank Lloyd must use `read_recent_events()` from `observability/event_log` — not reimplement file reading. This tests whether Frank Lloyd correctly reads the CAPABILITY_REGISTRY and follows the reuse rules before generating code.

**It produces the schema example.** The example spec in `SPEC_SCHEMA.md` is already written for this exact task. Frank Lloyd's first real build can be validated against the design that specified it.

---

## Proof task summary

| Item | Value |
|---|---|
| Build ID | BUILD-001 |
| Title | Event log query endpoint |
| Build type | platform_capability |
| Risk level | critical (any main.py modification is critical) |
| New files | `app/routes/event_query.py` |
| Modified files | `app/main.py` (one include line) |
| Reuses | `observability/event_log.read_recent_events()` |
| Sentinel scope | smoke |
| Success check | `GET /events?limit=3` returns valid events JSON |
| Rollback | Delete new file, remove one include line |
| Validates | Schema usability, staging model, main.py approval boundary, reuse workflow |
| Autonomy stage | Stage 2 minimum (draft generator — produces code into staging) |

---

## What success here enables

If BUILD-001 completes successfully:
- The spec schema has been validated on a real build
- The staging directory structure has been exercised
- The main.py approval boundary has been tested end-to-end
- Frank Lloyd has a documented track record entry in build_log.jsonl
- The operator has a new useful API capability
- Frank Lloyd can attempt BUILD-002 with higher confidence

Recommended BUILD-002 after success: the Frank Lloyd status stub (Candidate 3). With the schema, staging, and approval workflow proven, the status endpoint is a low-effort next step that gives Frank Lloyd a live presence in the API.

---

## What failure here reveals

If BUILD-001 fails or produces a bad artifact:
- **Schema problem**: spec was ambiguous or missing required fields — fix schema before proceeding
- **Staging problem**: artifacts landed incorrectly or were not reviewable — fix staging model
- **Reuse problem**: Frank Lloyd reimplemented event_log.py instead of using it — add stricter reuse checks to the spec schema
- **main.py problem**: Frank Lloyd produced an incorrect include statement — tighten the integration steps section of the spec
- **Sentinel problem**: Sentinel returned unexpected verdict — check FILE_TEST_MAP coverage for new route files

None of these failure modes affect any existing capability. The only consequence of failure is that BUILD-001 is rejected and the spec/schema/workflow is improved before the next attempt.
