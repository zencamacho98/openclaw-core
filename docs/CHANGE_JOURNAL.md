# Change Journal — The Abode
*Append-only. Each entry records what changed, why, and where. Add new entries at the bottom.*

---

## Format

```
## [DATE] [BLOCK TITLE]
**Commit**: short SHA or "unreleased"
**What changed**: short description
**Why**: motivation or trigger
**Files**: changed files
**Reuses**: existing flows reused
**Left out**: what was explicitly not done
```

---

## 2026-04-09 Initial OpenClaw system with validation harness
**Commit**: `5765424`  
**What changed**: Full initial system. FastAPI backend on port 8001. Portfolio tracker. Strategy core (mean-reversion + MA crossover). Mock trade task. Pattern aggregator. Proposal parser. Regime trade task. Loop control (start/stop). Agent state manager. Monitor route with Peter chat, status, logs. Strategy changelog and applier.  
**Why**: First commit — bootstrapping the entire system from scratch.  
**Files**: `app/` (all core modules), `app/routes/monitor.py`, `app/strategy/`, `data/portfolio.json`, `CLAUDE.md`  
**Reuses**: n/a (initial)  
**Left out**: Research loop, Neighborhood, Supervisor, Custodian, Warden

---

## 2026-04-09 Sweep, services, and UI cleanup
**Commit**: `18713a5`  
**What changed**: Parameter sweep validation runs (9 sweep configs). Strategy config improvements. Applier and mean_reversion updates. Portfolio state expanded. Candidate config and tuning log.  
**Why**: First pass at automated parameter optimization — identify better config via sweep.  
**Files**: `app/experiment.py`, `app/strategy/applier.py`, `app/strategy/config.py`, `app/strategy/mean_reversion.py`, `data/candidate_config.json`, `data/portfolio.json`, `data/strategy_config.json`, `data/tuning_log.jsonl`, `data/validation_runs/`  
**Reuses**: Existing strategy core, portfolio tracker  
**Left out**: Candidate queue, campaign orchestration, operator review flow

---

## 2026-04-10 ER filter and cooldown accepted; research and trade review added
**Commit**: `14861cd` / `24533bb`  
**What changed**: Kaufman Efficiency Ratio (ER) filter added to strategy. Trade cooldown added. Research cycle and trade review improvements. MR strategy improvement accepted from candidate.  
**Why**: Sweep identified ER-filtered config as better; promoted to active strategy.  
**Files**: `app/strategy/mean_reversion.py`, `app/strategy/config.py`, `data/strategy_config.json`  
**Reuses**: Strategy applier, portfolio core  
**Left out**: Supervisor daemon, readiness scorecard

---

## 2026-04-10 [11am session] Belfort Readiness Bundle + Neighborhood overhaul
**Commit**: `f2168f1`  
**What changed**:  
- 8-gate readiness scorecard (`/belfort/readiness`)  
- Baseline reset endpoint (`/belfort/readiness/reset`)  
- Baseline adoption record on disk (`data/baseline_adoption_record.json`)  
- Neighborhood HTML revamped with Belfort house, readiness panel, pixel-art community layout  
- Monitor route expanded (Peter v2 commands)  
- Supervisor state and daemon plumbing  
- CLAUDE.md overhauled with full project context and skills wiring  
**Why**: Operator needed visibility into whether Belfort's strategy was healthy vs baseline. Neighborhood needed to become the primary user surface.  
**Files**: `app/routes/belfort_readiness.py` (new), `app/routes/neighborhood.py` (major rewrite), `app/routes/monitor.py`, `app/routes/supervisor.py`, `app/supervisor.py`, `data/baseline_adoption_record.json`, `data/agent_state/mr_belfort.json`, `CLAUDE.md`  
**Reuses**: Portfolio `get_snapshot()` and `get_trades()`, strategy `get_config()`, supervisor state  
**Left out**: Learning verdict, diagnostics, soft triggers, skills files

---

## 2026-04-10 [evening session] Learning verdict, diagnostics, adaptive triggers, neighborhood stability
**Commit**: `d95171753` (learning test)  
**What changed**:  

**A. Skills wiring**  
- `skills/abode-neighborhood-pass/SKILL.md`, `skills/abode-role-boundary-check/SKILL.md`, `skills/abode-delivery-report/SKILL.md` added  
- `CLAUDE.md` wired `@` imports so skills auto-load in every session  

**B. Neighborhood declutter + stability**  
- Readiness section collapsed into `<details>` — only badge, gate count, research trigger, blockers visible at top level  
- Removed cycle count from Peter's panel (was internal jargon)  
- Removed duplicate trades/P&L from Belfort SITUATION (already shown in TRADING STATS grid)  
- Fixed stutter: `populatePanel(_skipClear=true)` on poll refresh skips "Loading…" flash  
- 55-second cooldown guards on readiness and learning async loads  
- Cooldowns reset on `closePanel()` so re-opening always fetches fresh  

**C. Belfort diagnostics panel**  
- New endpoint `GET /belfort/diagnostics` (new file `app/routes/belfort_diagnostics.py`)  
- Three sub-reports: strategy drift (key param comparison vs baseline), session P&L path (expectancy, peak, drawdown), trigger detail (active signals, gaps to thresholds, research bridge)  
- Registered in `app/main.py`  
- Neighborhood Belfort panel renders diagnostics section with collapsible "Hard threshold gaps" detail  

**D. Adaptive trigger tuning**  
- New soft trigger layer in `app/routes/belfort_readiness.py`: 3 conditions (negative expectancy after 5 trades, PF < 1.0, drawdown from peak > $1k)  
- `_research_triggers()` now returns `pressure: none/soft/hard`, `soft_triggered`, `soft_reasons`, `soft_count`  
- `app/routes/belfort_learning.py` verdict logic updated: `n_soft >= 2` → "tune", `n_soft == 1` → "monitor" (fires before "continue")  
- With live data (-$2.04/trade expectancy, PF 0.94, -$1,641 drawdown from peak): verdict correctly = "tune"  

**Files added**: `app/routes/belfort_diagnostics.py`, `app/routes/belfort_learning.py`, `app/routes/belfort_memory.py`, `skills/abode-*/SKILL.md`  
**Files edited**: `app/main.py`, `app/routes/belfort_readiness.py`, `app/routes/neighborhood.py`, `CLAUDE.md`  
**Reuses**: Readiness helpers imported by diagnostics and learning. Portfolio `get_snapshot()` / `get_trades()` throughout. Candidate queue read for research bridge.  
**Left out**: No Discord, no new houses, no LM in diagnostics

---

## 2026-04-10 Documentation foundation
**Commit**: unreleased  
**What changed**: Four documentation files created under `docs/`:  
- `docs/BRD.md` — Business requirements: product vision, user framing, surfaces, workflows, success criteria  
- `docs/TRD.md` — Technical requirements: architecture, services, runtime, LM policy, role boundaries, data persistence, design constraints  
- `docs/CAPABILITY_REGISTRY.md` — Capability inventory: all 18 live capabilities with status, owner, business purpose, technical description, code location, reuse potential  
- `docs/CHANGE_JOURNAL.md` — This file: append-only incremental change history  
**Why**: No README existed. Engineering context lived only in CLAUDE.md session instructions. Docs needed to capture system intent, technical structure, and capability inventory so future blocks have a grounded reference.  
**Files added**: `docs/BRD.md`, `docs/TRD.md`, `docs/CAPABILITY_REGISTRY.md`, `docs/CHANGE_JOURNAL.md`  
**Files edited**: none  
**Reuses**: Existing `docs/abode_identity.md`, `docs/abode_runtime.md`, `docs/abode_product_rules.md`, `docs/abode_cost_policy.md` as source of truth — not duplicated  
**Left out**: README.md (not requested), API reference (derivable from routes), data schema docs

---

---

## 2026-04-10 Docs access from inside The Abode
**Commit**: unreleased  
**What changed**: Project docs are now readable from inside the Neighborhood. A DOCS entry was added to the ops row; clicking it opens a panel with four tabs (Business Requirements, Technical Design, Capability Registry, Change Journal). Each tab fetches and renders the corresponding markdown file from `docs/`. Read-only — no editing features.  
**Why**: The four docs existed on disk but had no UI path. Operator needed to read project context without leaving the product.  
**Files edited**: `app/routes/neighborhood.py` only — backend endpoint, CSS, HTML ops unit, detail panel section, JS renderer and loader  
**Reuses**: Existing ops-unit pattern, detail panel, `_escHtml()`, `selectItem()`, `closePanel()` cooldown reset pattern  
**Left out**: Markdown table rendering (skipped; too complex for minimal renderer), search/filter, edit capability, versioning, export

---

## 2026-04-10 Peter front-layer role cleanup
**Commit**: unreleased  
**What changed**: Removed Peter's dependence on Belfort's research/activity state in the front layer. Peter's house no longer lights up green because Belfort is running. Peter's badge, speech bubble, and panel situation are now purely operator-facing.  
**Why**: Peter's visible state mirrored Belfort's activity (green glow + "RESEARCH ON" badge + "Research running" speech) which is role bleed — Belfort owns activity, Peter owns operator relevance.  
**Files edited**: `app/routes/neighborhood.py` only — three targeted edits: `populatePanel` Peter branch, `applyState` Peter section, `updateSummary` attention bar fallback  
**Reuses**: Existing `setClass`, `setSpeech`, `setBadge`, `setItems` helpers unchanged  
**Left out**: No new chat features, no new agent logic, no panel rewrite

---

## 2026-04-11 Vision reset and documentation alignment
**Commit**: unreleased  
**What changed**: Full documentation realignment to the intended direction of THE ABODE. This is a doctrine and architecture shift, not an implementation change.

**Doctrine changes captured**:
- THE ABODE is an AI workforce operating environment, not just a home for agents that trade and monitor themselves
- Backstage operating services (Custodian, Supervisor, Checker, Sentinel, Warden) are not houses — corrected in BRD and CAPABILITY_REGISTRY
- House eligibility standard defined: a house requires durable specialized role, measurable outcomes, some autonomy, standalone value, and real workflow ownership
- Belfort is a prototype revenue house and learning infrastructure proving ground — not just a mock trading script
- Live trading is a milestone earned through readiness, not a permanent constraint
- Builder / Incubator defined as a planned specialist house
- Autonomy escalation doctrine made explicit: earned through evidence and safeguards, never declared
- Layered architecture model formalized: experience / executive+control / specialist house / operating services
- "Learning must be real" — not prompt growth or reflection theater — stated as a hard rule
- Platform capabilities (readiness framework, verdict engine, campaign orchestration) distinguished from house-specific logic

**Files created**:
- `docs/vision/PROJECT_VISION.md` — strategic source of truth
- `docs/vision/CORE_DOCTRINE.md` — 10 design rules
- `docs/vision/ROLE_MAP.md` — layer model, role table, boundaries, Builder defined
- `docs/vision/HOUSE_ELIGIBILITY.md` — 5 criteria + current eligibility table
- `docs/vision/PRODUCT_MAP.md` — surface hierarchy and design intent
- `docs/vision/MILESTONE_MAP.md` — near/mid/long-term direction + autonomy doctrine
- `docs/vision/DOC_ALIGNMENT_NOTES.md` — what was misaligned and what changed

**Files revised**:
- `docs/BRD.md` — workforce framing, housed agents vs services, Belfort framing, live trading doctrine, updated principles
- `docs/TRD.md` — 4-layer architecture, operating services section, Belfort live trading preparation doctrine, reusable platform capabilities table
- `docs/CAPABILITY_REGISTRY.md` — restructured into three categories (housed, operating services, platform); classification metadata added

**Why**: The existing docs were implementation-accurate but did not reflect the true intended direction. Key gaps: no workforce framing, backstage services called houses, no house eligibility concept, no autonomy escalation doctrine, no Builder/Incubator, Belfort described too narrowly, architecture missing the four-layer model.  
**Left out**: No feature build. No CLAUDE.md rewrite. `docs/abode_identity.md` not fully revised (noted as remaining gap).

---

## 2026-04-11 Builder house — specification pass
**Commit**: unreleased  
**What changed**: Builder/Incubator defined as a real planned house with a complete spec. This is a design pass — no code was written.

**Decisions captured**:
- Builder and Incubator start as one house. Incubation is a workflow mode within Builder, not a separate domain. Split is a future milestone decision, not a starting assumption.
- Duplication/cloning is in Builder's scope but deferred until the core build workflow is stable.
- Four autonomy stages defined: Spec writer → Draft generator → Supervised builder → Trusted builder. Each requires demonstrated safety before advancing.
- Permanent off-limits files identified: `app/main.py`, `scripts/ctl.sh`, `app/loop.py`, `app/routes/neighborhood.py`, all runtime infrastructure.
- Builder depends on operating services: LMHelper/CostWarden (all LM calls), Sentinel (staging validation), event_log (build audit trail).
- Six new platform capabilities identified as gaps that Builder will force the platform to invent: spec schema, staging area, template library, build manifest format, diff review protocol, promotion workflow. These become platform capabilities when Builder reaches Stage 2.
- Bloat prevention rules established: mandatory eligibility gate before new house creation, default skepticism (backstage service before house), blast radius minimum.

**Files added**:
- `docs/builder/BUILDER_SPEC.md` — full spec including mission, workflows, ownership boundaries, inputs/outputs, approval boundaries, autonomy ladder, safety rules, reuse rules, success criteria, milestones, design question answers

**Files edited**:
- `docs/CAPABILITY_REGISTRY.md` — added planned section A.0 for Builder with four capability entries
- `docs/CHANGE_JOURNAL.md` — this entry

**Why**: Builder is the mechanism by which the Abode grows its own workforce. Without it, all construction work happens outside the system, breaking the workforce model. The spec establishes Builder as a real house candidate with earned-autonomy discipline, not a vague "AI coding assistant" concept.  
**Left out**: No code. No route stubs. No Peter integration. No staging area. No spec schema. All of those are Stage 1 build work, not spec work.

---

## 2026-04-11 Builder execution contract — design pass
**Commit**: unreleased  
**What changed**: Three design documents added to `docs/builder/`. No code written.

**Decisions captured**:
- Spec schema format: YAML frontmatter (structured) + markdown body (human context). Six build types: new_house, new_service, modification, platform_capability, clone, docs_only. Four risk levels: low, medium, high, critical. Risk level is determined by the highest-risk individual change in the build — main.py modification is always high.
- Staging model: Option C hybrid — staging inside repo at `staging/builder/` (gitignored, ephemeral), governance artifacts archived to `data/builder/archives/{build_id}/` after promotion (committed to git). Build log at `data/builder/build_log.jsonl`. Code artifacts are never stored in git twice; only spec + manifest + Sentinel report are archived.
- Against Option B (outside repo): breaks auditability doctrine. Against Option A (tracked in git): pollutes git history with draft code artifacts.
- First proof task: BUILD-001 — event log query endpoint (`GET /events`). New file `app/routes/event_query.py` + one include line in `app/main.py`. Exercises main.py approval boundary (most important safety check), validates reuse workflow, produces genuinely useful capability, near-zero blast radius if wrong.
- Against Candidate 1 (Custodian history): modifies existing files — too high blast radius for first proof. Against Candidate 3 (Builder status stub): too thin, doesn't test reuse, trivial success criterion.
- Staging lock: `.build.lock` file pattern (same as campaigns/.campaign.lock) — prevents concurrent builds.
- Promotion sequence documented: manual at Stage 1/2, automated at Stage 3+.

**Files added**:
- `docs/builder/SPEC_SCHEMA.md` — schema sections, required/optional fields by build type, full example spec for BUILD-001
- `docs/builder/STAGING_MODEL.md` — three-option evaluation, hybrid recommendation, directory structure, build log format, gitignore rule, promotion sequence, safety rules
- `docs/builder/FIRST_PROOF_TASK.md` — three candidate analysis, final recommendation with rationale, success/failure interpretation

**Why**: The Builder spec needed an execution contract before any implementation could begin. Schema defines what a build request looks like. Staging defines where artifacts go. Proof task defines what Builder proves itself on first.  
**Left out**: No code stubs. No `staging/` directory creation. No `.gitignore` update. No route files. All of that is implementation work for when Builder reaches Stage 2.

---

## 2026-04-11 BUILD-001 — Event log query endpoint
**Commit**: unreleased  
**What changed**: Implemented `GET /events` — a read-only query endpoint over `data/event_log.jsonl`. This is the first manual reference build executed against the Builder spec and staging design. Builder itself does not exist yet; this build was executed manually to validate the schema, approval workflow, and staging model.

**Risk resolved**: SPEC_SCHEMA and FIRST_PROOF_TASK had inconsistent risk levels for `app/main.py` changes. Resolved: any change to `app/main.py` is `critical`. Both docs updated before implementation began.

**Design assumptions stated explicitly**:
- No severity filter → all severities returned (differs from `read_recent_events` default; query endpoint is for explicit querying, not dashboard display)
- `agent` query param maps to `source` field in event records
- `since` boundary is inclusive
- `_MAX_READ=500` ceiling on events pulled before agent/since filtering — explicit tradeoff against completeness for very large logs

**Files added**: `app/routes/event_query.py`, `tests/test_event_query.py`  
**Files edited**: `app/main.py` (one import line + one include_router line)  
**Reuses**: `observability/event_log.read_recent_events()`, `observability/event_log.SEVERITIES` — no custom file reading  
**Tests**: 25 new tests, all pass. 586 existing tests unaffected.  
**Left out**: No neighborhood UI update, no Peter command integration, no build log entry (Builder infrastructure does not exist yet)

---

## 2026-04-11 BUILD-001 proof lane hardening
**Commit**: unreleased  
**What changed**: Closed the validation gap identified after BUILD-001.  
- `app/test_sentinel.py` — added `"app/routes/event_query.py": ["test_event_query.py"]` to `FILE_TEST_MAP`. Sentinel can now auto-detect and target the correct test suite when `event_query.py` is listed as a touched file.  
- `docs/builder/FIRST_PROOF_TASK.md` — status updated from "DRAFT" to "REFERENCE BUILD COMPLETE". Added reference callout block documenting that BUILD-001 was manually executed, all 25 tests pass, and Sentinel coverage is now wired.  
**Why**: BUILD-001 identified that Sentinel had no FILE_TEST_MAP entry for the new route file. Without it, a future staged validation run would fall back to smoke tests rather than targeting `test_event_query.py` directly. The design doc update completes the paper trail so the manual reference build is fully legible to future Builder work.  
**Files**: `app/test_sentinel.py`, `docs/builder/FIRST_PROOF_TASK.md`  
**Reuses**: Existing FILE_TEST_MAP pattern in Sentinel; no new code patterns introduced  
**Left out**: No new tests, no broader Sentinel changes, no Builder infrastructure, no neighborhood UI

---

## 2026-04-11 Builder Stage 1 execution flow — design pass
**Commit**: unreleased  
**What changed**: Full Stage 1 flow defined. No code written.

Key decisions captured:
- Builder request packet format (8 fields, Peter-authored, written to `data/builder/requests/`)
- Pre-flight checklist (8 mandatory questions, Builder must answer all before spec is ready)
- Review packet contents (spec summary + pre-flight + flagged concerns + decision form)
- Approval record schema (`approval.json` + build_log.jsonl line, both written at approval)
- Archive structure at Stage 1 (`request.json`, `spec.yaml`, `preflight.md`, `approval.json`)
- Stage 1 → Stage 2 transition: what stays identical vs what expands (two-gate approval, Sentinel auto-run, staged code artifacts)
- Sentinel role at each stage: not triggered at Stage 1 (spec identifies `sentinel_scope` as forward commitment); auto-triggered at Stage 2 before operator sees code
- Full 18-step lifecycle from operator request to `spec_approved` status
- Manual vs formalized split: request submission, spec production, staging can stay manual; request schema, log format, archive format, and 4 API endpoints must be formalized
- BUILD-002 sequencing: build AFTER Stage 1 data model pass so status endpoint reads real data, not mocked state

**Files added**: `docs/builder/STAGE1_FLOW.md`  
**Files edited**: `docs/CHANGE_JOURNAL.md`  
**Reuses**: SPEC_SCHEMA.md format, STAGING_MODEL.md directory conventions, BUILD-001 as reference example throughout  
**Left out**: No data model schema pass (next step), no route implementation, no Peter integration, no BUILD-002

---

## 2026-04-11 Builder Stage 1 data model — design pass
**Commit**: unreleased  
**What changed**: Four schema contracts defined for Builder Stage 1. No code written.

Schemas defined:
- **Request JSON** (`data/builder/requests/{id}_request.json`) — 6 required fields (Peter-authored), 4 optional. Immutable after Peter writes it.
- **Build log line** (`data/builder/build_log.jsonl`) — event-based JSONL. 5 Stage 1 events: `request_queued`, `spec_ready`, `spec_approved`, `spec_rejected`, `abandoned`. Peter writes `request_queued`; Builder writes the rest.
- **Archive manifest** (`data/builder/archives/{id}/manifest.json`) — contents index, written for all terminal outcomes including rejected/abandoned.
- **Builder status response** (`GET /builder/status`) — derived entirely from build_log.jsonl (no staging directory read). Includes pending/completed buckets and summary counts.

Also defined:
- `decision.json` schema (replaces `approval.json` name — covers approval AND rejection)
- Status derivation logic: latest event per build_id determines status
- Full lifecycle trace using BUILD-002 as example
- 6 naming/path decisions flagged for human direction
- Test fixture path: `tests/fixtures/builder/` (deferred until BUILD-002 test file is written)

Inconsistencies resolved:
- `spec.yaml` declared canonical (STAGING_MODEL had referenced `spec.json` + `spec.md`)
- Build log event names aligned to Stage 1 only (STAGING_MODEL had Stage 2+ events mixed in)

**Files added**: `docs/builder/DATA_MODEL.md`  
**Files edited**: `docs/CHANGE_JOURNAL.md`  
**Reuses**: Event log JSONL pattern from `observability/event_log.py`, temp-path patching pattern from `test_event_query.py` (noted for future test fixtures)  
**Left out**: No route stubs, no fixture files, no `data/builder/` directory creation, no BUILD-002

---

## 2026-04-11 BUILD-002 — Builder Stage 1 status endpoint
**Commit**: unreleased  
**What changed**: Implemented `GET /builder/status` — a real Stage 1 status endpoint that reads `data/builder/build_log.jsonl` and derives current build state per build_id. This is the second manual reference build against the Builder spec and data model.

**Design decisions**:
- `build_log.jsonl` is the sole source of truth for status derivation (no staging directory read)
- Title fallback chain: `request_queued.extra.title` → request file → `build_id`
- Unknown/future events (Stage 2+: `promoted`, `staged`, etc.) are silently skipped — latest known Stage 1 event governs
- All 5 Stage 1 events recognised: `request_queued`, `spec_ready`, `spec_approved`, `spec_rejected`, `abandoned`
- `builder_stage` hardcoded at `1` — not read from disk
- Missing `data/builder/` directory → empty-state 200 (never crashes)

**Files added**: `app/routes/builder_status.py`, `tests/test_builder_status.py`  
**Files edited**: `app/main.py` (one import + one include_router), `app/test_sentinel.py` (FILE_TEST_MAP entry)  
**Tests**: 25 new tests, all pass. 611 existing tests unaffected.  
**Reuses**: JSONL read pattern from `observability/event_log.py`, module-level path patching pattern from `test_event_query.py`  
**Left out**: No approval endpoints, no request creation endpoint, no detail endpoint (`GET /builder/{id}`), no neighborhood UI, no Peter integration

*To add a new entry: copy the format block above, fill in the fields, append at the bottom.*  
*Keep entries factual. The why and left-out fields matter most for future context.*
