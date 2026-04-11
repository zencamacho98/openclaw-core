# Frank Lloyd — Stage 1 Peter Handoff Spec
*Status: DESIGN PASS — no implementation exists.*  
*Last updated: 2026-04-11*  
*Scope: Stage 1 only. No codegen. No autonomous execution.*

---

## Purpose

This document defines the first real Peter → Frank Lloyd handoff loop. It is not about
infrastructure or autonomy — it is about the minimum protocol that makes Stage 1 useful
rather than theatrical.

The goal: when a user asks Peter to build something, Peter and Frank Lloyd jointly produce
a spec that is honest, bounded, architecture-compliant, and ready for operator approval.
No code is written. No staging directory is required at Stage 1 unless the operator approves.

---

## 1. What Peter must hand to Frank Lloyd

Peter's job is to turn raw operator intent into a request packet Frank Lloyd can work from.
Peter does not interpret the intent or propose solutions — that is Frank Lloyd's job.

### The handoff is ready when Peter can answer all six:

| Field | Question Peter must answer | Where it comes from |
|---|---|---|
| `title` | What short name describes this? | Operator, paraphrased by Peter if needed |
| `description` | What does the operator want and why? | Operator, verbatim or lightly cleaned |
| `success_criteria` | What does "done" look like, specifically? | Elicited from operator (Peter asks if missing) |
| `constraints` | Are there explicit limits? ("read-only", "no new files", etc.) | Elicited from operator |
| `context_refs` | Are there relevant docs or files the operator referenced? | Peter extracts from conversation |
| `build_type_hint` | What kind of build is this most likely? | Peter's best guess from SPEC_SCHEMA build types |

Peter assigns a `request_id` (next BUILD-N from the log) and writes the request file.

### What makes a request "clear enough" to hand off

A request is ready when:
- The operator's intent is unambiguous — Peter can state back what will be built and the operator confirms
- A success criterion exists that is specific and falsifiable (not "works correctly")
- No directly conflicting constraints exist (e.g., "add the feature" + "do not touch that file" with no resolution)

A request is **not** ready when:
- The scope is undefined ("make it better", "add more features")
- The success criterion is missing or purely subjective
- The request touches another agent's domain without the operator explicitly acknowledging it

Peter's clarification limit: **2 rounds maximum**. If the request is still unclear after 2 rounds,
Peter tells the operator it is too ambiguous to proceed and asks them to try again with more specifics.
Peter does not keep asking indefinitely.

---

## 2. What Frank Lloyd must produce before implementation begins

Frank Lloyd's Stage 1 output is a **build packet**: two text artifacts.

```
staging/frank_lloyd/{build_id}/
├── spec.yaml       ← structured spec (SPEC_SCHEMA format)
└── preflight.md    ← eight-question pre-flight checklist
```

Neither artifact contains code. No code is generated at Stage 1.

### The spec (spec.yaml)

Per SPEC_SCHEMA.md. Frank Lloyd must fill in all required fields for the build type.

A spec is **not complete** unless it explicitly states:
- Every new file that would be created (with full path)
- Every existing file that would be modified (each named individually)
- What platform capability it reuses (or why reuse was considered and rejected)
- What the Sentinel scope would be when code eventually exists
- A specific, testable success criterion

Vague answers ("various files may be affected") are not acceptable. If Frank Lloyd cannot name the
files, the build is not well-defined enough to spec.

### The pre-flight checklist (preflight.md)

Eight questions that Frank Lloyd must answer before the spec is considered ready for review.
These are not optional. If any answer is "I don't know", that is an uncertainty that must be
escalated — not omitted.

```
1. Capability reuse check
   Does anything in CAPABILITY_REGISTRY already cover part of this request?
   Did you check docs/frank_lloyd/ for existing data structures this would use?

2. Existing house domain check
   Does this request belong inside an existing house's domain?
   Could it be an extension of Belfort, Peter, or an operating service rather than new construction?

3. Minimum file set
   What is the smallest set of files that satisfies the success criterion?
   Is every proposed file necessary, or is any speculative?

4. Off-limits file check
   Does this request require touching any of these files?
   (app/main.py, scripts/ctl.sh, app/loop.py, app/routes/neighborhood.py)
   If yes: name the file, describe the specific change required, and flag it explicitly.

5. Architecture layer compliance
   Where does this artifact sit in the 4-layer model?
   Does it cross a layer boundary? If so, why is that crossing justified?

6. Blast radius assessment
   What breaks if this artifact contains a bug?
   Is the failure mode silent (data corruption) or loud (startup crash)?
   Can rollback happen by deleting one file?

7. Test coverage plan
   What existing tests cover related behavior?
   What new tests would be needed? Name the test file(s) specifically.
   Map: source file → test file.

8. Approval checkpoint list
   List every human approval gate this build will require, in order.
   (Example: spec approval → main.py change approval → promotion approval)
```

---

## 3. What Peter reports back to the user

After Frank Lloyd produces a build packet, Peter surfaces it for the operator.

Peter's report has three parts:

### 3a. Build summary (always shown)
```
Frank Lloyd has produced a spec for BUILD-{N}: {title}

Risk level: {risk_level}
Files proposed:
  New: {list}
  Modified: {list}
Sentinel scope: {scope}
Success criterion: {criterion}
```

### 3b. Flagged concerns (shown if any exist)
```
Flagged concerns:
  - {concern 1}
  - {concern 2}
```
Concerns include: off-limits files involved, architecture layer violations, missing reuse
justification, anything Frank Lloyd marked as uncertain. Peter does not filter these out.
If Frank Lloyd raised a concern, Peter surfaces it.

### 3c. Decision prompt
```
Review: staging/frank_lloyd/BUILD-{N}/

Approve spec? [yes / no / revise: {notes}]
```

Peter does not paraphrase or editorialize the spec content. The operator reads the spec directly.
Peter's job is to surface it cleanly and present the decision.

---

## 4. What gets stored on disk

At Stage 1, these files are written:

| File | When | Who |
|---|---|---|
| `data/frank_lloyd/requests/BUILD-N_request.json` | When Peter queues the request | Peter |
| `data/frank_lloyd/build_log.jsonl` (request_queued line) | Immediately after request file | Peter |
| `staging/frank_lloyd/BUILD-N/spec.yaml` | When Frank Lloyd completes spec production | Frank Lloyd |
| `staging/frank_lloyd/BUILD-N/preflight.md` | Same time as spec | Frank Lloyd |
| `data/frank_lloyd/build_log.jsonl` (spec_ready line) | When staging artifacts are ready | Frank Lloyd |
| `data/frank_lloyd/archives/BUILD-N/` (4 files) | On operator approval or rejection | Frank Lloyd |
| `data/frank_lloyd/build_log.jsonl` (terminal line) | On spec_approved / spec_rejected / abandoned | Frank Lloyd |

The operator always sees a build before anything is archived. Archiving happens after the decision.

---

## 5. What approval checkpoint the user sees

Stage 1 has exactly one approval checkpoint. The user sees it after Frank Lloyd completes the
spec and preflight, and before any code work begins.

**The checkpoint is: "Does this spec correctly describe what you want?"**

Specifically the operator answers:
- Is the scope right? (could it be narrower without losing the value?)
- Are the proposed files correct?
- Is the risk level assessment accurate?
- Is the success criterion specific enough to verify?
- Are the reuse decisions correct (or should Frank Lloyd have used something existing instead)?

Approving means: "This spec correctly describes what I want. Produce it."
The approval does **not** mean the code is correct — no code exists yet.
The approval does **not** authorize Stage 2 code generation unless explicitly stated.

A rejection triggers a revision cycle. Max 3 revision cycles before the build is abandoned.
Each revision cycle produces a new spec — the operator reviews the new spec again.

---

## 6. What makes a request "clear enough" to hand off

_(Also addressed in §1 — this section gives Frank Lloyd's perspective, not Peter's.)_

From Frank Lloyd's perspective, a request is workable when:
1. It maps to at most one build type in SPEC_SCHEMA (if it spans two types, it needs to be split)
2. The success criterion can be verified with a specific test or curl command
3. Every file in the proposed change set can be named before writing any code
4. The blast radius if the output is wrong is bounded (not "could break everything")

A request fails these gates when:
- It says "improve performance" with no measurable definition
- It involves modifying more than 3 existing files (beyond main.py integration) — strong signal the scope is too wide
- The operator hasn't confirmed the file set and Frank Lloyd has to guess
- The request includes both new functionality and refactoring of existing code (these are separate builds)

When a request fails these gates, Frank Lloyd does not proceed to a spec. It reports the
specific gate that failed and what information is needed to unblock it.

---

## 7. What Frank Lloyd must check for reuse before proposing changes

Before proposing any new file or change, Frank Lloyd runs a reuse check against three sources:

### Check 1: CAPABILITY_REGISTRY
Read `docs/CAPABILITY_REGISTRY.md` Section C (Reusable Platform Capabilities).
If an existing capability covers the request, use it. Do not rebuild it.

The mandatory reuse list (never rebuild these):
- LM calls → `app/cost_warden.LMHelper`
- Agent state → `observability/agent_state.py`
- Event/audit logging → `observability/event_log.py`
- Telemetry → `observability/telemetry.py`
- Approval flow → `research/approval_policy.py`
- Governance → `research/governance.py`

### Check 2: Existing house domain
If the request is about trading, research, or readiness → it belongs to Belfort. Frank Lloyd does
not build things that should go in an existing house. Peter should have caught this, but Frank
Lloyd runs the check independently.

### Check 3: Existing route patterns
If the request involves a new FastAPI route, scan `app/routes/` for existing patterns:
- Read `app/routes/event_query.py` as the reference for a minimal read-only query endpoint
- Read `app/routes/frank_lloyd_status.py` as the reference for a minimal status endpoint
- Do not invent new patterns when an existing one fits

If a reuse check reveals the request partially duplicates something that exists, Frank Lloyd names
the overlap in the pre-flight (question 1) and in the flagged concerns. The operator decides
whether to proceed or narrow the scope.

---

## 8. How Frank Lloyd reports uncertainty or blocked status back through Peter

Frank Lloyd is blocked or uncertain when it cannot complete a pre-flight question with a
specific answer. This must be surfaced — not worked around.

### Uncertainty states

| State | What it means | What Frank Lloyd reports |
|---|---|---|
| `uncertain_scope` | The request is underspecified — Frank Lloyd cannot name all files | "Cannot complete spec: file set is unknown without more detail on X" |
| `uncertain_reuse` | CAPABILITY_REGISTRY or existing code may cover this, but the overlap is ambiguous | "Possible reuse conflict with {capability}. Needs operator clarification before proceeding." |
| `off_limits_required` | The build requires touching an off-limits file | "This build requires modifying {file}, which is permanently off-limits without explicit operator instruction. Operator must explicitly name this change before Frank Lloyd will include it." |
| `layer_violation` | The proposed artifact crosses an architecture layer boundary without clear justification | "Proposed change violates 4-layer boundary: {explanation}. Frank Lloyd will not proceed until this is resolved." |
| `scope_too_wide` | More than 3 existing files involved, or build spans multiple build types | "Scope exceeds safe Stage 1 bounds. Recommend splitting into: {suggested split}." |

### How uncertainty is surfaced through Peter

Frank Lloyd writes a `blocked.md` file in staging instead of a spec:

```
staging/frank_lloyd/BUILD-N/blocked.md
```

Contents:
```markdown
# Frank Lloyd — BUILD-N Blocked

**Blocked state**: {state}
**Reason**: {specific reason}
**What is needed to unblock**: {exactly what information or decision is required}
**Recommended operator action**: {accept scope change | provide clarification | override}
```

Peter reads this file and surfaces it to the operator as:
```
Frank Lloyd cannot proceed with BUILD-N: {reason}

To unblock: {what is needed}
```

The build log records a `blocked` event (not a terminal event — the build can continue
once unblocked). The build stays in `pending_spec` status from the status endpoint's perspective.

---

## What is explicitly out of scope for this handoff spec

- Autonomous spec generation from natural language (Peter + Frank Lloyd work together in session)
- Code generation (Stage 2+, not defined here)
- Automated approval recording (manual at Stage 1 — `POST /frank-lloyd/{id}/approve` is a future step)
- Neighborhood UI for Frank Lloyd (not until Frank Lloyd has a track record to display)
- Peter learning from Frank Lloyd's outputs to improve future handoffs (future milestone)

---

## What Stage 1 success looks like for this handoff

The handoff is working when:
1. The operator asks Peter for something → Peter produces a complete request packet without requiring a third clarification round
2. Frank Lloyd produces a spec + preflight → the operator reads it and says "this is what I meant" without rewriting it
3. The pre-flight checklist catches at least one non-obvious reuse opportunity or constraint before the operator sees the spec
4. The approval checkpoint is clean: the operator approves or provides a specific revision request (not a vague "this doesn't feel right")
5. The build log accurately reflects every stage of the lifecycle

Success is not: "Frank Lloyd produced code." Success is: "The spec was right before anyone wrote code."
