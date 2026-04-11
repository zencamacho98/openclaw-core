# Frank Lloyd — House Spec
*Status: DRAFT — Stage 1 infrastructure in progress.*  
*Last updated: 2026-04-11*

---

## 1. Mission

Frank Lloyd is the construction department of THE ABODE.

It accepts structured intent — from the operator via Peter — and produces the artifacts, specs, and integration plans needed to create, modify, duplicate, or evolve agents and houses inside the Abode. Its goal is to eliminate the external build loop: talk to ChatGPT → copy into Claude Code → manually build. Instead: talk to Peter → Peter routes to Frank Lloyd → Frank Lloyd handles construction → operator reviews and approves.

Frank Lloyd is a force multiplier. It does not generate revenue directly. Its value is that it makes the rest of the workforce cheaper and faster to build, maintain, and improve.

---

## 2. Why Frank Lloyd deserves to be a house

Against the five eligibility criteria:

| Criterion | Assessment |
|---|---|
| Durable specialized role | Yes. Construction and workforce evolution is a distinct domain. No other agent owns it. |
| Measurable outcomes | Yes. Build success rate, Sentinel pass rate on first attempt, operator approval rate, reduction in operator direct-coding time. |
| Operates with some autonomy | Conditional — see autonomy ladder. Early stages are fully supervised. Later stages are bounded. |
| Potentially force-multiplying | Yes. Every house Frank Lloyd can produce faster compounds the value of the entire workforce. |
| Owns a real workflow | Yes. Spec elaboration → draft generation → staging → review → promotion is a real end-to-end workflow. |

**Current eligibility: Conditional (planned).** Frank Lloyd earns its house fully when it can accept a spec, produce a staged artifact, and have that artifact pass Sentinel and architecture review without requiring the operator to write code themselves.

---

## 3. Workflows Frank Lloyd owns

1. **Intent elaboration** — Takes a high-level operator intent ("I want a house that monitors external APIs") and produces a structured spec: mission, workflows, inputs/outputs, eligibility assessment, approval boundaries, architecture layer placement. This is Frank Lloyd's entry-point workflow and the lowest-risk capability to build first.

2. **House eligibility assessment** — Given any candidate concept, runs it through the five eligibility criteria and returns an honest verdict: house / backstage service / not ready. Frank Lloyd defaults to skepticism — it should be harder to create a new house than to add to an existing one.

3. **Build execution** — Takes an approved spec and produces code artifacts in a staging area. Never writes directly to the live repo. Produces: new files, integration instructions, a build manifest listing what would change.

4. **Modification execution** — Takes a change request and a reference to existing code. Produces a diff in the staging area. Every modification to an existing file is a separate explicit request, not implicit.

5. **Duplication/cloning** — Takes a proven house as a source, a name/domain for the new instance, and a manifest of what changes. Produces a staged copy. *(Planned — deferred to after core build workflow is stable.)*

6. **Capability reuse audit** — Before any build, surveys CAPABILITY_REGISTRY and existing platform code for overlapping capabilities. Returns a reuse recommendation. This runs as a gate, not an option.

7. **Build log maintenance** — Append-only record of every build request, every artifact produced, every approval and rejection. This is Frank Lloyd's own audit trail.

---

## 4. What Frank Lloyd does NOT own

- **The operator conversation.** Peter owns the interface. Frank Lloyd never talks to the operator directly — it produces output that Peter surfaces.
- **Runtime management.** Custodian owns health and process management. Frank Lloyd does not touch `scripts/ctl.sh`, PID files, or process lifecycle.
- **Test execution.** Sentinel owns test running. Frank Lloyd requests Sentinel runs against staged artifacts; it does not run tests itself.
- **LM cost routing.** All LM calls go through CostWarden/LMHelper. Frank Lloyd does not have a private LM client.
- **Strategy and trading logic.** Belfort owns that domain. Frank Lloyd can create a new house with a trading capability if a spec calls for it, but it does not make strategy decisions.
- **Approval authority.** Frank Lloyd never approves its own output. Every artifact that could affect the live repo requires operator sign-off.
- **Deploying to production.** Frank Lloyd stages artifacts. The operator promotes them. Frank Lloyd has no promotion authority at any maturity stage.

---

## 5. Relationship to Peter

Peter is Frank Lloyd's only upstream interface.

Flow: Operator intent → Peter → structured build request → Frank Lloyd → staged artifact + summary → Peter → operator review.

Peter's responsibilities in this flow:
- Accept the operator's raw intent
- Ask clarifying questions if the intent is too vague to spec
- Route a well-formed build request to Frank Lloyd
- Surface Frank Lloyd's output (spec, diff, eligibility verdict) for operator review
- Surface Frank Lloyd's approval request for operator action

Peter must not collapse Frank Lloyd's workflow into himself. Peter asks and delegates; Frank Lloyd produces.

Frank Lloyd's output should never be applied silently. Peter always presents it as "Frank Lloyd produced X — review before proceeding."

---

## 6. Relationship to Belfort

Belfort is Frank Lloyd's primary reference architecture — not because they are similar in domain, but because Belfort's implementation represents the current best-practice house pattern:

- Route structure (`app/routes/belfort_*.py`)
- State persistence (`data/agent_state/`)
- Readiness scorecard pattern
- Learning/verdict pattern
- Diagnostics sub-report pattern
- Research trigger → campaign → candidate queue → operator approval flow

When Frank Lloyd creates a new specialist house, it should use Belfort's architecture as the template unless there is a documented reason to deviate.

Frank Lloyd must not modify Belfort's routes, state, or logic without an explicit per-request operator approval. Belfort's domain is Belfort's.

---

## 7. Relationship to backstage operating services

Frank Lloyd depends on several operating services and must not circumvent them:

| Service | Frank Lloyd's dependency |
|---|---|
| Cost Warden | All Frank Lloyd LM calls route through LMHelper. No private clients. |
| Test Sentinel | Frank Lloyd requests Sentinel runs on staged artifacts before presenting them for operator review. |
| Custodian | Frank Lloyd respects the runtime — it never manipulates processes, PID files, or port bindings. |
| Loop Supervisor | Frank Lloyd has no dependency. Campaign orchestration is Supervisor's domain. |
| Loop Checker | Frank Lloyd's build log is available to Checker for suspicious-pattern analysis. |

Operating services do not become houses by working with Frank Lloyd. If Frank Lloyd creates a new operating service as an artifact, that artifact is still assessed by the eligibility criteria — Frank Lloyd does not grant house status.

---

## 8. Inputs Frank Lloyd accepts

| Input | Format | Source | Notes |
|---|---|---|---|
| Build intent | Free-text | Operator via Peter | Stage 1 entry point — elaborated into a spec |
| Structured spec | Spec schema (see §15) | Operator or Frank Lloyd Stage 1 | Stage 2+ entry point |
| Reference architecture | Pointer to existing house/module | Operator | For modification or cloning |
| Constraint list | Structured | Operator | Architecture rules, off-limits files, style rules |
| Capability reuse directive | Pointer to CAPABILITY_REGISTRY entry | System | Pre-build gate |
| Approval signal | Operator confirmation | Operator via Peter | Required before staging → live |

---

## 9. Outputs Frank Lloyd produces

| Output | Format | Destination | Stage |
|---|---|---|---|
| House eligibility assessment | Markdown report | Staging area | 1+ |
| Structured spec | Markdown + JSON schema | Staging area | 1+ |
| Build manifest | File list + change type | Staging area | 2+ |
| Code artifacts | Python files, route files, data files | `staging/frank_lloyd/{build_id}/` | 2+ |
| Integration instructions | Markdown | Staging area | 2+ |
| Sentinel request | Trigger + file list | Sentinel | 2+ |
| Diff for review | Unified diff or file comparison | Peter → operator | 2+ |
| Build log entry | Append-only JSONL | `data/frank_lloyd/build_log.jsonl` | All stages |

---

## 10. Approval boundaries

### Always requires operator approval — no exceptions

- Any modification to an existing file (new files only for bounded autonomy; modifications always require approval)
- Any change to `app/main.py` (route registration, lifespan hooks)
- Any change to `app/routes/neighborhood.py`
- Any change to `scripts/ctl.sh` or any control infrastructure
- Any deletion of a file, route, or capability
- Any new house being added to the neighborhood (visual presence grant)
- Any change that affects another house's existing routes or data
- Any change to data persistence schemas in live data files
- Any promotion of staged artifacts to the live repo

### Could eventually be safe for bounded autonomous execution

These are candidates for future autonomy expansion, subject to demonstrated safety at the previous stage:

- Generating an eligibility assessment (Stage 1, low risk)
- Generating a spec document (Stage 1, low risk)
- Creating a new file in a defined pattern location with no live-repo writes (Stage 2)
- Requesting a Sentinel run on staged artifacts (Stage 2)
- Producing a build plan for operator pre-approval (Stage 2)
- Adding a new data field to a house's own state file, additive only, no schema breaks (Stage 3, conditional)

---

## 11. Autonomy ladder

Frank Lloyd follows the same earned-autonomy doctrine as every other house. No stage is granted by declaration — each requires demonstrated safety at the prior stage.

### Stage 0 — Concept (current)
Defined in docs. No code exists. Frank Lloyd has no autonomous capability.

### Stage 1 — Spec writer
Frank Lloyd can accept a high-level intent via Peter and produce:
- A house eligibility assessment
- A structured spec document
Output lands in `staging/frank_lloyd/{build_id}/`. No code generation. No repo writes.
Operator reviews spec and approves or rejects before any further work.

**Autonomy**: Full supervision. Frank Lloyd produces text artifacts only.

### Stage 2 — Draft generator
Frank Lloyd can generate code drafts from an approved Stage 1 spec.
Output lands in staging area only. Never in the live repo.
Frank Lloyd automatically requests a Sentinel run on staged files.
Produces: diff, build manifest, integration instructions.
Operator reviews diff + Sentinel verdict before any promotion.

**Autonomy**: Supervised generation. Frank Lloyd writes to staging only.

### Stage 3 — Supervised builder
For pattern-matched builds (new backstage service from a defined template, new route file from a defined template), Frank Lloyd can:
- Produce a build plan (what files will be created/modified, what the integration steps are)
- After operator approves the build plan, execute the build into staging
- Auto-run Sentinel
- Present the result for final promotion approval

Operator approves twice: once for the plan, once for promotion.
Still no direct writes to the live repo.

**Autonomy**: Pre-approved plan execution. Two approval gates.

### Stage 4 — Trusted builder (long-term)
For well-defined pattern-matched builds where Stage 3 has demonstrated consistent Sentinel passes and architecture compliance, Frank Lloyd can execute end-to-end with the operator reviewing only the final diff + Sentinel verdict.

Still cannot: modify runtime infrastructure, modify existing houses without explicit per-request approval, or promote without operator confirmation.

**Autonomy**: Bounded autonomous execution within defined patterns. Final human gate always applies.

---

## 12. Safety and integrity rules

1. **Staging-first always.** Frank Lloyd never writes to the live repo at Stages 1–3. Stage 4 still requires operator promotion approval.
2. **No self-modification.** Frank Lloyd cannot modify its own code, routes, data schemas, or build log format.
3. **No runtime infrastructure writes.** `app/main.py`, `scripts/ctl.sh`, `app/loop.py`, `.env`, and all PID/log infrastructure are permanently off-limits without explicit operator instruction that names the specific change.
4. **No modification of existing houses without per-request approval.** General permission does not exist. Every modification to Belfort, Peter, or any other existing house requires a fresh explicit approval identifying the specific files and changes.
5. **Architecture integrity check on every build.** Every artifact Frank Lloyd produces must be checked against the 4-layer model before it is presented for review. If the artifact violates layer discipline, Frank Lloyd must flag it, not produce it silently.
6. **Mandatory eligibility gate before new house creation.** Before building any new house, Frank Lloyd must run and surface the eligibility assessment. The operator must see the result. If any criterion is questionable, Frank Lloyd must name it explicitly.
7. **Blast radius minimum.** Frank Lloyd should prefer: adding to an existing house over creating a new house; a backstage service over a house when eligibility is unclear; the smallest set of file changes that satisfies the request.
8. **Sentinel required.** No staged artifact is presented to the operator for promotion approval without a Sentinel run.
9. **Append-only build log.** Every build request, every artifact, every approval, every rejection is logged in `data/frank_lloyd/build_log.jsonl`. The log is never truncated or modified.
10. **No circular dependency.** Frank Lloyd cannot modify the capabilities it depends on (CostWarden, Sentinel, agent_state, observability) without an explicit operator-directed maintenance window.

---

## 13. Reuse rules

Before starting any build, Frank Lloyd must run a capability reuse audit:

1. Check CAPABILITY_REGISTRY for existing capabilities that overlap with the request.
2. Check whether the request adds to an existing house's domain rather than requiring a new one.
3. Identify which platform capabilities apply: LMHelper, agent_state, event_log, telemetry, readiness scorecard pattern, campaign orchestration.
4. Flag any request that would duplicate existing live functionality.

**Platform capabilities Frank Lloyd must reuse (never rebuild):**

| Capability | Module |
|---|---|
| LM calls | `app/cost_warden.LMHelper` |
| Agent state persistence | `observability/agent_state.py` |
| Event/audit logging | `observability/event_log.py` |
| Telemetry pattern | `observability/telemetry.py` |
| Approval flow patterns | `research/approval_policy.py` |
| Governance patterns | `research/governance.py` |
| Manifest patterns | `research/manifest.py` |

**New platform capabilities Frank Lloyd is likely to force us to invent:**

| Capability | Why it doesn't exist yet |
|---|---|
| Spec schema | No structured format for describing a house or capability exists yet |
| Staging area | No `staging/` directory or promotion workflow exists yet |
| Template library | No curated house/service templates exist yet |
| Build manifest format | Similar to `research/manifest.py` but at the repo/architecture level |
| Diff review protocol | No structured operator review flow for proposed file changes |
| Promotion workflow | Moving artifacts from staging to live with gated approval |

These should be designed and built as platform capabilities when Frank Lloyd reaches Stage 2 — not before.

---

## 14. What counts as success

**Stage 1 success**: Frank Lloyd produces a structurally correct, architecture-compliant spec from a high-level intent request. The operator says "this is what I meant" without needing to rewrite it.

**Stage 2 success**: Frank Lloyd-produced code artifacts pass Sentinel validation on first or second attempt (no extended thrash). Operator review time per build is less than the time the operator would have spent writing the code manually.

**Stage 3 success**: Frank Lloyd can handle a defined class of builds (e.g., new backstage service from template) with operator reviewing only the plan + final result, not each individual file.

**Ongoing success metrics:**
- Operator direct-coding work on The Abode decreases over time
- Sentinel first-pass rate for Frank Lloyd artifacts improves over time
- Fraction of requests where Frank Lloyd correctly recommends backstage service vs house is high
- No incident where Frank Lloyd's output caused regression to existing houses without operator awareness

---

## 15. Milestones

### Concept (current)
Defined in docs. No code. Frank Lloyd appears in ROLE_MAP, HOUSE_ELIGIBILITY, CAPABILITY_REGISTRY (planned).

### Defined house
- Spec finalized (this document)
- Peter knows how to package and route a build intent
- Staging area structure defined (`staging/builder/`)
- Spec schema defined (JSON/markdown format for a house spec)
- Template for at least one house type defined (Belfort-like specialist house)

### Usable house (Stage 1–2)
- Peter can route a build intent to Frank Lloyd
- Frank Lloyd produces a spec document and eligibility assessment for operator review
- Frank Lloyd generates code drafts from approved specs into staging
- Sentinel runs automatically on staged artifacts
- Operator can review and promote a staged artifact without writing code

At this milestone: evaluate whether Frank Lloyd's spec-writing and code-generation workflows have diverged enough to warrant a house split. If they feel like one pipeline, stay as one house. The decision is made at this milestone with evidence — not before.

### Trusted house (Stage 3–4)
- Frank Lloyd handles pattern-matched builds end-to-end with two approval gates
- Build log shows a track record of Sentinel passes and architecture compliance
- Operator's direct-coding work on The Abode is materially reduced
- Frank Lloyd's eligibility assessments are accurate: backstage services aren't being promoted to houses

---

## Appendix: Design question answers

**Is Frank Lloyd one house or two?**
Start as one. Incubation is a workflow mode within Frank Lloyd, not a separate domain. The split becomes worth considering only at the "Usable House" milestone, if the spec-only pipeline and the code-generation pipeline develop incompatible autonomy profiles or a plausible standalone identity for one of them. Until then, one house.

**Should duplication/cloning be part of Frank Lloyd?**
Yes, in scope, deferred in implementation. Cloning belongs to Frank Lloyd's domain but is the highest-risk operation (canonical ambiguity, name collisions, route conflicts). Design the interface now; build it after the core build workflow is stable.

**What types of changes should always require human approval?**
Any modification to existing files. Any change to runtime infrastructure. Any new house visual presence. Any deletion. Any data schema change in live files. Any promotion of staged artifacts to the live repo. See §10 for full list.

**What types of changes could eventually be safe for bounded autonomous execution?**
New file creation following an established template pattern. Spec generation. Eligibility assessment. Sentinel-triggered staging validation. See §10 and §11 Stage 4.

**How should Frank Lloyd avoid creating neighborhood bloat?**
Default skepticism: prefer adding to an existing house over creating a new one. Mandatory eligibility gate before any new house. Explicit operator confirmation for visual presence grants. Build log makes all creations auditable. No house is created silently.

**How should Frank Lloyd decide house vs backstage service?**
Run the five eligibility criteria from `HOUSE_ELIGIBILITY.md`. Default to backstage service if any criterion is unclear. Present the assessment to the operator. Frank Lloyd should explain the criteria result, not just give a verdict.

**What existing platform capabilities should Frank Lloyd reuse first?**
`LMHelper`, `agent_state.py`, `event_log.py`, `approval_policy.py`, `governance.py`, `manifest.py`. See §13.

**What new reusable platform capabilities might Frank Lloyd force us to invent?**
Spec schema, staging area, template library, build manifest format, diff review protocol, promotion workflow. These become platform capabilities, not Frank Lloyd-specific code. See §13.
