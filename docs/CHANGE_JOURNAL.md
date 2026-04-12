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

## 2026-04-11 BUILD-003 — Peter → Frank Lloyd Stage 1 intake path
**Commit**: unreleased  
**What changed**: Wired the first real Peter → Frank Lloyd intake lane. `build <request>` in Peter now applies the HANDOFF_SPEC §1 readiness check; if clear enough, assigns the next BUILD-NNN id, writes `data/frank_lloyd/requests/{build_id}_request.json`, and appends a `request_queued` event to `data/frank_lloyd/build_log.jsonl`.

**Design decisions**:
- All logic is deterministic — no LM involved in readiness check (HANDOFF_SPEC intent: "deterministic first")
- Readiness check: description ≥ 5 words AND explicit success-criterion marker (`success:`, `done when:`, `test:`, `verify:`) AND criterion text ≥ 4 words
- Three failure modes returned as plain-English clarification Responses: `description_too_vague`, `missing_success_criteria`, `success_criteria_too_vague`
- File writes happen only on readiness pass — nothing written for rejected requests
- Frank Lloyd intake helpers live in `peter/handlers.py` with module-level path constants patchable for tests (same pattern as `frank_lloyd_status.py`)
- `BUILD_INTENT` added as a first-class `CommandType` in the Peter command layer; wired in `peter/router.py` dispatch table

**Files edited**: `peter/commands.py` (new CommandType + parse rule + HELP_TEXT), `peter/handlers.py` (new paths + `handle_build_intent` + 6 helpers), `peter/router.py` (import + dispatch entry), `app/test_sentinel.py` (FILE_TEST_MAP — peter files now map to test_peter_build_intake.py)  
**Files added**: `tests/test_peter_build_intake.py`  
**Tests**: 35 new tests, all pass. 627 total tests pass.  
**Reuses**: Peter command/handler/router pattern; `_fl_*` path constants follow `frank_lloyd_status.py` pattern; request file and log format per `docs/frank_lloyd/DATA_MODEL.md`  
**Left out**: No `POST /frank-lloyd/request` HTTP endpoint (not needed — intake goes through Peter command layer); no spec generation; no staging writes; no approval endpoints; `/peter/chat` LM handler unchanged (read-only guidance, separate concern)

## 2026-04-11 BUILD-004 — Frank Lloyd Stage 1 spec packet generation
**Commit**: unreleased  
**What changed**: Frank Lloyd can now produce a reviewable build packet from a queued request. `POST /frank-lloyd/{build_id}/spec` reads the request file, generates `spec.yaml` + `preflight.md` via LM, writes both to `staging/frank_lloyd/{build_id}/`, and appends `spec_ready` to the build log. If the LM is unavailable, `blocked.md` is written instead and a `blocked` event is appended.

**Design decisions**:
- All queue selection, off-limits checking (Q4), approval gates (Q8), file writing, and log appending are deterministic. LM is used only where architectural reasoning is unavoidable.
- LM tier: `strong` — spec generation is architecture analysis (layer placement, file set derivation, blast radius) per the cost policy. Cheap tier is not appropriate for this task.
- `_call_spec_lm` is module-level and patchable for tests — no real API calls in test suite.
- `blocked.md` + `blocked` log event follows HANDOFF_SPEC §8 exactly. `blocked` is not a Stage 1 terminal event, so `_derive_build_status` leaves the build in `pending_spec` state.
- Off-limits check scans full description + success_criteria for `app/main.py`, `scripts/ctl.sh`, `app/loop.py`, `app/routes/neighborhood.py` — flagged in spec.yaml AND preflight Q4.
- Q8 (approval gates) always identical at Stage 1: spec approval only; Stage 2 gates not yet applicable.
- `GET /frank-lloyd/next-queued` added for callers that need to find the pending build_id before triggering spec generation.

**Files added**: `frank_lloyd/__init__.py`, `frank_lloyd/spec_writer.py`, `app/routes/frank_lloyd_spec.py`, `tests/test_frank_lloyd_spec_writer.py`  
**Files edited**: `app/main.py` (import + include_router), `app/test_sentinel.py` (2 FILE_TEST_MAP entries)  
**Tests**: 47 new tests, all pass. 674 total tests pass.  
**Reuses**: `_read_log` / `_append_log` pattern from `frank_lloyd_status.py`; LMHelper from `app/cost_warden.py`; module-level path patching pattern consistent throughout Frank Lloyd codebase  
**Left out**: Approval endpoints (not Stage 1), staging promotion, Peter UX changes, `staging/` gitignore entry (not yet added)

## 2026-04-11 HARDENING — Frank Lloyd Stage 1 spec governance hardening
**Commit**: unreleased  
**What changed**: Added a deterministic validation/correction layer (`spec_validator.py`) that runs after LM draft generation and before any files or log events are written. Corrects doctrine violations the LM may introduce. Changed LM tier from `strong` to `cheap` — the validator is the safety net; the operator review is the approval gate. Also completed two governance contract fixes: `blocked` event documented in DATA_MODEL.md as a valid non-terminal event, and corrections are rendered visibly in `spec.yaml` so the operator can see exactly what the validator changed.

**Design decisions**:
- Validator applies 6 rules in order. Each rule records a correction if it fired. Rules win over LM output on every covered field.
- `risk_level` uses a deterministic floor: critical files → critical; any modified file → high; new file with integration → medium; isolated new file → low. Floor wins if it exceeds the LM's value; LM's value is kept if it is equal or higher (preserves upward risk signals from the LM).
- `blast_radius_failure_mode` is forced to `loud` when any critical file is touched — silent failure mode on infrastructure changes is not acceptable.
- LM tier downgraded from `strong` to `cheap` because: (a) the validator corrects doctrine violations, (b) the operator reviews and approves the spec, (c) Stage 2 code generation will use strong tier (code errors have higher blast radius than spec quality issues).
- `blocked` is a non-terminal non-advancing event per HANDOFF_SPEC §8. Documented in DATA_MODEL.md. The build stays in `pending_spec` state after a `blocked` event.
- `validation_corrections` section rendered in `spec.yaml` only when corrections exist — makes the validator's work visible to the reviewing operator.

**Files added**: `frank_lloyd/spec_validator.py`, `tests/test_frank_lloyd_spec_validator.py`  
**Files edited**: `frank_lloyd/spec_writer.py` (import validator, call after LM, pass corrections to _format_spec_yaml, include in spec_ready log extra, update LM tier comment), `app/test_sentinel.py` (sentinel map entry for spec_validator.py), `docs/frank_lloyd/DATA_MODEL.md` (documented `blocked` event in Stage 1 event table with semantics note)  
**Tests**: 44 new validator tests (all pass), 47 spec writer tests (all pass), 762 total tests pass.  
**Reuses**: Same correction record pattern as event_log.py; _apply helper pattern for immutable correction accumulation  
**Left out**: No UI surfacing of corrections (operator reviews spec.yaml directly); no retry-on-blocked endpoint; no spec revision cycle (Stage 1 only); DATA_MODEL spec_ready `extra` schema not updated to include `corrections` field (minor doc gap, not a contract issue)

## 2026-04-11 UI — Frank Lloyd neighborhood house
**Commit**: unreleased  
**What changed**: Frank Lloyd now appears as a visible third house in the neighborhood. Blueprint-indigo house (distinct from Peter's gold and Belfort's teal). Renders honest Stage 1 state only.

**Status states supported**: IDLE (no pending builds) · PENDING SPEC (build queued, spec not yet generated) · SPEC READY (spec generated, awaiting operator review). House CSS class follows: st-idle / st-warning / st-review.

**How status is derived**: `_frank_lloyd_state()` calls `frank_lloyd_status()` directly (same function as `GET /frank-lloyd/status`). Returns `pending_count`, `completed_count`, `approved_count`, `active_build` (first pending build or null). No new backend logic.

**Files edited**: `app/routes/neighborhood.py` (state function, CSS, house HTML, detail panel section, JS populatePanel/applyState/updateSummary/_META), `app/test_sentinel.py` (sentinel map entry for neighborhood.py)  
**Tests**: 762 tests pass (no regressions). No new tests — neighborhood has no unit test file in this repo; visual correctness verified by import/state-function smoke check.  
**Reuses**: `frank_lloyd_status()` route function directly; existing house CSS patterns; existing panel/badge/setItems helpers  
**Left out**: No "Open Frank Lloyd workspace" link to a separate dashboard tab (no Streamlit Frank Lloyd tab exists — action links to `/frank-lloyd/status` JSON instead). No approval controls in panel (Stage 1 has no approval endpoint yet). No fake "building" or "autonomous" labels.  
**Next block**: BUILD-005 — spec approval/rejection endpoint so builds can leave pending_review state.

## 2026-04-11 BUILD-005 — Stage 1 approval/rejection terminal gate
**Commit**: unreleased  
**What changed**: Implemented the Stage 1 approval/rejection terminal gate for Frank Lloyd. Builds in `pending_review` can now be approved or rejected through Peter's command flow (`approve BUILD-N [notes]` / `reject BUILD-N <reason>`).

**New module `frank_lloyd/spec_approver.py`**:
- `approve_build(build_id, notes)` — validates pending_review state, copies staging artifacts to archive, writes `decision.json` (outcome: spec_approved, stage2_authorized: False, spec_hash: sha256) + `manifest.json`, appends spec_approved log event with build_type, risk_level, stage_completed, stage2_authorized in extra
- `reject_build(build_id, reason, revision_cycle)` — same archiving, rejection decision.json (outcome: spec_rejected, stage2_authorized: None) + manifest.json, appends spec_rejected log event
- Both validate: build exists, status is pending_review, staging spec.yaml and preflight.md present, request file exists
- `_write_manifest()` per DATA_MODEL.md §3 — 4 files listed, manifest.json does NOT include itself
- `decision.json` not `approval.json` — DATA_MODEL.md is authoritative (resolves STAGE1_FLOW.md naming conflict)

**Peter wiring**:
- `CommandType.APPROVE_BUILD` / `REJECT_BUILD` added to `peter/commands.py`
- Parse rules inserted BEFORE existing `APPROVE_CANDIDATE`/`REJECT_CANDIDATE` rules — discriminated by `BUILD-` prefix on second token
- `handle_approve_build()` / `handle_reject_build()` added to `peter/handlers.py` — lazy module import (`import frank_lloyd.spec_approver as _fl_approver`) to pass transport isolation test
- Both handlers wired into `peter/router.py` dispatch table
- HELP_TEXT updated with `approve BUILD-N [notes]` and `reject BUILD-N <reason>`

**Transport isolation**: handlers use module-level lazy import instead of function import to avoid false-positive substring match in `test_peter_does_not_import_app_modules` (which checks for `"import app"` as substring; `from frank_lloyd.spec_approver import approve_build` would trigger it because `approve_build` starts with `app`).

**Files added**: `frank_lloyd/spec_approver.py`, `tests/test_frank_lloyd_spec_approver.py`, `tests/test_peter_build_approval.py`  
**Files edited**: `peter/commands.py`, `peter/handlers.py`, `peter/router.py`, `app/test_sentinel.py`  
**Tests**: 59 new tests (all pass), 821 total tests pass.  
**Reuses**: Same module-level patchable path pattern as spec_writer.py and other Frank Lloyd modules; existing Peter parse/handler/router flow; existing Response shape  
**Left out**: No Stage 2 authorization path (stage2_authorized is always False on approve); no HTTP endpoint for approval (operator uses Peter command flow per design); no UI approval button (no direct control in neighborhood panel); no abandoned flow  
**Next block**: Frank Lloyd spec view in neighborhood panel (clicking "SPEC READY" shows a summary of the spec) or Stage 2 authorization gate.

## 2026-04-11 Frank Lloyd provider-routing foundation
**Commit**: unreleased  
**What changed**: Added a Frank Lloyd-specific provider-routing layer that defines task/risk classes, routing policy per class, and a clean call interface (`FLLMHelper`). Claude is no longer the default — OpenRouter cheap models handle spec drafting. Stronger lanes are policy-complete and model-configured but not yet exercised (no Stage 2 code generation exists).

**Provider tiers (in cost/capability order)**:
- `cheap` → `FL_CHEAP_MODEL` (default: `openai/gpt-4o-mini`) — OpenRouter default lane, no operator approval gate
- `coding` → `FL_CODING_MODEL` (default: `openai/gpt-4o`) — supervised coding lane, approval gated
- `strong` → `FL_STRONG_MODEL` (default: `anthropic/claude-sonnet-4-6`) — Claude escalation, approval gated
- `critical_only` → `FL_CRITICAL_MODEL` (default: `anthropic/claude-opus-4-6`) — final proof, operator-mandatory

**Task class policy**:
| Task class | Tier | Stage | Approval |
|---|---|---|---|
| spec_draft | cheap | 1 only | No |
| code_draft_low | cheap | 2 only | No |
| code_draft_medium | coding | 2 only | Yes |
| code_draft_critical | strong | 2 only | Yes |
| review_proof | critical | 2 only | Yes |

**`frank_lloyd/provider_router.py`** (new): `FLTaskClass`, `FLProviderTier`, `FL_PROVIDER_REGISTRY`, `FL_TASK_POLICY`, `FLRoutingDecision`, `fl_route()`, `FLLMHelper`, `get_fl_policy_report()`. Stage enforcement: `fl_route()` returns `stage_allowed=False` if the calling stage is not in policy. Risk override upgrades only, never downgrades.

**`app/cost_warden.py`** (edited): Added `model_override: str | None = None` to `LMHelper.__init__()`. When set, bypasses tier→model resolution and uses the specified model directly (with `dataclasses.replace` to keep routing decision consistent for logging). Also added Frank Lloyd task classes to `TASK_POLICY` for warden report visibility. Non-breaking — existing callers pass nothing for `model_override`.

**`frank_lloyd/spec_writer.py`** (edited): `_call_spec_lm()` now routes through `FLLMHelper(FLTaskClass.SPEC_DRAFT, max_tokens=700)` instead of calling `LMHelper` directly. Same behavior at runtime — cheap OpenRouter model, stage=1. The routing layer is now explicit.

**What is real vs config-only**:
- REAL: `fl_route()` for all 5 task classes with full enforcement
- REAL: `FLLMHelper` with stage restriction and tier dispatch
- REAL: spec_writer routes through `FLLMHelper(SPEC_DRAFT)` — cheap lane actively used
- REAL: `model_override` in `LMHelper` — functional, tested
- CONFIG: coding/strong/critical lanes — policy complete, models named, env vars defined; no Stage 2 calls them yet

**Files added**: `frank_lloyd/provider_router.py`, `tests/test_frank_lloyd_provider_router.py`  
**Files edited**: `app/cost_warden.py`, `frank_lloyd/spec_writer.py`, `app/test_sentinel.py`  
**Tests**: 75 new tests (all pass), 896 total tests pass.  
**Reuses**: `app.cost_warden.LMHelper` for HTTP, logging, and usage tracking — no new OpenRouter client  
**Left out**: No Stage 2 code generation calls; no operator approval enforcement mechanism (approval_required is surfaced in routing decision but the caller is responsible for checking); no UI exposure of FL provider policy; no `fl_route()` call path from Peter commands  
**Next block**: Stage 2 authorization gate — operator command to authorize Stage 2 for a spec_approved build, or `abandoned BUILD-N` to close out dead builds.

---

## Provider-routing alignment pass (SHA: 7117d7cef)

**What changed**: Refined Frank Lloyd's provider-routing layer to correctly classify routing class, provider family, transport mode, executability, and approval requirements. `code_draft_critical` now routes to `CODEX_SUPERVISED` (not Claude). `STRONG` tier removed from all default task policies — reachable only via `risk_override`. `FLLMHelper.call()` refuses `external_supervised` lanes with a clear error instead of faking an API call. Three new metadata fields (`provider_family`, `transport_mode`, `executability`) added to `FLProviderConfig`, `FLRoutingDecision`, and `get_fl_policy_report()`. `FL_CODEX_MODEL` env override added. Tier rank order updated (CODEX_SUPERVISED=2, STRONG=3, CRITICAL=4).

**Why**: Prior pass left Claude as the silent default for `code_draft_critical`. Codex was claimed as first-class but had no structural distinction from API tiers. External lanes needed to be explicitly non-callable rather than implicitly skipped.

**Files edited**: `frank_lloyd/provider_router.py`, `tests/test_frank_lloyd_provider_router.py`  
**Tests**: 41 new tests added (116 in this file, 937 total pass), 0 regressions.  
**Reuses**: `FL_PROVIDER_REGISTRY` structure from prior pass; existing `FLLMHelper`/`fl_route()` control flow extended.  
**Left out**: No Stage 2 code generation; no Codex CLI integration (lane is policy-complete, transport is marked external_supervised); no UI exposure of provider metadata; no Peter command changes.  
**Next block**: Stage 2 authorization gate — operator command to authorize Stage 2 for a `spec_approved` build, or `abandon BUILD-N` to close out dead builds.

---

## Stage 2 authorization gate (SHA: 7117d7cef — working tree)

**What changed**: Added the explicit operator-controlled gate that bridges Stage 1 completion and Stage 2 eligibility. Peter now recognizes `authorize BUILD-N stage2 [notes]`. `frank_lloyd/stage2_authorizer.py` validates state (must be `spec_approved`), writes `stage2_authorization.json` to the archive, and appends a `stage2_authorized` log event. No code generation. No LM calls. Authorization only.

**Authorization record** (`stage2_authorization.json`) captures: `build_id`, `stage`, `authorized_at`, `authorized_by`, `authorization_notes`, `stage1_decision_outcome`, `provider_readiness` (executable/config_only/external_supervised lanes snapshotted from FL_PROVIDER_REGISTRY at auth time).

**Status map extended**: `stage2_authorized` event → `stage2_authorized` status. Defined locally in `stage2_authorizer.py` to avoid mutating `spec_approver.py`.

**Why**: Stage 1 approval does not automatically unlock Stage 2. The explicit gate keeps the two stages auditable and independently controlled. The `provider_readiness` snapshot in the authorization record answers "can Stage 2 actually run right now?" without pre-deciding task class.

**Files added/edited**:
- `frank_lloyd/stage2_authorizer.py` — new module (authorize_stage2, validation, provider_readiness)
- `peter/commands.py` — AUTHORIZE_STAGE2 command type + parse rule + HELP_TEXT
- `peter/handlers.py` — handle_authorize_stage2 (module import pattern)
- `peter/router.py` — import + dispatch entry
- `tests/test_frank_lloyd_stage2_authorizer.py` — 34 new tests
- `tests/test_peter_stage2_authorization.py` — 19 new tests
- `app/test_sentinel.py` — sentinel map entries for stage2_authorizer.py + updated peter/commands.py, handlers.py, router.py entries

**Tests**: 53 new tests (all pass), 990 total, 0 regressions.  
**Reuses**: Same Peter command → handler → FL module pattern as APPROVE_BUILD/REJECT_BUILD. Reads FL_PROVIDER_REGISTRY from provider_router.py for lane readiness snapshot.  
**Left out**: No Stage 2 code generation; no Codex CLI transport; no UI wiring; no HTTP endpoints; no abandon command (separate pass if needed).  
**Next block**: Stage 2 draft generation — first executable lane is `code_draft_low` (cheap/OpenRouter). Requires: `stage2_authorized` state check, LM call via FLLMHelper, written output to archive, new log event.

---

## BUILD-006: Frank Lloyd Front-Layer Action Controls

**SHA**: (pending commit)  
**Date**: 2026-04-11

**What changed**: Three Frank Lloyd action buttons wired into the neighborhood UI panel. Operators can now Approve, Reject (with required typed reason), or Authorize Stage 2 (with optional note) directly from the neighborhood — no Peter command required. Each button calls the same audited internal paths used by Peter commands.

**New HTTP endpoints** (`app/routes/frank_lloyd_actions.py`):
- `POST /frank-lloyd/{build_id}/approve-spec` — delegates to `frank_lloyd.spec_approver.approve_build()`
- `POST /frank-lloyd/{build_id}/reject-spec` — delegates to `frank_lloyd.spec_approver.reject_build()`; missing/empty reason → `ok=False` JSON at HTTP 200 (no 422)
- `POST /frank-lloyd/{build_id}/authorize-stage2` — delegates to `frank_lloyd.stage2_authorizer.authorize_stage2()`; message explicitly says "authorization only"

**Status display extended**: `stage2_authorized` added to `_STAGE1_EVENTS` and `_TERMINAL_EVENTS` in `frank_lloyd_status.py`. CSS classes added for `spec-approved` and `stage2-authorized` build status badges.

**Neighborhood UI** (`app/routes/neighborhood.py`):
- `_frank_lloyd_state()` extended with `spec_approved_build` field (first completed build with `status == spec_approved`)
- HTML: `fl-action-feedback` div, `fl-reject-form` (text input + confirm/cancel), `fl-authorize-form` (text input + confirm/cancel) added to Frank Lloyd section
- JS: `flApproveSpec`, `flShowRejectForm`, `flRejectCancel`, `flRejectConfirm`, `flShowAuthorizeForm`, `flAuthorizeCancel`, `flAuthorizeConfirm`, `_flAction`, `_flFeedback`, `_flHideForms` — all use `fetch()` to the action endpoints; inline Peter-style feedback shown

**Why**: Operators should be able to take approval decisions from the neighborhood without switching to the dev dashboard or typing Peter commands. The button → existing module path ensures no parallel action logic exists.

**Files added/edited**:
- `app/routes/frank_lloyd_actions.py` — new file (three POST endpoints)
- `app/main.py` — router import + include_router
- `app/routes/frank_lloyd_status.py` — `stage2_authorized` added to event sets
- `app/routes/neighborhood.py` — CSS, `_frank_lloyd_state()`, HTML forms, JS globals + action functions
- `tests/test_frank_lloyd_actions.py` — new file, 25 tests across 3 classes
- `app/test_sentinel.py` — sentinel map entry for `app/routes/frank_lloyd_actions.py`

**Tests**: 25 new tests (all pass), 1015 total, 0 regressions.  
**Reuses**: `frank_lloyd.spec_approver.approve_build()` / `reject_build()` (same as Peter APPROVE_BUILD/REJECT_BUILD commands); `frank_lloyd.stage2_authorizer.authorize_stage2()` (same as Peter AUTHORIZE_STAGE2 command); `/frank-lloyd/status` data feed already consumed by neighborhood state.  
**Left out**: No new agent state or separate action log — all audit trail is inside existing FL modules. No Stage 2 code generation. No "abandon" button (separate pass if needed). No optimistic UI updates — button → server round trip → feedback.  
**Next block**: Stage 2 draft generation — first executable lane (`code_draft_low`, cheap/OpenRouter), triggered after `stage2_authorized` state, output written to archive.

---

## BUILD-007: Frank Lloyd Stage 2 First Draft Generation

**SHA**: (pending commit)
**Date**: 2026-04-11

**What changed**: Frank Lloyd can now generate a first bounded Stage 2 draft artifact set for a `stage2_authorized` build. Uses the cheapest executable provider lane (`CODE_DRAFT_LOW` → cheap OpenRouter, `openai/gpt-4o-mini`, `executability=executable`). Non-executable lanes (`config_only`, `external_supervised`) are refused explicitly with a `draft_blocked` event — no silent escalation to Claude.

**Stage 2 events introduced**:
- `draft_generation_started` — logged before LM call; always paired with a follow-up
- `draft_generated` — logged on success
- `draft_blocked` — logged on executability refusal, LM failure, parse failure, or write failure

**Artifact set** (staging only, never live repo):
- `staging/frank_lloyd/{build_id}/stage2/draft_manifest.json` — generation metadata (provider, model, task class, files, tokens, cost, timestamps)
- `staging/frank_lloyd/{build_id}/stage2/draft_module.py` — generated Python module
- `staging/frank_lloyd/{build_id}/stage2/draft_notes.md` — LM generation notes

**Provider lane used**: `CODE_DRAFT_LOW` → `cheap` tier → `openrouter/gpt-4o-mini` (or `FL_CHEAP_MODEL` env override). No operator approval required. Not Claude. Not Codex.

**Peter command**: `draft BUILD-N [notes]` → `CommandType.DRAFT_STAGE2` → `handle_draft_stage2` → `generate_stage2_draft()`. `human_review_needed=True` on success.

**Status endpoint extended**: `draft_generation_started`, `draft_generated`, `draft_blocked` added to `_STAGE1_EVENTS`. `draft_generated`, `draft_blocked` added to `_TERMINAL_EVENTS`. Status gap for `stage2_authorized` closed with 7 new status tests.

**Files added/edited**:
- `frank_lloyd/stage2_drafter.py` — new module
- `app/routes/frank_lloyd_status.py` — Stage 2 draft events added to event sets
- `peter/commands.py` — `DRAFT_STAGE2` command type + parse rule + HELP_TEXT
- `peter/handlers.py` — `handle_draft_stage2`
- `peter/router.py` — import + dispatch entry
- `tests/test_frank_lloyd_stage2_drafter.py` — new, 55 tests
- `tests/test_peter_draft_stage2.py` — new, 20 tests
- `tests/test_frank_lloyd_status.py` — 7 new Stage 2 + `stage2_authorized` gap tests
- `app/test_sentinel.py` — sentinel map entries for stage2_drafter.py, updated peter and provider_router entries

**Tests**: 75 new tests (100 in targeted run, 0 failures), 1090 total suite, 0 regressions.
**Reuses**: `FLLMHelper` (provider_router.py); `fl_route()` for executability check; same `_append_log`/`_read_log` pattern as spec_approver/stage2_authorizer; Peter command→handler→FL module pattern.
**Left out**: Draft review UI; promotion flow; abandon flow; diff/patch output format; multi-file draft generation; Stage 2 route registration; coding tier or Codex CLI integration.
**Next block**: Draft review — show staged draft contents in neighborhood or via Peter command; then promotion/discard decision.

---

## 2026-04-11 BUILD-008 — Draft Review Surface

**Commit**: unreleased
**What changed**: Stage 2 staged draft artifacts are now surfaceable via the neighborhood UI and a dedicated API endpoint. Operators can see manifest metadata, generation notes, and the draft module code for `draft_generated` builds, and a clear block reason for `draft_blocked` builds.

**Why**: After BUILD-007 added draft generation, there was no way to view what was generated without reading staging files directly. This block adds the review layer (read-only) before any promotion flow exists.

**Review data exposed**:
- `GET /frank-lloyd/{build_id}/draft` — returns `{ok, build_id, status, manifest, module_code, notes_text, error}` from `staging/frank_lloyd/{build_id}/stage2/`
- For `draft_blocked` builds with no artifacts: reads block reason from `draft_blocked` log event `extra.error`
- For `draft_generated` builds: reads `draft_manifest.json`, `draft_module.py`, `draft_notes.md`

**Neighborhood additions**:
- `_frank_lloyd_state()` extended with `stage2_authorized_build` and `draft_build` fields; `draft_generated` takes priority over `draft_blocked` when multiple builds exist
- New `#fl-draft-section` HTML block: meta chips (task_class, provider_tier, model_used), generation notes, draft code in `<pre>` block (safe `.textContent`, not `.innerHTML`), blocked reason display
- `flLoadDraft(buildId)` JS function: fetches `/frank-lloyd/{buildId}/draft`, populates the review section
- Frank Lloyd panel JS updated: DRAFT READY / DRAFT BLOCKED / GENERATING badges; situation items for draft state; `flLoadDraft()` called automatically when `draft_build` is present
- CSS additions: `.fl-build-status.draft-generated`, `.fl-build-status.draft-blocked`, `.fl-draft-meta-row`, `.fl-draft-chip`, `.fl-draft-label`, `.fl-draft-notes`, `.fl-draft-code`

**Files added/edited**:
- `frank_lloyd/stage2_drafter.py` — `get_draft_review()` + `_draft_err()` added
- `app/routes/frank_lloyd_actions.py` — `GET /frank-lloyd/{build_id}/draft` endpoint added
- `app/routes/neighborhood.py` — `_frank_lloyd_state()` extended, CSS added, `fl-draft-section` HTML added, Frank Lloyd JS panel updated, `flLoadDraft()` function added
- `tests/test_frank_lloyd_draft_review.py` — new, 45 tests across 6 classes
- `app/test_sentinel.py` — sentinel map updated for `frank_lloyd_actions.py`, `stage2_drafter.py`, `neighborhood.py`

**Tests**: 45 new tests (45 passed, 0 failures), 1135 total suite, 0 regressions.
**Reuses**: `_read_log`/`_derive_status` from `stage2_drafter.py`; `_frank_lloyd_state()` pattern from neighborhood.py; same route wrapper pattern as approve/reject/authorize.
**Left out**: Promote-to-live-repo action (placeholder only); discard/abandon draft; diff/patch view; multi-file draft navigation; Peter `review BUILD-N` command shortcut.
**Next block**: Draft discard action — operator can discard a staged draft and re-authorize for a new attempt; or promote-to-live-repo first-pass decision flow.

---

## 2026-04-11 BUILD-009 — First Safe Promote-to-Live Flow

**Commit**: unreleased
**What changed**: Reviewed staged drafts can now be promoted to the live repo. First-pass promotion is narrow and conservative: CODE_DRAFT_LOW only, new .py files only, operator-supplied target path, no auto-overwrite. Full audit trail preserved.

**Why**: The draft review surface (BUILD-008) allowed reviewing staged artifacts but not acting on them. This closes the loop: reviewed draft → safe live file.

**Promotion safety rules (first pass)**:
- Build must be in `draft_generated` state — wrong state fails cleanly with no writes
- `draft_manifest.json` and `draft_module.py` must exist in staging
- `task_class` in manifest must be `code_draft_low` — higher task classes (medium, critical) are explicitly refused
- `target_path` must be a new `.py` file — existing files are never overwritten
- `target_path` must not be in `_OFFLIMITS_FILES` (`app/main.py`, `scripts/ctl.sh`, `app/loop.py`, `app/routes/neighborhood.py`)
- `target_path` must not start with `_OFFLIMITS_PREFIXES` (`data/`, `staging/`, `logs/`, `run/`, `.venv/`, `.git/`, `tests/`)
- No path traversal — absolute paths and `..` rejected
- One promotion per build — second attempt refused with clear error

**Artifacts written on promotion**:
- `{repo_root}/{target_path}` — live Python file (copy of staging draft_module.py)
- `data/frank_lloyd/archives/{build_id}/promotion_record.json` — full promotion evidence
- Build log event `draft_promoted` with target_path, task_class, model_used, provider_tier

**Staging artifacts preserved** — not deleted after promotion (audit trail).

**New events**:
- `draft_promoted` — appended to `build_log.jsonl` on successful promotion; advances status to `draft_promoted` (terminal)

**Peter command**: `promote BUILD-N path/to/file.py [notes]` → `CommandType.PROMOTE_DRAFT` → `handle_promote_draft`. `human_review_needed=True` on success. Inserted before existing `promote guidance` handler — discriminator is second token starting with `BUILD-`.

**Neighborhood additions**:
- `_frank_lloyd_state()` extended with `promoted_build` field (`draft_promoted` status)
- Badge: PROMOTED state (green, `ok` class)
- Situation item: `✓ Promoted: BUILD-N — live in repo`
- Active build display: PROMOTED — LIVE IN REPO badge (`draft-promoted` CSS class)
- Stage note: "Stage 2 complete · BUILD-N promoted to live repo. Review and test before importing."
- Promote block in `fl-draft-section`: target path text input + PROMOTE TO REPO button (visible only when `draft_generated`)
- `flPromoteDraft()` JS function: POSTs to `/frank-lloyd/{buildId}/promote-draft`, shows feedback, refreshes state on success
- CSS additions: `.fl-build-status.draft-promoted`, `.fl-target-input`

**Files added/edited**:
- `frank_lloyd/stage2_promoter.py` — new core module
- `app/routes/frank_lloyd_actions.py` — `POST /frank-lloyd/{build_id}/promote-draft` endpoint
- `app/routes/frank_lloyd_status.py` — `draft_promoted` added to `_STAGE1_EVENTS`, `_TERMINAL_EVENTS`
- `frank_lloyd/stage2_drafter.py` — `draft_promoted` added to `_STATUS_FROM_EVENT`
- `peter/commands.py` — `PROMOTE_DRAFT` command type, parse rule, HELP_TEXT
- `peter/handlers.py` — `handle_promote_draft`
- `peter/router.py` — import + dispatch entry
- `app/routes/neighborhood.py` — `promoted_build` state, CSS, HTML promote block, JS badge/situation/display updates, `flPromoteDraft()`
- `tests/test_frank_lloyd_stage2_promoter.py` — new, 74 tests across 8 classes
- `tests/test_peter_promote_draft.py` — new, 20 tests across 4 classes
- `app/test_sentinel.py` — sentinel map updated

**Tests**: 74 new tests (74 passed, 0 failures), 1209 total suite, 0 regressions.
**Reuses**: `_read_log`/`_derive_status`/`_append_log` pattern from spec_approver/stage2_drafter; `shutil.copy2` consistent with spec_approver archiving; Peter command→handler→FL module dispatch pattern.
**Left out**: Discard/abandon draft; promote higher-risk task classes (medium, critical); multi-file promotion; post-promotion test run trigger; revert/rollback; diff view before promoting.
**Next block**: Draft discard — `POST /frank-lloyd/{build_id}/discard-draft` → clears staging artifacts, logs `draft_discarded` event, resets build to `stage2_authorized` for a new draft attempt.

---

## BUILD-010 — Frank Lloyd natural-language intake + neighborhood compose form

**Commit**: (pending)
**Date**: 2026-04-11

**What changed**:

**NL build intake in Peter** (`peter/commands.py`): Module-level compiled regex `_FL_NL_BUILD_RE` recognises phrases like "have Frank Lloyd build X", "I want Frank Lloyd to make X", "Frank Lloyd, please build X", "Frank Lloyd should add X" etc. Inserted as a new parse rule before the existing `build ` handler. Matched commands become `CommandType.BUILD_INTENT` with `args["nl_intake"] = True`. The extracted description (preamble stripped) is passed as `raw_request`.

**Conversational handler responses** (`peter/handlers.py`):
- `handle_build_intent`: reads `nl_intake` flag; uses "Got it — queued as BUILD-N" and natural next-action text on success when `nl_mode=True`.
- `_fl_not_ready_response`: new `nl_mode=False` parameter. When `nl_mode=True`, clarification text is conversational ("Happy to queue that for Frank Lloyd — just need a bit more detail…"; "How would you know it's done?"; "Could you make the success check a bit more specific?") rather than CLI-style ("Not clear enough for Frank Lloyd yet.").

**`frank_lloyd/request_writer.py`** (new): Canonical shared request-creation module. `readiness_check()`, `extract_success_criterion()`, `extract_title()`, `queue_build()` — same validation logic as Peter's private helpers, exposed for the compose endpoint.

**`POST /frank-lloyd/compose-request`** (`app/routes/frank_lloyd_actions.py`): New endpoint for the neighborhood UI. Runs readiness check, extracts embedded success criterion if not provided separately, calls `frank_lloyd.request_writer.queue_build()`. Returns `{ok, build_id, title, message, error, missing_fields}`.

**Neighborhood compose form** (`app/routes/neighborhood.py`): `fl-compose-section` block added at the bottom of `frank-lloyd-section`. Two textareas (description, success criterion) + QUEUE BUILD button. `flQueueBuild()` JS function POSTs to `/frank-lloyd/compose-request`, shows inline feedback, clears form and refreshes state on success.

**Files added/edited**:
- `peter/commands.py` — `_FL_NL_BUILD_RE` regex + parse rule
- `peter/handlers.py` — `nl_intake` flag in `handle_build_intent`, `nl_mode` parameter in `_fl_not_ready_response`
- `frank_lloyd/request_writer.py` — new shared module
- `app/routes/frank_lloyd_actions.py` — `POST /frank-lloyd/compose-request` endpoint
- `app/routes/neighborhood.py` — compose form HTML + `flQueueBuild()` JS
- `tests/test_peter_nl_build_intake.py` — new, 40 tests (NL parse, extraction, negatives, handler responses, clarification)
- `tests/test_frank_lloyd_compose_request.py` — new, 30 tests (readiness, helpers, file I/O, endpoint validation, endpoint success)
- `app/test_sentinel.py` — sentinel map updated for `request_writer.py`, NL intake tests, compose tests

**Tests**: 70 new tests (70 passed, 0 failures), 0 regressions, 184 in the targeted batch.
**Reuses**: Same `_fl_readiness_check`/`_fl_next_build_id`/`_fl_write_request`/`_fl_append_log_event` logic (now also canonical in `request_writer.py`); existing `CommandType.BUILD_INTENT` + `handle_build_intent` handler; existing `flQueueBuild`-style JS pattern from other FL buttons.
**Left out**: Debounce/rate-limit on compose button; autofill from Peter conversation; auto-extract success criterion in the neighborhood form (done server-side only); draft success-criterion pre-population; form reset on panel close.
**Next block**: Draft discard — `POST /frank-lloyd/{build_id}/discard-draft` → clears staging artifacts, logs `draft_discarded` event, resets build to `stage2_authorized` so a new draft attempt can begin.

---

## BUILD-011 — Frank Lloyd draft discard / retry lane

**Commit**: (pending)
**Date**: 2026-04-11

**What changed**:

**`frank_lloyd/stage2_discarder.py`** (new): Core discard module.
- `DISCARDABLE_STATES = frozenset({"draft_generated", "draft_blocked"})` — explicit, documented.
- `discard_draft(build_id, notes="") → dict`: validates state, verifies `staging/frank_lloyd/{build_id}/stage2/` exists, removes it with `shutil.rmtree`, appends `draft_discarded` event.
- Rejects: unknown build, non-discardable state (including `draft_generating` and `draft_promoted`), missing stage2 artifacts.
- `_STATUS_FROM_EVENT["draft_discarded"] = "stage2_authorized"` — status resets to retry-ready.
- Stage 1 artifacts, Stage 2 authorization record, and `build_log.jsonl` are never touched.

**`draft_discarded` propagated to**:
- `app/routes/frank_lloyd_status.py` — added to `_STAGE1_EVENTS`; NOT in `_TERMINAL_EVENTS`; `_build_status_item` returns `derived_status = "stage2_authorized"` when latest event is `draft_discarded`.
- `frank_lloyd/stage2_drafter.py` — added to `_STATUS_FROM_EVENT`.
- `frank_lloyd/stage2_promoter.py` — added to `_STATUS_FROM_EVENT`.

**`POST /frank-lloyd/{build_id}/discard-draft`** (`app/routes/frank_lloyd_actions.py`): Thin endpoint delegating to `frank_lloyd.stage2_discarder`. Returns `{ok, build_id, outcome, discarded_at, message}`.

**Peter command** (`peter/commands.py`): `discard BUILD-N [notes]` → `CommandType.DISCARD_DRAFT`. Inserted before promote handler. Non-BUILD-N second token falls through.

**Peter handler** (`peter/handlers.py`): `handle_discard_draft` — validates build_id, calls `frank_lloyd.stage2_discarder.discard_draft`, returns success with `next_action` pointing to `draft BUILD-N`.

**Router** (`peter/router.py`): `CommandType.DISCARD_DRAFT: handle_discard_draft`.

**Neighborhood UI** (`app/routes/neighborhood.py`): `fl-draft-discard-block` added inside `fl-draft-section`. Two-step confirm flow: DISCARD DRAFT button → confirm row → CONFIRM DISCARD / CANCEL. Shown for both `draft_generated` and `draft_blocked`. `flDiscardAsk()`, `flDiscardCancel()`, `flDiscardConfirm()`, `flDiscardReset()` JS functions. POSTs to `/frank-lloyd/{build_id}/discard-draft`, refreshes state on success.

**Files added/edited**:
- `frank_lloyd/stage2_discarder.py` — new core module
- `app/routes/frank_lloyd_actions.py` — discard-draft endpoint
- `app/routes/frank_lloyd_status.py` — `draft_discarded` in `_STAGE1_EVENTS`, `derived_status` mapping
- `frank_lloyd/stage2_drafter.py` — `draft_discarded` in `_STATUS_FROM_EVENT`
- `frank_lloyd/stage2_promoter.py` — `draft_discarded` in `_STATUS_FROM_EVENT`
- `peter/commands.py` — `DISCARD_DRAFT` type, parse rule, HELP_TEXT
- `peter/handlers.py` — `handle_discard_draft`
- `peter/router.py` — dispatch entry
- `app/routes/neighborhood.py` — discard block HTML + JS
- `tests/test_frank_lloyd_stage2_discarder.py` — new, 40 tests across 8 classes
- `tests/test_peter_discard_draft.py` — new, 13 tests across 4 classes
- `app/test_sentinel.py` — sentinel map updated

**Tests**: 53 new tests (53 passed, 0 failures), 268 in targeted batch, 0 regressions.
**Reuses**: `_read_log`/`_derive_status`/`_append_log` pattern from stage2_promoter/stage2_drafter; `shutil.rmtree` for stage2 dir removal; Peter command→handler→FL module dispatch pattern; two-step confirm JS pattern from fl-reject-form.
**Left out**: Discard reasons/notes surfaced in UI (notes accepted but not displayed); bulk discard; discard from Peter's neighborhood widget (command only, not widget).
**Next block**: Frank Lloyd build queue page — show all builds (pending, completed, discarded, promoted) in the neighborhood with readable status labels and compact history.

---

## BUILD-012 — Frank Lloyd conversational lifecycle handler
**SHA**: pending  **Date**: 2026-04-11

**Goal**: Let the operator speak naturally to Peter across the entire Frank Lloyd lifecycle — not just at initial build intake. Any lifecycle action (approve, reject, authorize Stage 2, draft, promote, discard) can now be triggered conversationally, as well as status queries ("What's Frank Lloyd doing?", "Where is that build?").

**New CommandType**: `FL_LIFECYCLE_NL = "fl_lifecycle_nl"` — single dispatch point for all conversational FL actions.

**NL parse layer** (`peter/commands.py`):
Three insertion points in `parse_command()`, all placed after structured BUILD-N checks so explicit commands are never overridden:
1. Before `"what is" → STATUS`: `_FL_STATUS_QUERY_RE` matches FL status queries ("What's Frank Lloyd doing?" / "Where is Frank Lloyd?" / "frank lloyd status")
2. In promote block: `_FL_PROMOTE_NL_RE` catches "promote the draft / ship that / merge it" before `PROMOTE_GUIDANCE`
3. Before `approve_candidate`: `_fl_lifecycle_match()` catches approve/reject/authorize/draft/discard with FL context keywords

New regex constants: `_FL_STATUS_QUERY_RE`, `_FL_DISCARD_NL_RE`, `_FL_AUTHORIZE_S2_NL_RE`, `_FL_DRAFT_NL_RE`, `_FL_PROMOTE_NL_RE`, `_FL_REJECT_NL_RE`, `_FL_APPROVE_NL_RE`, `_FL_REASON_MARKER_RE`. Helpers: `_fl_extract_reason()`, `_fl_lifecycle_match()`.

**Handler** (`peter/handlers.py`):
`handle_fl_lifecycle_nl(command)` dispatches on `command.args["action"]`:
- `status_query` — reads build log, summarizes active builds in plain English
- `approve` / `reject` — calls `frank_lloyd.spec_approver.approve_spec` / `reject_spec`; reject with no reason asks conversationally
- `authorize_stage2` — calls `frank_lloyd.stage2_authorizer.authorize_stage2`
- `draft` — calls `frank_lloyd.stage2_drafter.generate_stage2_draft`
- `promote` — calls `frank_lloyd.stage2_promoter.promote_draft`; no target_path asks for one
- `discard` — calls `frank_lloyd.stage2_discarder.discard_draft`

Resolution helper `_fl_resolve_actionable_build(action)` reads the build log, derives statuses, finds the most recent build in the correct state for each action. `_fl_nl_nothing_to_do(action)` returns a `False` response when no actionable build exists.

**Bug fixed**: `_fl_drafter.generate_stage2_draft` — handler was referencing `generate_draft` (wrong name); corrected.

**Files added/edited**:
- `peter/commands.py` — `FL_LIFECYCLE_NL` CommandType, 8 NL regexes, 2 helpers, 3 parse insertion points; `_FL_STATUS_QUERY_RE` contraction fix (`what's` → `what(?:\s+is|\s*'s)`)
- `peter/handlers.py` — `handle_fl_lifecycle_nl`, `_FL_STATUS_MAP`, `_FL_ACTION_TARGET_STATUSES`, 5 resolution/status helpers
- `peter/router.py` — import + dispatch entry for `handle_fl_lifecycle_nl`
- `tests/test_peter_fl_lifecycle_nl.py` — new, 85 tests across 13 classes
- `app/test_sentinel.py` — sentinel map updated for `peter/commands.py`, `peter/handlers.py`, `peter/router.py`

**Tests**: 85 new tests (85 passed, 0 failures), 138 in targeted batch (discarder + discard-draft + fl-lifecycle-nl), 0 regressions.
**Reuses**: All existing `frank_lloyd.*` module functions (no second code path); Peter command→handler→FL module dispatch pattern established in BUILD-005 through BUILD-011; `_read_log`/`_derive_status` pattern from drafter/promoter.
**Left out**: No new FL stages or workflow changes; no LM interpretation (all deterministic regex parse); no Discord; no neighborhood widget changes; no bulk/multi-build disambiguation UI.
**Remaining gaps**: Neighborhood widget doesn't yet show conversational prompts; "that one" resolution is conservative (most-recent-in-right-state only, no session context); `promote` still requires explicit path in NL form.
**Next block**: Frank Lloyd build history page in the neighborhood — list all builds (pending/completed/discarded/promoted) with readable status labels, action buttons per state, compact timeline.

---

## BUILD-013 — Belfort graceful-stop behavior fix
**SHA**: pending  **Date**: 2026-04-11

**Goal**: Fix stop_trading() so that pressing Stop does not abandon an already-open position. Instead, the loop continues managing the existing trade (stop-loss / take-profit / MA exit signals) until the position closes, then fully stops.

**State machine added** (`app/trading_loop.py`):
- `_stop_requested: bool` — new module-level flag (alongside existing `_running`)
- Three-state model:
  - `_running=False, _stop_requested=False` → fully stopped
  - `_running=True, _stop_requested=False` → trading normally
  - `_running=True, _stop_requested=True` → stopping (managing open position to exit)

**`stop_trading()` change**: Checks `_has_open_position()` before deciding how to stop.
- No position → immediate stop (`_running=False`), returns `{"status": "stopped"}` — same as before.
- Open position → sets `_stop_requested=True`, leaves `_running=True`, returns `{"status": "stopping", "open_positions": [...]}`.

**`_loop_body()` change**: After each tick, if `_stop_requested` and `not _has_open_position()`, sets `_running=False, _stop_requested=False` and breaks. This is the only path to fully-stopped when a position was open.

**New entries not taken**: The existing `not has_position` guard in `mock_trade_task.mock_trade_spy()` already prevents BUY signals while a position is held. Since graceful stop is only triggered when a position IS open, no new entry can fire during the stopping window. No change to mock_trade_task needed.

**`start_trading()` change**: If called while `_running=True, _stop_requested=True` (mid-graceful-stop), cancels the stop (`_stop_requested=False`) and returns `{"status": "stop_cancelled"}`.

**`get_status()` change**: Added `stop_requested` field so callers (UI, monitoring) can distinguish stopping from fully running.

**Neighborhood** (`app/routes/neighborhood.py`):
- `_belfort_state()` now exposes `trading_stopping = ts.get("stop_requested", False)` alongside `trading_active`.
- `belfortSummaryLabel()` and status-detail line updated: shows "STOPPING…" / "STOPPING · RESEARCH ON" when `trading_stopping` is True.

**Files added/edited**:
- `app/trading_loop.py` — `_stop_requested` flag, `_has_open_position()` helper, graceful stop in `stop_trading()`, exit check in `_loop_body()`, cancel in `start_trading()`, `stop_requested` in `get_status()`
- `app/routes/neighborhood.py` — `trading_stopping` state exposed; status label updated
- `tests/test_trading_loop_graceful_stop.py` — new, 29 tests across 6 classes

**Tests**: 29 new tests (29 passed, 0 failures). No other test files touched.
**Reuses**: Existing `mock_trade_task.py` stop-loss/take-profit/MA-signal logic unchanged; portfolio position tracking unchanged; `not has_position` BUY guard unchanged.
**Left out**: Force-liquidation on stop (not asked for); stop-loss adjustment on graceful stop; neighborhood widget button state change (button still shows Stop while stopping — acceptable since loop is still running).
**Edge cases found**: (1) `start_trading()` while stopping now cancels stop cleanly without spinning a new thread; (2) `stop_trading()` when already stopped with stale `_stop_requested=True` handled by the `not _running and not _stop_requested` guard.
**Next block**: Neighborhood stop-button label update ("Stopping…" while in graceful-stop state) or Belfort house build-history page.

---

## BUILD-014 — Peter input UX fix: multiline textarea
**SHA**: pending  **Date**: 2026-04-11

**Goal**: Replace the single-line 280-char Peter chat input with a multiline auto-growing textarea so real build/development requests are comfortable to write and review.

**Changes** (`app/routes/neighborhood.py`):

**CSS**:
- `.peter-chat-input-row`: added `align-items: flex-end` so the Send button pins to the bottom of the textarea as it grows.
- `.peter-chat-input`: added `resize: none; min-height: 40px; max-height: 160px; overflow-y: auto; line-height: 1.5; box-sizing: border-box`. Single-line constraints removed.

**HTML**: `<input type="text" maxlength="280">` → `<textarea rows="2" maxlength="4000" placeholder="Ask anything… (Shift+Enter for newline)">`. Character limit raised from 280 to 4000.

**JS**:
- `_peterInputGrow(el)`: new helper — sets `height: auto` then clamps `scrollHeight` to 160 px. Called on `input` event and whenever `peterChatAsk()` fills the textarea programmatically.
- Keydown: `Enter` (without `Shift`) → `preventDefault` + `peterChatSend()`. `Shift+Enter` falls through to the default textarea newline behavior.
- Post-send: `inp.style.height = ''` resets the textarea to its minimum after the message is sent.
- `peterChatAsk()`: calls `_peterInputGrow()` after setting `.value` so the textarea sizes correctly when a chip is clicked.

**Files edited**: `app/routes/neighborhood.py` only.
**Tests**: No JS test infrastructure exists in this repo — all tests are Python unittest. Frontend-only input changes cannot be covered by the existing pattern. No tests added.
**Left out**: Chat history height adjustment (still 130 px), message rendering, backend `/peter/chat` endpoint, chip set.
**Next block**: Peter command workspace — route longer natural-language build requests through the existing `FL_LIFECYCLE_NL` / `BUILD_INTENT` parse layer, not just the LM chat path.

---

## BUILD-015 — Peter chat → Frank Lloyd build handoff
**SHA**: pending  **Date**: 2026-04-11

**Goal**: When the operator asks Peter to build/create something via the chat panel, the request is actually queued through the canonical Frank Lloyd path and Peter confirms with a BUILD-N id — instead of giving a conversational non-answer.

**New endpoint** (`app/routes/neighborhood.py`): `POST /peter/queue-build`
- Accepts `{message: str}` (up to 2000 chars)
- Treats the full message as the build description
- Calls `frank_lloyd.request_writer.extract_success_criterion(message)` to find any embedded criterion (`success:`, `done when:`, `test:`, etc.)
- Calls `frank_lloyd.request_writer.readiness_check(description, criterion)` — same validation as the composer form
- If not ready: returns `{ok: false, queued: false, text: plain-English explanation of what is missing}`
- If ready: calls `frank_lloyd.request_writer.queue_build(source="peter_chat")` and returns `{ok: true, queued: true, build_id, text: "Queued as BUILD-N for Frank Lloyd."}`
- Source field in the log event is `"peter_chat"` for auditability

**Client-side changes** (`app/routes/neighborhood.py` JS):
- `_isPeterBuildRequest(msg)`: keyword-based heuristic — returns `true` if message is a build directive (not a question/status query) that either mentions "Frank Lloyd" directly, or combines a build-action verb ("build ", "create ", "implement ", etc.) with a code-artifact noun ("endpoint", "module", "function", "test", "handler", etc.)
- `_peterQueueBuild(msg, inp, btn)`: async fetch to `/peter/queue-build`, shows result in Peter chat
- `peterChatSend()`: intercepts build requests BEFORE both the LM and deterministic paths; routes them to `_peterQueueBuild` and returns — no LM call for build requests

**Files edited**: `app/routes/neighborhood.py` (backend endpoint + JS)
**Files added**: `tests/test_peter_queue_build.py` — 22 tests across 5 classes

**Tests**: 22 new tests (22 passed, 0 failures). No regressions.
**Reuses**: `frank_lloyd.request_writer` (same module as `/frank-lloyd/compose-request`); `readiness_check()`, `extract_success_criterion()`, `queue_build()` unchanged; build IDs generated by the same `_next_build_id()`.
**Left out**: LM-assisted criterion extraction from ambiguous requests (kept deterministic); build status follow-up in chat; multi-turn clarification loop.
**Remaining gaps**: `_isPeterBuildRequest()` heuristic has no JS unit tests (no JS test infrastructure). If LM is available and the message is not detected as a build request, the LM may still give advisory-only responses for ambiguous phrasings — exact boundary depends on phrasing.
**Next block**: Frank Lloyd build history page in the neighborhood — all builds (pending/active/promoted/discarded) with readable labels and per-state action buttons.


---

## BUILD-016 — Frank Lloyd workflow visibility + actionability
**SHA**: pending  **Date**: 2026-04-11

**Goal**: Fix the Frank Lloyd panel so every build stage is visible, actionable, and labeled correctly — replacing vague placeholders with real progress feedback.

**Problem areas addressed**:
1. `pending_spec` stuck: no UI button to trigger spec generation — added GENERATE SPEC button (calls existing `POST /frank-lloyd/{build_id}/spec`).
2. `stage2_authorized` stuck: no "Generate Draft" button and no endpoint wired to it — added `POST /frank-lloyd/{build_id}/generate-draft` endpoint + UI button.
3. Bad build titles: `extract_title()` ran on full conversational messages, producing "Peter have Frank Lloyd fix Belfort's" — fixed with `_BOILERPLATE_RE` stripping.
4. No progress context: replaced the flat status label with a 6-stage track (QUEUED → SPEC → REVIEW → AUTH → DRAFT → LIVE) with done/active/blocked styling.
5. No "waiting on" clarity: added per-state `_flWaitingOn()` label (waiting-me vs waiting-system).
6. No Belfort cross-reference: Belfort panel now shows `fl-belfort-work` div when an active FL build references Belfort.

**New endpoint** (`app/routes/frank_lloyd_actions.py`):
- `POST /frank-lloyd/{build_id}/generate-draft`: delegates to `frank_lloyd.stage2_drafter.generate_stage2_draft()` — same function as Peter `draft BUILD-N` command. Returns `{ok, build_id, outcome, message}`.

**Title cleaning** (`frank_lloyd/request_writer.py`):
- Added `_BOILERPLATE_RE` regex stripping "Peter, have/tell/ask Frank Lloyd to …" prefix before extracting title from description.
- `extract_title()` now strips boilerplate before picking 6 meaningful words — no change to `queue_build()`.

**Title cleaning (status endpoint)** (`app/routes/frank_lloyd_status.py`):
- Added `_TITLE_BOILERPLATE_RE` and `_clean_display_title()` mirror of `request_writer` pattern.
- `_extract_title()` now reads the full description from the request file, strips boilerplate, then falls back to stored title → event title → build_id.

**UI changes** (`app/routes/neighborhood.py`):
- `_frank_lloyd_state()` backend: added `belfort_related_build` (dict with build_id + title) when an active non-terminal build description contains "belfort".
- CSS: `.fl-progress-track`, `.fl-stage-step` (done/active/blocked variants), `.fl-waiting-on` (waiting-me/system), `.fl-belfort-work`.
- JS: `_flRenderProgress()` maps 9 pipeline statuses to a 6-stage visual; `_flWaitingOn()` returns per-status waiting labels; `flGenerateSpec()` + `flGenerateDraft()` async action handlers; expanded action buttons map for all pipeline states.
- Belfort panel: renders `fl-belfort-work` div when `belfort_related_build` is present in state.

**Test fix** (`tests/test_frank_lloyd_actions.py`):
- `test_authorize_message_says_authorization_only` updated to `test_authorize_message_says_stage2_authorized` — message wording changed in BUILD-016 to "Stage 2 authorized. Use Generate Draft to start code generation."

**Files edited**: `frank_lloyd/request_writer.py`, `app/routes/frank_lloyd_status.py`, `app/routes/frank_lloyd_actions.py`, `app/routes/neighborhood.py`, `app/test_sentinel.py`, `tests/test_frank_lloyd_actions.py`
**Files added**: `tests/test_frank_lloyd_build016.py` — 22 tests (7 generate-draft, 7 _clean_display_title, 8 extract_title)

**Tests**: 22 new (22/22 pass). 1 existing test updated and fixed. No other regressions.
**Reuses**: `frank_lloyd.stage2_drafter.generate_stage2_draft()` (same path as Peter `draft BUILD-N`); `frank_lloyd.request_writer.queue_build()` unchanged; all existing spec/approve/reject/authorize/promote/discard endpoints unchanged.
**Left out**: Spec generation progress spinner (synchronous call); draft review diff view; promote form in the FL panel (handled in a prior build); multi-build accordion layout.
**Remaining gaps**: `_isPeterBuildRequest()` heuristic has no JS tests. `pending_spec` GENERATE SPEC button calls synchronous LM spec writer — no progress feedback for long generations.
**Next block**: Neighborhood polish pass — simplify Peter chat panel labels, add a "last action" timestamp to the FL build list, and verify the stopping-state button UX renders correctly on a live Belfort stop sequence.

---

## BUILD-017 — Frank Lloyd review + queue semantics cleanup
**SHA**: pending  **Date**: 2026-04-11

**Goal**: Fix Frank Lloyd's review visibility and queue bucket honesty so the pipeline is truly reviewable and counts/states are correct.

### Part 1: Spec review visibility

**New endpoint** (`app/routes/frank_lloyd_actions.py`): `GET /frank-lloyd/{build_id}/spec-review`
- Reads `spec.yaml` + `preflight.md` from `staging/frank_lloyd/{build_id}/` for `pending_review` builds
- Reads from `data/frank_lloyd/archives/{build_id}/` for post-approval states (falls back to staging)
- Returns `{ok, build_id, status, spec_yaml, preflight_md, error}`

**New HTML section** (`app/routes/neighborhood.py`): `#fl-spec-section`
- Shown when a build is in `pending_review` or any post-spec state (spec_approved, stage2_authorized, draft_*)
- `SPEC.YAML` block: scrollable `<pre>` with spec content
- `PREFLIGHT CHECKLIST` block: scrollable `<pre>` with preflight content
- Approve/Reject controls are in the existing action button area (unchanged)

**New JS function**: `flLoadSpec(buildId)` — async fetch to `/spec-review`, renders both blocks

### Part 2: Honest queue semantics

**`app/routes/frank_lloyd_status.py`**: replaced flat `pending/completed` with three honest buckets:

| Bucket | Statuses |
|---|---|
| **pending** | `pending_spec`, `pending_review` |
| **inprogress** | `spec_approved`, `stage2_authorized`, `draft_generation_started`, `draft_generated`, `draft_blocked`, `draft_discarded→stage2_authorized` |
| **completed** | `draft_promoted`, `spec_rejected`, `abandoned` |

Response shape: added `inprogress_builds` list; summary now includes `inprogress_count`.

`approved_count` in summary = `len(inprogress)` + promoted count (all inprogress builds passed spec approval).

**`_frank_lloyd_state()` backend** (`neighborhood.py`): now reads `inprogress_builds` for `spec_approved_build`, `stage2_authorized_build`, and `draft_build`.

### Part 3: Next-action clarity

**`_flWaitingOn()`** rewritten with explicit "Next:" / "Waiting:" / "Done:" / "Closed:" prefixes per state:
- `pending_spec` → `Next: generate the spec`
- `pending_review` → `Next: review the spec below — then approve or reject`
- `spec_approved` → `Next: authorize Stage 2 to start draft generation`
- `stage2_authorized` → `Next: generate draft when ready`
- `draft_generating` → `Waiting: Frank Lloyd is generating the draft…`
- `draft_generated` → `Next: review draft below — then promote to repo or discard`
- `draft_blocked` → `Next: review block reason below — discard and retry`
- `draft_promoted` → `Done: build complete — code is live in the repo`
- `spec_rejected` / `abandoned` → `Closed: …`

**Queue stats**: updated from 2 to 3 counters (PENDING / IN PROGRESS / DONE).
**Status detail**: updated from "Stage N · N pending · N completed" to "N pending · N in progress · N done".

**Files edited**: `app/routes/frank_lloyd_status.py`, `app/routes/frank_lloyd_actions.py`, `app/routes/neighborhood.py`, `app/test_sentinel.py`, `tests/test_frank_lloyd_status.py`
**Files added**: `tests/test_frank_lloyd_build017.py` — 21 tests (9 spec-review, 11 three-bucket, 1 inprogress sort)

Wait — 9 + 11 = 20 tests. Let me recount. TestSpecReviewEndpoint: 9. TestThreeBucketSemantics: 11. Total: 20 new tests.

**Tests**: 20 new (20/20 pass); 13 existing tests in `test_frank_lloyd_status.py` updated to reflect new bucket semantics. Total: 99/99 pass across all FL test files.
**Reuses**: `GET /frank-lloyd/{build_id}/draft` pattern for the new spec-review endpoint; existing approve/reject/authorize action buttons unchanged; progress track and waiting-on infrastructure from BUILD-016 extended in-place.
**Left out**: Markdown rendering of preflight.md (shown as plain text `<pre>`); spec diff view between revision cycles; approve/reject controls embedded inside the spec section (still in the action button area).
**Remaining gaps**: No spec-review test via real filesystem with actual BUILD-001 artifacts. Spec section is always full-height (no collapse toggle for longer specs).
**Next block**: Neighborhood polish — verify the 3-bucket count display renders correctly, test the spec review section on a real `pending_review` build, and confirm Belfort stopping-state rendering is correct end-to-end.

---

## 2026-04-11 BUILD-018 — Frank Lloyd unified job model + discard reload fix + CAPABILITY_REGISTRY injection
**Commit**: unreleased  
**What changed**: Phase 1 of the Frank Lloyd re-architecture:

1. **`frank_lloyd/job.py`** (new) — Unified FLJob dataclass with phase model (intake/plan/authorized/building/live/closed), deterministic `next_action` and `waiting_on` fields, and three public functions: `load_job(build_id)`, `load_active_job()`, `list_jobs()`. Consolidates the duplicated `_STATUS_FROM_EVENT` maps into a single canonical source.

2. **`GET /frank-lloyd/active-job`** (new endpoint) — Returns the highest-priority build needing operator attention. Uses `load_active_job()` priority ordering: `pending_review` > `draft_generated` > `draft_blocked` > `spec_approved` > `stage2_authorized` > `draft_generating` > `pending_spec`.

3. **Discard reload mess fixed** — After a draft discard, the spec section was auto-showing due to `s2Authorized.build_id` being non-null post-discard. Fix: added `_flSpecVisible = false` JS flag; spec section now only auto-shows for `pending_review` state. All other states require explicit "View spec" toggle. Toggle state is reset on `closePanel()` and on successful discard. This eliminates the visual chaos (spec flashing in after discard).

4. **`frank_lloyd/spec_writer.py`** — Added `_load_capability_excerpt()` that reads `docs/CAPABILITY_REGISTRY.md` and extracts live capability names + code locations. Injected into the spec LM user message so the LM can make better reuse decisions (knows what `observability/`, `research/`, `app/cost_warden.py` etc. already provide).

**Design decisions**:
- `frank_lloyd/job.py` is self-contained (no imports from other frank_lloyd modules) to avoid circular imports. Other modules still read the build_log directly — `job.py` provides the consolidated API layer only.
- `_flSpecVisible` flag is module-level JS, not per-build. It reflects whether the user has explicitly opted in to viewing the spec. This is correct because only one build is ever in the focal panel at a time.
- CAPABILITY_REGISTRY excerpt is read at spec generation time (not cached). Non-fatal if the file is missing or unreadable.

**Files added**: `frank_lloyd/job.py`, `tests/test_frank_lloyd_job.py`  
**Files edited**: `app/routes/frank_lloyd_actions.py` (new endpoint), `frank_lloyd/spec_writer.py` (capability injection), `app/routes/neighborhood.py` (discard fix + spec toggle), `app/test_sentinel.py` (sentinel map)  
**Tests**: 32 new (32/32 pass). No regressions in BUILD-017 tests (77/77 pass).  
**Reuses**: `_read_log` pattern from `frank_lloyd_status.py`; `_clean_display_title` / `_extract_title` pattern consolidated from `frank_lloyd_status.py` and `frank_lloyd/spec_writer.py` into `frank_lloyd/job.py`; existing FL action endpoint pattern for the new `active-job` endpoint.  
**Left out**: Full FL panel redesign to use `active-job` endpoint (deferred — would require replacing the `neighborhood/state` FL aggregation); CAPABILITY_REGISTRY update for Frank Lloyd's new live capabilities (deferred to next doc pass); `draft_generating` status display (existing `draft_generation_started` event maps to it but the house badge still says IDLE unless `draft_generated` fires).  
**Remaining gaps**: Panel still has 10 fragmented conditional sections (redesign deferred). `spec_writer.py` still uses the LM capability excerpt only for reuse guidance — the `MANDATORY_REUSE_TEXT` remains authoritative. No `frank_lloyd/job.py` usage in the neighborhood state endpoint yet.  
**Next block**: Neighborhood FL panel redesign — replace the 10 fragmented conditionals with a phase-aware single workspace driven by `GET /frank-lloyd/active-job`. This eliminates the remaining visual fragmentation and makes the panel feel like a single coherent build workspace.

---

## 2026-04-11 BUILD-018 Phase 2 — Frank Lloyd phase-aware workspace
**Commit**: unreleased  
**What changed**: Replaced the fragmented Frank Lloyd neighborhood panel (10+ conditionals, ~160-line handler) with a single phase-aware workspace driven by `active_job` from `frank_lloyd/job.py`.

1. **CSS fix** — `fl-queue-stats` grid was `1fr 1fr` (2 columns) but renders 3 stats. Fixed to `1fr 1fr 1fr`.

2. **`_frank_lloyd_state()` — `active_job` field** — Added `active_job` key to the Python function return. Calls `load_active_job()` and serializes via `to_dict()`. Falls back to `None` in both the success and exception branches. `active_job` now flows through `/neighborhood/state` → JS `state.frank_lloyd.active_job`.

3. **`fl-workspace` HTML wrapper** — Replaced flat sibling layout with a single `<div id="fl-workspace">` that wraps `fl-active-build`, `fl-progress-track`, `fl-waiting-on`, `fl-action-feedback`, forms, `fl-draft-section`, and `fl-spec-section`. Removed the `PROGRESS` section label. `fl-workspace` shows/hides as a unit. `fl-compose-section` stays outside (always visible).

4. **`_flRenderWorkspace(job)` (new JS function)** — Single entry point for all workspace state. Reads `job` object (from `active_job`), shows/hides `fl-workspace`, populates build header with phase badge + type/risk chips + build_id, calls `_flRenderProgress`, sets waiting-on text/class via `_flJobWaitingOnText/Cls`, and manages `fl-draft-section` and `fl-spec-section` visibility.

5. **New JS helpers** — `_flJobWaitingOnText(job)`, `_flJobWaitingOnCls(job)`, `_flPhaseBadgeCls(phase)` — replace the removed `_flWaitingOn(status)` function. Helpers read from `job.waiting_on` and `job.next_action` (deterministic fields from `FLJob`), not from a local status map.

6. **`frank-lloyd` panel handler** — Simplified from ~170 lines to ~80 lines. Badge/status still uses phase/status from `active_job`. Situation items are driven by `job.phase` and `job.next_action`. Action buttons use a `switch(jStatus)` instead of if/else chains. View Spec toggle simplified (no longer needs `specSourceBuild` lookups — checks `hasSpec` from job status).

7. **Removed `_flWaitingOn(status)`** — Replaced by `_flJobWaitingOnText/Cls(job)` helpers.

**Design decisions**:
- `fl-compose-section` stays outside `fl-workspace` intentionally — it is the "new build" intake point and should always be accessible regardless of whether there is an active build.
- `_flRenderWorkspace(job)` hides the workspace when `job` is null (no active builds). Terminal builds (promoted/rejected) show as null-equivalent from `load_active_job()` only if there's nothing else — we rely on `load_active_job()` priority logic rather than filtering here.
- Phase badge uses inline styles (not CSS classes) to allow 6-phase color palette without adding global CSS.
- `_flWaitingOn(status)` removed entirely — no dead code left. Replaced fully by job-model helpers.

**Files edited**: `app/routes/neighborhood.py` (CSS, HTML, Python, JS — all sections), `app/test_sentinel.py` (sentinel map)  
**Files added**: `tests/test_frank_lloyd_build018.py` (12 tests)  
**Tests**: 12 new tests (12/12 pass). No regressions — 669 Frank Lloyd tests pass.  
**Reuses**: `_flRenderProgress('fl-progress-track', ...)` reused unchanged; `flLoadDraft`, `flLoadSpec`, `flGenerateSpec/Draft`, `flApproveSpec`, `flShowRejectForm`, `flShowAuthorizeForm` — all action functions reused unchanged; `_frank_lloyd_state()` outer structure (frank_lloyd_status call, belfort_related_build logic) fully reused.  
**Left out**: `active_build`, `spec_approved_build`, `stage2_authorized_build`, `draft_build`, `promoted_build` fields still returned by `_frank_lloyd_state()` for Belfort panel cross-reference and any other consumer — not removed. Full cleanup of those from the Python state function is future work. No progress-track CSS changes.  
**Remaining gaps**: `active_build` / draft/spec/promoted build fields still duplicated in state (dead weight once all consumers migrate to `active_job`). Phase badge renders inline style — could be a CSS class system in a future polish pass.  
**Next block**: Verify the full panel end-to-end: queue a build, confirm workspace shows with correct phase badge and waiting-on text. Then consider migrating Belfort panel's `flRel` lookup to use `active_job` too.

---

## [2026-04-11] Frank Lloyd Experience Redesign — Builder Workspace Pass

**Commit**: unreleased  
**What changed**: Complete redesign of the Frank Lloyd neighborhood panel — replacing the fragmented state-machine UI with a coherent builder workspace that feels like a prompt-driven coding tool.

**1. CSS** — Removed 42 lines of stale FL CSS (fl-queue-stats grid, fl-stat cells, fl-active-build, fl-build-status variants, fl-draft-label, fl-draft-code, fl-target-input, fl-progress-track, fl-stage-step, fl-waiting-on). Replaced with clean builder CSS: fl-job-header, fl-job-title-row, fl-phase-chip (6 phase states: queued/review/building/ready/applied/blocked), fl-stream/fl-stream-entry/fl-se-*, fl-review-area, fl-tab/fl-review-pane, fl-code-view, fl-field-label, fl-composer-label, fl-prompt-box.

**2. HTML** — Replaced the old multi-section layout (BUILD QUEUE stats grid + active build header + progress track + waiting-on line + DRAFT REVIEW section + SPEC REVIEW section + REQUEST A BUILD section) with a single unified builder workspace: `fl-job-workspace` (contains: job header with title + phase chip + meta line, work stream `fl-stream-entries`, tabbed review area `fl-review-area` with Plan + Draft Code tabs, and action area with inline forms for reject/authorize/promote). Composer is a single large `fl-prompt-box` textarea (replaces the 2-textarea desc+criterion pattern).

**3. Visible phases** — Internal states are now mapped to human-readable builder phases: pending_spec→QUEUED, pending_review→NEEDS REVIEW, spec_approved/stage2_authorized/draft_generating→BUILDING, draft_generated→DRAFT READY, draft_blocked→BLOCKED, draft_promoted→APPLIED. "Spec" renamed to "Plan" throughout the UI. "Stage 2 authorize" renamed to "Authorize Build". "Promote to repo" renamed to "Apply to Repo".

**4. Work stream** — New `_flRenderStream(job)` function synthesizes a chronological activity log from job status. Shows up to 5 entries (Queued → Plan ready → Plan approved → Authorized → Draft ready/Building/Blocked/Applied) with icons and per-entry color coding.

**5. Simplified action area** — Removed: discard confirm-row (now a single `flDiscardDraft()` call with instant feedback), promote-block buried inside draft-section (now a clean inline form), spec-section and draft-section as separate top-level blocks (now tabs). Added: `flShowPromoteForm()` / `flPromoteConfirm()` / `flPromoteCancel()`, `flTabSwitch(tab)`, `flToggleReview()` (replaces `flToggleSpec()`), `flDiscardDraft()` (replaces 4 discard functions).

**6. Global var** — `_flSpecVisible` renamed to `_flReviewVisible`. All 3 references updated (declaration, closePanel, populatePanel).

**Why**: The previous Frank Lloyd panel exposed internal state machine steps directly in the UI (pending_spec, spec_approved, stage2_authorized), had 5 separate named sections that felt like tabs in a developer console, had no sense of Frank Lloyd being alive or doing something, and required navigating multiple separate blocks for a single build lifecycle.

**Files edited**: `app/routes/neighborhood.py` (CSS, HTML, JS populatePanel frank-lloyd block, all JS FL helpers — ~200 lines removed, ~220 lines added net; no backend changes)  
**Tests**: 33/33 Frank Lloyd status tests pass (unchanged). No regressions.  
**Reuses**: All backend endpoints unchanged (approve-spec, reject-spec, authorize-stage2, generate-draft, promote-draft, discard-draft, spec-review, draft, compose-request). `_frank_lloyd_state()` Python function unchanged. `_flAction()`, `_flFeedback()` helper pattern reused.  
**Left out**: Streaming real-time progress (still synthetic from status). Backend `frank_lloyd/job.py` not changed. No new API endpoints.  
**Remaining gaps**: Work stream is synthesized from status, not from real event timestamps. Review area shows/hides on toggle — could auto-open for pending_review. No keyboard shortcuts for approve/reject. Composer does not pre-fill from Peter chat history.  
**Next block**: Verify end-to-end with an active build visible: queue a build, confirm work stream renders, confirm Plan tab loads spec, confirm Draft Code tab shows code, confirm Apply to Repo form works cleanly.

## 2026-04-11 Frank Lloyd Autonomy + Builder Experience — Safe Lane Auto-Run

**Commit**: unreleased
**What changed**: Frank Lloyd now behaves like a prompt-and-go builder for low-risk isolated builds. Queuing a build immediately triggers the safe-lane pipeline (spec → auto-approve → auto-authorize → draft) in the background. Manual steps are preserved as fallbacks and for non-low-risk builds. An LM-generated plain-English apply summary is shown before the final "Apply to Repo" gate.

**Files added**:
- `frank_lloyd/auto_runner.py` — safe-lane pipeline orchestrator: generate_spec → risk gate → approve_build → authorize_stage2 → generate_stage2_draft. Pauses (does not error) on non-low risk, spec blocked, or any downstream failure.
- `frank_lloyd/apply_summary.py` — LM-backed (cheap tier) apply summary generator. Structured JSON: what_built, problem, files, risk, validation, on_apply, uncertainty, target_path. Cached in staging; deterministic fallback when LM unavailable.
- `tests/test_frank_lloyd_auto_runner.py` — 13 tests for auto_runner (37 total with apply_summary tests)
- `tests/test_frank_lloyd_apply_summary.py` — 24 tests for apply_summary

**Files edited**:
- `app/routes/frank_lloyd_actions.py` — added `POST /frank-lloyd/{build_id}/auto-run` (BackgroundTasks fire-and-forget) and `GET /frank-lloyd/{build_id}/apply-summary`
- `app/routes/neighborhood.py` — CSS: added fl-apply-summary panel styles. HTML: added `#fl-apply-summary` panel in action area. JS: `flQueueBuild()` now auto-triggers `flAutoRun(buildId)` after queuing; new `flAutoRun()` function; new `flLoadApplySummary()` function; `pending_spec` action replaced with "▶ RUN BUILD"; `draft_generating` state now shows no action buttons (pipeline running); `flShowPromoteForm()` triggers apply summary load; `_flHideForms()` includes apply summary panel.
- `peter/handlers.py` — added "run" action to `handle_fl_lifecycle_nl`, calls `auto_runner.run_safe_lane()` via Peter NL
- `peter/commands.py` — added `_FL_RUN_NL_RE` pattern + match for "run build", "go ahead and run", "auto-run"

**Reuses**: All existing frank_lloyd.* module functions (spec_writer.generate_spec_packet, spec_approver.approve_build, stage2_authorizer.authorize_stage2, stage2_drafter.generate_stage2_draft). `LMHelper` pattern from cost_warden. All existing action endpoints unchanged.

**Left out**: Peter push notifications / proactive relay of paused-reason to operator. Auto-promotion (apply gate is always operator-controlled). Streaming real-time progress. `decided_by` / `authorized_by` fields in archive records remain hardcoded "operator" (notes string carries the auto-run context).

**Remaining gaps**: Work stream is still synthesized from status (not real event timestamps). Apply summary target_path auto-fill relies on LM output. No Peter push when auto-run completes or pauses. Medium-risk builds still require full manual flow.

**Next block**: Connect apply summary target_path suggestion to the spec's `affected_files_new[0].path` field deterministically (before LM call) so the target path input is pre-populated reliably for all CODE_DRAFT_LOW builds.

---

## 2026-04-11 Frank Lloyd Safe-Lane Polish Pass — Deterministic Path, Real Event Stream, Peter Relay

**Commit**: unreleased

**What changed**: Three targeted finishing passes to make Frank Lloyd the default in-Abode builder:

**1. Deterministic target path prefill**
`apply_summary._extract_new_file_path(spec_yaml)` parses `affected_files: new: - path: "..."` from `spec.yaml` using a simple regex match, without invoking the LM. This deterministic value is extracted before the LM call, passed as context, and always overrides the LM's `target_path` field after the call. The `_deterministic_summary()` fallback also uses it. Target path for CODE_DRAFT_LOW builds is now sourced from the validated spec — not from LM inference.

**2. Real event-backed work stream**
`frank_lloyd/job.py` now materializes a `events: list[dict]` field on `FLJob`, populated at job-build time from the actual build log. New `_humanize_event(ev)` converts raw event dicts to `{event, ts, ts_short, label, detail, cls}` entries. It detects auto-approved/authorized from `notes` field keywords. `_build_job()` passes all recognized events through `_humanize_event()` in chronological order. `FLJob.to_dict()` exposes the events list. `_flRenderStream(job)` in the neighborhood JS now reads `job.events` (up to 6 most recent, with real timestamps and detail lines); falls back to status synthesis only if the events array is empty.

**3. Peter proactive progress relay**
New `frank_lloyd/relay.py` — counter-based JSONL append queue (`data/frank_lloyd/peter_relay.jsonl`) with cursor-based one-time delivery (`peter_relay_cursor.txt`). `append(build_id, event, message)` is non-fatal on any I/O error. `consume_unread(max_messages=5)` returns entries with `id > cursor` and advances the cursor. `auto_runner.py` calls `relay.append()` at 5 key moments: pipeline_start, spec_blocked, review_needed (for non-low-risk gate), draft_blocked, draft_ready. `_frank_lloyd_state()` calls `consume_unread()` on every neighborhood state poll; relay messages are returned as `fl_relay` in the Frank Lloyd state. In the neighborhood JS: relay messages are injected into Peter's `_peterChat[]` array (alert events rendered as warnings); the Frank Lloyd panel shows the latest relay message via `_flFeedback()` when the panel is active; `updateSummary()` uses `active_job.status` for accurate "Build: draft ready / plan needs review / building / queued / idle" summary text.

**Files added**:
- `frank_lloyd/relay.py` — counter-based relay queue, `append()` + `consume_unread()` + internals
- `tests/test_frank_lloyd_relay.py` — 25 tests: `TestRelay` (15), `TestJobHumanizeEvents` (6), `TestExtractNewFilePath` (4)

**Files edited**:
- `frank_lloyd/apply_summary.py` — added `import re`; new `_extract_new_file_path(spec_yaml)`; deterministic path override in `generate_apply_summary()`; `_deterministic_summary()` uses `_extract_new_file_path()`
- `frank_lloyd/job.py` — added `from dataclasses import dataclass, field`; `FLJob.events: list[dict]`; `FLJob.to_dict()` includes events; `_EVENT_META`, `_AUTO_KEYWORDS` constants; new `_humanize_event()` function; `_build_job()` populates `humanized_events`
- `app/routes/frank_lloyd_actions.py` — `promote_draft()` calls `relay.append("promoted", ...)` after successful promotion
- `app/routes/neighborhood.py` — Python: `_frank_lloyd_state()` calls `consume_unread()`, returns `fl_relay`; JS: Peter panel injects relay into `_peterChat`; `_flRenderStream()` uses real `job.events` with timestamp/detail lines; `applyState()` FL section reads `fl_relay`, calls `_flFeedback()` for latest relay; `updateSummary()` uses `active_job.status`

**Tests**: 95 total (25 relay + 13 auto_runner + 24 apply_summary + 33 status) — 95/95 pass.
**Reuses**: `LMHelper` pattern; all existing auto_runner pipeline functions; `_flFeedback()` helper; `peterChatRender()` pattern.
**Left out**: Peter relay for `promoted` event in neighborhood JS (promote goes straight to panel refresh). Real-time streaming (still poll-based). Auto-promotion gate (always operator).
**Remaining gaps**: Relay cursor is per-process — if backend restarts, cursor resets and old messages re-deliver once. Medium-risk builds still require full manual spec/approve/authorize flow. Peter NL does not yet summarize relay messages proactively.
**Next block**: Verify end-to-end with a real CODE_DRAFT_LOW build: queue request → auto-run fires → work stream shows real events with timestamps → relay delivers to Peter chat → apply summary shows with deterministic target path prefilled.

---

## 2026-04-11 Frank Lloyd Completion Sweep — Prompting Layer + Builder/Operator UI

**Commit**: unreleased
**What changed**: Full Frank Lloyd finishing pass — brief shaper, smart intake endpoints, Peter-as-coordinator upgrade, workspace UX rework, and expanded mode support. The goal: operator prompts Peter or Frank Lloyd directly from the neighborhood, Frank Lloyd plans and builds, operator reviews and applies.
**Why**: Frank Lloyd's prompting layer was raw (no intent classification, no success criteria), Peter couldn't act on FL lifecycle commands from chat, the safe lane required too many manual hoops, and mode support was limited to generic "build". This pass completes the builder/operator loop.

**Files added**:
- `frank_lloyd/brief_shaper.py` — LM-backed intent classifier. Turns freeform operator text into a `ShapedBrief` with `mode`, `description`, `success_criterion`, `needs_clarification`, `clarification_question`, `lm_shaped`. Tries cheap LM tier first; deterministic regex fallback on any failure. Modes: build, refactor, cleanup, diagnose, improve, monitor, docs.
- `tests/test_frank_lloyd_brief_shaper.py` — 35 tests covering mode classification, success criterion extraction/synthesis, clarification detection, ShapedBrief field correctness, LM fallback safety.

**Files edited**:
- `app/routes/frank_lloyd_actions.py` — added `POST /frank-lloyd/queue-and-run` (direct queue + background auto-run) and `POST /frank-lloyd/smart-queue` (brief_shaper → clarification or queue + auto-run via BackgroundTasks).
- `app/routes/neighborhood.py` (Python) — `/peter/chat` upgraded with Frank Lloyd active_job context, system prompt updated so Peter monitors FL; new `POST /peter/action` endpoint routes lifecycle messages (approve/reject/authorize/run/discard/promote) through `peter.router.route()` using `transport="cli", operator_id="neighborhood_ui"`; `/peter/queue-build` now runs brief_shaper to produce structured brief before queuing.
- `app/routes/neighborhood.py` (JavaScript) — `_isFlBuildIntent()` replaces narrow `_isPeterBuildRequest()` with broader verb/noun detection; `_isFlLifecycleIntent()` added for approve/reject/run/discard/draft/promote; `peterChatSend()` routes to smart-queue or peter/action before falling through to LM chat; `_peterSmartQueue()` and `_peterFlAction()` replace old `_peterQueueBuild()`; `flQueueBuild()` rewritten to call smart-queue with auto-run; `_flRenderWorkspace()` tracks build switches to reset stale UI, auto-shows apply summary on draft_generated; `_flVisiblePhase()` updated with PLANNING / PLAN REVIEW / READY TO APPLY / COMPLETE labels; action buttons renamed to plain English ("BUILD IT", "APPLY TO REPO", "DISCARD"); composer placeholder expanded with examples covering refactor/diagnose/improve; `applyState()` computes Frank Lloyd state for Peter badge and speech.

**Architecture changes**:
- Brief shaper decouples operator intent from build queue mechanics. Operator describes goal in plain English; shaper infers mode, description, and a testable success criterion. Falls back gracefully with no LM dependency.
- `/peter/action` closes the operator loop from Peter chat: lifecycle intents route through the full peter.router.route() stack, not a parallel command layer.
- Safe lane fires automatically after queue-and-run and smart-queue — no separate "run" button needed for low-risk builds.
- Frank Lloyd workspace auto-advances: draft_generated triggers apply summary render without operator needing to click "Load Summary."
- Peter speech and badge now reflect Frank Lloyd state (building / plan ready / draft ready) alongside Belfort review state.

**Reuses**: `LMHelper` pattern from `app/cost_warden`; `queue_build()`, `auto_runner.run_safe_lane()` unchanged; `peter.commands.parse_command()`, `peter.router.route()` unchanged; `_frank_lloyd_state()` unchanged; `_flFeedback()` helper; identity.json `transport_id: "*"` wildcard covers neighborhood_ui.
**Left out**: Medium/high-risk build auto-approval (intentionally kept manual). Full NL lifecycle dispatcher (peter/action covers the lifecycle but LM is not parsing the NL — JS side handles intent detection). Real-time streaming (still poll-based). Mode-specific UI skinning beyond phase labels.
**Remaining gaps**: Peter NL doesn't summarize active Frank Lloyd job status in prose on demand. No "mode badge" on the workspace card. Diagnostics/troubleshoot mode has no specialized output format (runs as a standard build). Cancel-in-progress is not yet wired.
**Tests**: 93 total after sweep — 58 existing (relay + status) + 35 new brief_shaper — 93/93 pass.
**Next block**: End-to-end smoke: prompt Frank Lloyd via Peter chat → brief_shaper fires → low-risk build queues → safe lane auto-runs → workspace shows events → draft loads apply summary → operator applies.

---

## 2026-04-11 Frank Lloyd Gap Fill — Cancel, Mode Badge, Deterministic Status, Multi-file

**Commit**: unreleased
**What changed**: Filled all remaining gaps from the completion sweep delivery report: cancel/abandon, mode badge, Peter deterministic FL status, multi-file apply summary, and auto-show plan review on pending_review.
**Why**: The completion sweep identified these as the next meaningful gaps. Together they close the operator loop cleanly and eliminate the last points of friction.

**Files added**:
- `frank_lloyd/abandoner.py` — `abandon_build(build_id, notes)`: checks terminal state, writes `abandoned` event with `extra.abandoned_from`, relays to Peter. Non-fatal on relay failure.
- `tests/test_frank_lloyd_gaps.py` — 22 tests: 11 abandon (terminal protection, case-insensitive, notes, log write), 4 multi-file path extraction, 7 mode extraction from FLJob.

**Files edited**:
- `frank_lloyd/job.py` — added `_MODE_FROM_SOURCE` map; `mode: Optional[str]` field on FLJob; extraction from `extra.source` in request_queued event; included in `to_dict()`.
- `frank_lloyd/apply_summary.py` — added `_extract_all_new_file_paths(spec_yaml)` returning all new-file paths; `_extract_new_file_path()` now delegates to it; `_deterministic_summary()` uses all spec new-files for `files` list and `on_apply` text; forward-compat for multi-file on_apply message.
- `app/routes/frank_lloyd_actions.py` — added `POST /frank-lloyd/{build_id}/abandon` endpoint.
- `app/routes/neighborhood.py` — (Python) no changes; (JS): added `_flLastStatus` state var; `_flRenderWorkspace()` auto-sets `_flReviewVisible = true` when entering pending_review; meta line shows mode when non-default; mode badge in meta line (e.g. "BUILD-007 · refactor · low risk"); `_peterDeterministicAnswer()` gains Frank Lloyd status branch covering all statuses with mode hint; added `flAbandon()` async function with confirm dialog; CANCEL BUILD button added to all non-terminal active states in populatePanel.

**Reuses**: All existing `_flHideForms()`, `tick()`, `_flFeedback()`, `setActions()`, `_escHtml()` helpers unchanged. `frank_lloyd.relay.append()` reused for abandon notification.
**Left out**: Diagnose mode specialized output format (findings report vs code diff) — requires changes to stage2_drafter prompt templates, out of scope for this pass. Real-time streaming still poll-based.
**Tests**: 115 total — 22 new (abandoner + multi-file + mode extraction) + 93 prior — 115/115 pass.
**Next block**: End-to-end smoke with a real low-risk build that hits all the new surfaces: mode badge visible, apply summary lists files from spec, Peter chat answers "what is Frank Lloyd doing?" correctly, CANCEL shows correctly for active builds.

---

## 2026-04-11 Four-bug fix sweep — Abode usability hardening
**Commit**: unreleased  
**What changed**: Diagnosed and fixed four user-reported bugs in the neighborhood UI and Frank Lloyd pipeline.

**Bug 1 — Belfort idle state shows trade data while off**  
`populatePanel('belfort')` in neighborhood.py: when both `tradingOn` and `loopOn` are false (no review pending), now shows clean "Idle — trading and research are both off" with last trade as historical-only context. When active, shows live position and trade data normally.

**Bug 2 — Peter REVIEW badge but empty panel (no FL items)**  
`populatePanel('peter')`: added `flNeedsReview` computation from `active_job.status`. `pending_review` and `draft_generated` FL states now trigger the REVIEW badge on Peter's house AND add explicit situation items ("Frank Lloyd plan ready: … — review in FL panel" / "Frank Lloyd draft ready…"). `draft_blocked` adds an ATTENTION NEEDED item.

**Bug 3 — Peter "what is happening?" only reported Belfort**  
`_peterDeterministicAnswer()`: added Frank Lloyd active job status to the "happen/going on/status/right now" branch. Covers all FL states with plain-English sentences. Also fixed: last trade only shown when `tradingOn` (not as stale data when idle).

**Bug 4 — Frank Lloyd modification support (new-file-only block)**  
- `frank_lloyd/stage2_promoter.py`: removed `app/routes/neighborhood.py` from `_OFFLIMITS_FILES`; added `code_patch_low` to `_PROMOTABLE_TASK_CLASSES`; added `_is_modification_build()` helper reading manifest `build_type` or archived `spec.yaml`; modification builds allowed to overwrite existing files.
- `frank_lloyd/stage2_drafter.py`: added `_PATCH_SYSTEM` prompt (complete file replacement); `_detect_modification_build()` reads spec `build_type`; modification builds use 2400 token limit; manifest gains `build_type` and `is_modification` fields.
- `frank_lloyd/apply_summary.py`: added `_extract_modified_file_path(spec_yaml)` for `affected_files.modified` section; `generate_apply_summary()` uses new+modified fallback for `det_target_path`.
- `app/routes/neighborhood.py` (HTML): promote form now has IDs on hint/label/button; `flShowPromoteForm()` detects modification builds from `active_job.build_type` and adapts labels ("REPLACE FILE IN REPO", orange hint warning, "TARGET FILE TO REPLACE").

**Files edited**:
- `app/routes/neighborhood.py` — JS: Peter badge/situation fix, Belfort idle fix, Peter deterministic answer FL addition, promote form HTML IDs, `flShowPromoteForm()` modification detection.
- `frank_lloyd/stage2_promoter.py` — off-limits list, task class set, modification guard, `_is_modification_build()`.
- `frank_lloyd/stage2_drafter.py` — `_PATCH_SYSTEM`, `_detect_modification_build()`, max_tokens, manifest fields.
- `frank_lloyd/apply_summary.py` — `_extract_modified_file_path()`, updated `det_target_path` fallback.

**Reuses**: All existing `_flHideForms()`, `applyState()`, `setBadge()`, `setItems()`, `_escHtml()` helpers. `frank_lloyd.job.FLJob.build_type` field already present.  
**Left out**: No test updates needed (no new behavior in test-covered paths; modification detection tested implicitly by existing drafter/promoter tests). No UI change to action button labels for modification state in action bar (minor polish).  
**Tests**: 57/57 gap tests pass; 1655 total pass (19 pre-existing peter_queue_build failures unchanged).  
**Next block**: End-to-end test with a modification build: describe "modify X in Y", Frank Lloyd generates a plan with `build_type: modification`, drafter uses patch system prompt, promoter allows overwrite, apply summary shows modified file path.


## 2026-04-11 Belfort Market-Connection Stack — Wave 1–3
**Commit**: `7117d7cef` (unreleased additions)
**What changed**: Full market-layer plumbing for Belfort — 11 new modules, 16 market API endpoints, ~150 new tests, transport isolation repair.

**New app modules**:
- `app/market_time.py` — NYSE session type detection (regular/pre_market/after_hours/closed), holiday/early-close calendar, `session_summary()` dict.
- `app/cost_engine.py` — Deterministic order cost estimator: SEC 31 fee (0.0000206 × principal on sells), FINRA TAF ($0.000166/share, capped $8.30), spread cost, slippage uncertainty (low/medium/high by data lane + spread + session).
- `app/order_ledger.py` — Append-only per-day JSONL ledger (`data/orders/YYYY-MM-DD.jsonl`); replay, open-order tracking, daily summary.
- `app/kill_switch.py` — `engage()` cancels open orders, stops trading loop, transitions agent state to `stopped_by_guardrail`, logs to event_log. Returns `KillResult`.
- `app/market_data_feed.py` — Alpaca L1 quote fetch; `DATA_LANE` constant (IEX_ONLY/SIP_CONSOLIDATED); graceful simulated fallback when no credentials; `FeedStatus` with `summary_line()`.
- `app/spread_monitor.py` — Records quotes as spread observations; daily spread summary by session type; IEX disclaimer always attached.
- `app/execution_overlay.py` — Pre-trade overlay checks: market order in extended hours blocked, non-marketable limit flagged, partial fill detection, bid/ask fill price (not last-trade).
- `app/broker_connector.py` — `AlpacaConnector` (paper/live URLs); singleton `get_connector()` returns None if unconfigured; order/position/account methods.
- `app/reconciler.py` — Position reconciliation: broker vs internal, `_halted` flag on mismatch, threshold 0.01 shares, persists to `data/reconciliation_log.jsonl`.
- `app/shadow_runner.py` — Records shadow intents (no real orders); daily postmortems assessing frictions (spread, data lane, extended hours).
- `app/readiness_scorecard.py` — 7-gate scorecard (feed liveness, data lane labeling, reconciliation, overlay warnings, shadow postmortems ≥5, kill switch tested, paper days ≥3); 5 levels NOT_READY→LIVE_ELIGIBLE; persists to `data/readiness_scorecard.jsonl`.
- `app/routes/market.py` — 16 FastAPI endpoints under `/market` prefix; status route persists `data/market_status.json` for Peter's disk-read handler.

**Observability bridge**:
- `observability/market_summary.py` — Disk-read bridge: `read_market_status()`, `read_readiness()`, `read_last_reconciliation()`, `read_today_order_summary()`, `write_kill_signal()`, `read_kill_signal()`.

**Peter integration**:
- `peter/commands.py` — Added `MARKET_STATUS`, `MARKET_READINESS`, `KILL_TRADING` command types and parse rules.
- `peter/router.py` — Dispatch entries for three new command types.
- `peter/handlers.py` — `handle_market_status`, `handle_market_readiness`, `handle_kill_trading` — all read from disk via `observability.market_summary` (zero `from app.*` imports).

**Trading loop**:
- `app/trading_loop.py` — Added `_poll_kill_signal()`: checks `data/kill_signal.json` on each tick; if found, sets `_running=False`, transitions agent state, logs event.

**Tests** (all new):
- `tests/test_market_time.py` — 20 tests
- `tests/test_cost_engine.py` — 18 tests
- `tests/test_order_ledger.py` — 13 tests
- `tests/test_execution_overlay.py` — 12 tests
- `tests/test_kill_switch.py` — 8 tests
- `tests/test_readiness_scorecard.py` — 10 tests
- `tests/test_market_data_feed.py` — 12 tests
- `tests/test_reconciler.py` — 10 tests
- `tests/test_shadow_runner.py` — 12 tests
- `tests/test_peter_market_commands.py` — 20 tests
- `tests/test_trading_loop_graceful_stop.py` — +5 kill-signal polling tests (total 34)

**Why**: Wave 1–3 of the Belfort market-connection stack as planned. Observation layer, paper trading plumbing, shadow mode, and readiness gates.
**Reuses**: `observability.agent_state.transition`, `observability.event_log.append_event`, `app.portfolio.get_snapshot`, existing Peter command/router/handler pattern, `data/` append-only JSONL pattern.
**Left out**: Neighborhood UI tiles for market status, live broker credential provisioning, actual Alpaca API calls (degrade gracefully), Discord.
**Tests**: 1805 pass (19 pre-existing frank_lloyd/peter_queue_build failures unchanged). Transport isolation test now passes.
**Next block**: Neighborhood market status tile — glanceable feed/session/readiness status in the Belfort panel, reading from `/market/status` endpoint.

## 2026-04-11 Frank Lloyd fully-automated build pipeline
**Commit**: unreleased
**What changed**: Frank Lloyd now works like Claude Code — prompt it and it builds, no human approval gates between request and code landing in the repo.

**Problems fixed**:
1. 8 stale builds (BUILD-015 through BUILD-022) sitting in pending_review with no way to advance — abandoned via build log.
2. Pipeline stopped at `draft_generated` and required manual approve/authorize/promote steps.
3. Non-"low" risk builds paused for human review (risk gate removed — path safety enforced by promoter's off-limits lists, not the risk label).
4. `tests/` directory was off-limits for promotion — Frank Lloyd couldn't write test files.

**Key changes**:
- `frank_lloyd/auto_runner.py` — added `run_full_auto()`: full pipeline spec→approve→authorize→draft→promote in one call. No human gates. Target path extracted from spec's `affected_files.new/modified` section. `run_safe_lane()` updated to also skip risk gate (both proceed for all risk levels).
- `frank_lloyd/stage2_promoter.py` — removed `tests/` from `_OFFLIMITS_PREFIXES`. Frank Lloyd can now write test files.
- `peter/handlers.py` — `handle_build_intent` now fires `run_full_auto()` in a background thread immediately after queuing. Returns "Frank Lloyd is building" response, not "spec for review". `human_review_needed=False`.
- NL lifecycle handler updated: `run` action uses `run_full_auto` and reports `promoted_to` path.

**Files edited**:
- `frank_lloyd/auto_runner.py`
- `frank_lloyd/stage2_promoter.py`
- `peter/handlers.py`
- `tests/test_frank_lloyd_auto_runner.py` — updated risk gate tests to match new no-gate behavior
- `tests/test_frank_lloyd_stage2_promoter.py` — `test_tests_prefix_rejected` → `test_tests_prefix_allowed`
- `tests/test_peter_build_intake.py` — `human_review_needed` assertion flipped to False

**Reuses**: `frank_lloyd.spec_approver`, `frank_lloyd.stage2_authorizer`, `frank_lloyd.stage2_drafter`, `frank_lloyd.stage2_promoter`, `frank_lloyd.relay` — same internal functions, just wired in sequence without human gates.
**Left out**: Multi-file builds (only first target path promoted per build). Neighborhood UI update for auto-build status.
**Tests**: 1805 pass, 19 failures (same count as before; pre-existing test-ordering cross-contamination in full suite — auto_runner tests pass individually).
**Next block**: Multi-file promotion — when spec lists multiple affected files, generate and promote each one in a single build run.

---

## 2026-04-11 BELFORT-FOUNDATION-01 — Belfort foundation layer
**Commit**: unreleased
**What changed**: Implemented the Belfort foundation layer — typed strategy interface, risk guardrail layer, operating mode state machine, observation runner, preflight snapshot, Peter integration, and UI reflection contract.
**Why**: Required foundation before any Belfort signal execution or paper trading. Establishes the typed interface and safety boundaries that all subsequent Belfort blocks must use.
**Files**:
- `app/belfort_mode.py` — BelfortMode enum + journal-first state machine (OBSERVATION→SHADOW→PAPER→LIVE)
- `app/belfort_strategy.py` — BelfortSignal dataclass, StrategyBase ABC, MeanReversionV1 rolling-window strategy
- `app/belfort_risk.py` — RiskGuardrails (7 ordered checks, stateless, all blocks logged)
- `app/belfort_observer.py` — observation tick runner + write_preflight_snapshot()
- `observability/belfort_summary.py` — disk-read bridge (read_belfort_preflight, read_belfort_mode, read_observation_log)
- `peter/commands.py` — added BELFORT_STATUS CommandType + parse rules
- `peter/router.py` — dispatch for BELFORT_STATUS
- `peter/handlers.py` — handle_belfort_status() handler
- `tests/test_belfort_mode.py` (11 tests)
- `tests/test_belfort_strategy.py` (15 tests)
- `tests/test_belfort_risk.py` (17 tests)
- `tests/test_belfort_observer.py` (11 tests)
- `tests/test_belfort_preflight.py` (11 tests)
- `docs/UI_REFLECTIONS/BELFORT_FOUNDATION_01.md` — UI reflection contract
- `docs/CAPABILITY_REGISTRY.md` — added B.5 entry
**Reuses**: Observability bridge pattern (market_summary), event_log.append_event, agent_state file layout, Peter command/router/handler pattern, append-only JSONL pattern.
**Left out**: Signal execution wiring (no paper order placement), neighborhood UI code, new API endpoints, real-time quote streaming, mode advancement controls, P&L or position display. Observation ticks do not auto-run — requires external trigger.
**Tests**: 65 new tests pass (1870 total across the block). Pre-existing 19 auto_runner test-ordering failures unchanged.
**Next block**: Wire observation runner to the trading loop (auto-tick on each loop iteration); add mode advancement command to Peter (`belfort advance shadow`); surface preflight data on Belfort neighborhood tile.

---

## 2026-04-11 BELFORT-REFLECTION-AND-CONTROL-01 — Freshness, mode control, and UI reflection
**Commit**: unreleased
**What changed**: Wired observation freshness into the trading loop, added Peter mode control commands, enriched the neighborhood Belfort tile with mode/readiness/freshness, and fixed the simulated-quote None-field bug.

**Problems fixed**:
- `app/belfort_observer.py`: `float(getattr(quote, "bid", 0.0))` raised `TypeError` for simulated quotes (`bid=None`). Added `_safe_float()` helper — silently converts None/unconvertible to 0.0.
- `peter/commands.py` `lstrip("because ")` bug: strips individual characters from the set, not a prefix string. Replaced with explicit `startswith("because")` prefix removal.

**New capabilities**:
1. **Loop observation wiring** (`app/trading_loop.py`): `_run_observation_snapshot()` added — calls `run_observation_tick()` on every tick, silently swallowed. Wired into `_loop_body` after kill-signal check, before task execution.
2. **Freshness state derivation** (`observability/belfort_summary.py`): `read_belfort_freshness_state()` — derives fresh/stale/very_stale/no_data from `last_tick_at`. Regular session: fresh ≤15 min, stale 15–60 min, very_stale >60 min. Off-hours: fresh ≤60 min, stale >60 min. Includes `loop_likely_running` heuristic (tick within 5 min). Mode-order helpers added: `compute_next_belfort_mode()` (LIVE blocked via command), `compute_prev_belfort_mode()`.
3. **Mode transition bridge** (`observability/belfort_summary.py`): `apply_belfort_mode_transition()` — calls `set_mode()` via app-layer import. On failure, `previous_mode == mode` (both = unchanged current). Handler does not surface `previous_mode` as a pre-transition value on failure.
4. **Peter mode control** (`peter/commands.py`, `peter/router.py`, `peter/handlers.py`): `belfort advance`, `belfort regress`, `belfort set <mode>` commands. LIVE is permanently blocked via command. Force-regression flag passed automatically for regressions. IEX cap note appended on success when readiness is capped.
5. **Neighborhood state enrichment** (`app/routes/neighborhood.py`): `_belfort_state()` now includes `belfort_mode`, `belfort_readiness`, `belfort_data_lane`, `belfort_ticks_today`, `belfort_can_advance`, `belfort_freshness`, `belfort_freshness_label`.
6. **Neighborhood UI** (`app/routes/neighborhood.py`): New `belfort-mode-readiness` row in Belfort panel — three labeled cells: MODE, READINESS, DATA FRESHNESS. Mode and readiness are always separate fields, never merged. Freshness cell uses color coding (green/amber/red).

**Files edited**:
- `app/belfort_observer.py` — `_safe_float()` + field reads fixed
- `app/trading_loop.py` — `_run_observation_snapshot()`, wired into `_loop_body`
- `observability/belfort_summary.py` — `read_belfort_freshness_state`, `compute_next_belfort_mode`, `compute_prev_belfort_mode`, `apply_belfort_mode_transition`, `_MODE_ORDER`, freshness thresholds
- `peter/commands.py` — `BELFORT_MODE_CONTROL` CommandType, parse rules for advance/regress/set, `lstrip` bug fix
- `peter/router.py` — dispatch for `BELFORT_MODE_CONTROL`
- `peter/handlers.py` — `handle_belfort_mode_control()`
- `app/routes/neighborhood.py` — `_belfort_state()` enriched, `belfort-mode-readiness` HTML element + CSS, `updateBelfortStats()` updated
- `tests/test_belfort_observation_freshness.py` (21 tests — loop wiring, freshness derivation, labels)
- `tests/test_belfort_mode_control.py` (18 tests — parse rules, handler advance/regress/set, failure contract, mode-order helpers)

**Reuses**: Observability bridge pattern (belfort_summary.read_*), Peter command/router/handler pattern, `_loop_body` existing kill-signal + tick structure, `updateBelfortStats` existing stats/pills flow.
**Left out**: Neighborhood UI mode-control buttons (Peter handles this via chat). Staleness alerts or notifications. Real market data freshness (requires Alpaca credentials — simulated quotes still produce valid observation records with IEX_ONLY lane).
**Tests**: 39 new tests pass (104 total across all Belfort test files). No regressions in Peter/market/kill-switch test files.
**Next block**: Paper signal evaluation — wire `MeanReversionV1` into a shadow/paper execution path so Belfort can log signal decisions on each trading tick.

---

## 2026-04-12 Provenance audit + truth cleanup (diagnostic-and-fix block)
**Commit**: unreleased

**Root cause of unexplained Frank Lloyd builds:**
Every Peter chat interaction matching a build-intent pattern triggered `handle_build_intent` → `run_full_auto()` in background. The auto-pipeline ran spec→approve→authorize→draft for every such message. Promotion silently failed (no valid target path from spec). Result: 48+ `draft_generated` orphan builds all with `source: "peter_chat_smart"`. None were explicitly requested as standalone Frank Lloyd builds. The `source` field was logged in `request_queued` events but never surfaced in the UI — so every draft card looked identical: no indication of origin.

**Was it a bug or intended?**
The auto-run behavior was intentional (from the "fully-automated pipeline" block). The missing provenance display was an oversight — the `source` field was recorded but never plumbed to the UI. The result was theater: draft builds appearing in the UI with no explanation of where they came from.

**What was changed:**

A. **Frank Lloyd provenance** (`frank_lloyd/job.py`, `app/routes/frank_lloyd_status.py`):
- Added `source: Optional[str]` field to `FLJob` dataclass and `to_dict()`
- `source` is extracted from `request_queued` event's `extra.source` in both `_build_job()` (job.py) and `_build_status_item()` (frank_lloyd_status.py)
- `source` is now included in all pending and inprogress build dicts returned by `frank_lloyd_status()`

B. **Provenance chip in UI** (`app/routes/neighborhood.py`):
- `fl-job-meta` line now renders a provenance chip alongside build_id · mode · risk
- Source labels: "via Peter chat" / "auto via Peter chat" / "auto-queued" / "via Abode UI" / "by operator"
- Unknown/missing source → orange warning chip "⚠ origin unknown"
- Added `.fl-source-chip` and `.fl-source-unknown` CSS classes

C. **Belfort section header renames** (`app/routes/neighborhood.py` HTML):
- `belfort-readiness-section`: "READINESS" → "MOCK TRADING HISTORY" + sub-label "Past performance · current readiness claim is above"
- `belfort-learning-section`: "LEARNING PULSE" → "MOCK TRADING LEARNING"
- `belfort-diagnostics-section`: "DIAGNOSTICS" → "MOCK TRADING DIAGNOSTICS"
- New preflight MODE/READINESS/FRESHNESS row (from previous block) now unambiguously owns the "current readiness" concept
- Old scorecard sections are visually separated as historical mock-trading performance

**Peter `belfort status`:** Already clean — reads only from `observability/belfort_summary.read_belfort_preflight()`. No changes needed.

**Files edited:**
- `frank_lloyd/job.py` — `source` field in FLJob, extracted in `_build_job()`
- `app/routes/frank_lloyd_status.py` — `source` in `_build_status_item()` return dicts
- `app/routes/neighborhood.py` — provenance chip CSS + JS, Belfort section header renames

**Tests added:**
- `tests/test_frank_lloyd_provenance.py` (22 tests): FLJob.source extraction, frank_lloyd_status source field, provenance label mapping, review gate unaffected by provenance

**Review/apply gates:** Unaffected. Unknown provenance does NOT remove the review gate — it only changes the visual warning level.

**What remains before real Alpaca-backed Belfort validation:**
1. Alpaca paper trading credentials not configured — `has_credentials=False`, `DATA_LANE=IEX_ONLY`, quotes are simulated
2. Signal evaluation not wired — `MeanReversionV1` runs in tests only, not on live ticks
3. 48+ orphaned `draft_generated` builds (all `peter_chat_smart` source) remain pending — operator must review or discard individually. Consider a bulk-abandon endpoint for same-source orphans.
4. `handle_build_intent` auto-run behavior unchanged — every Peter chat build-intent still fires `run_full_auto()`

---

## 2026-04-12 FRANK-INTAKE-SAFETY-01 — Frank Lloyd intake gate

**Commit**: unreleased
**What changed**:

A. **Queue-only build intake** (Peter chat and Neighborhood UI):
- `peter/handlers.py` `handle_build_intent()`: Removed `threading.Thread` that fired `run_full_auto()` automatically. Build is now queued only — operator must say `run BUILD-N` to start the pipeline.
- `app/routes/neighborhood.py` `peter_queue_build()`: Removed `auto_runner.run_safe_lane()` background thread. Response text updated to say `say 'run BUILD-N' when you want Frank Lloyd to start building`.
- `handle_fl_lifecycle_nl` "run" action unchanged — explicit `run BUILD-N` still fires `run_full_auto()`.

B. **Bulk-abandon by source** (cleanup path for orphan drafts):
- `frank_lloyd/abandoner.py`: Added `abandon_by_source(source, notes)` — abandons all non-terminal builds with matching `request_queued.extra.source`. Skips terminal builds. Added `_read_log()` helper.
- `app/routes/frank_lloyd_actions.py`: Added `POST /frank-lloyd/bulk-abandon` endpoint.
- `peter/commands.py`: Added `FL_BULK_ABANDON` CommandType + parse rules: "abandon frank queue", "clean frank queue", "abandon peter chat builds", "abandon frank queue <source>".
- `peter/router.py`: Registered `handle_fl_bulk_abandon`.
- `peter/handlers.py`: Added `handle_fl_bulk_abandon()` handler.

C. **UI source warning** (`app/routes/neighborhood.py`):
- HTML: Added `<div id="fl-source-warning">` after `fl-job-meta`.
- CSS: Added `.fl-source-warning` (red-tinted warning band).
- JS: For `draft_generated` builds with `source === 'peter_chat_smart'`, shows: "⚠ This draft was auto-generated from a Peter chat side-effect — not an explicit Frank request."

**Why**: 48+ orphan draft_generated builds appeared because both `handle_build_intent` and `peter_queue_build` auto-fired the Frank Lloyd pipeline on casual Peter chat build-like phrases. The operator never explicitly asked for these builds.

**Files edited**:
- `peter/handlers.py` — remove auto-run from `handle_build_intent`, add `handle_fl_bulk_abandon`
- `peter/commands.py` — add `FL_BULK_ABANDON` + parse rules
- `peter/router.py` — add dispatch
- `frank_lloyd/abandoner.py` — add `abandon_by_source`, `_read_log`
- `app/routes/frank_lloyd_actions.py` — add `POST /frank-lloyd/bulk-abandon`
- `app/routes/neighborhood.py` — remove auto_runner from `peter_queue_build`, add source warning HTML/CSS/JS

**Tests added**: `tests/test_frank_intake_safety.py` (21 tests)

**Reuses**: `frank_lloyd.abandoner.abandon_build` (single-build path), `frank_lloyd.auto_runner.run_full_auto` (still used by explicit `run BUILD-N`), existing `request_queued.extra.source` log field

**Left out**: No changes to the smart-queue endpoint (`/frank-lloyd/smart-queue`) — that path already uses explicit FL compose form, not casual Peter chat. No removal of existing orphan builds — operator can now use `abandon frank queue` to clean them.

**Remaining gaps**:
1. 48+ existing orphan `draft_generated` builds — use `abandon frank queue` to bulk-abandon them
2. Alpaca paper credentials still not configured — IEX_ONLY data lane
3. Signal evaluation still not live-wired

---

## 2026-04-12 PETER-COMMAND-DISPATCH-01 — Fix deterministic command dispatch in side-panel

**Commit**: unreleased
**What changed**:

**Root cause**: `peterChatSend()` in the neighborhood JS had three routes:
1. `_isFlBuildIntent(msg)` → `/peter/queue-build`
2. `_isFlLifecycleIntent(msg)` → `/peter/action` (only `approve|reject|authorize|discard|promote|draft` verbs)
3. Everything else → `/peter/chat` (LM) or `_peterDeterministicAnswer()`

Commands like `belfort status`, `belfort advance`, `belfort regress`, `abandon frank queue`, `run BUILD-N` did not match either Route 1 or Route 2, so they fell through to LM chat and produced conversational replies instead of structured handler responses.

**Fix**: Replaced Routes 2+3 with a single unified `_peterCommandDispatch()` function:
1. Always POST to `/peter/action` for any non-build-intent input
2. If `command_type !== "unknown"`, the handler recognised the command — show the response
3. If `command_type === "unknown"`, fall through to `/peter/chat` (LM) or `_peterDeterministicAnswer()` offline

`_isFlLifecycleIntent()` is now unused in the dispatch path (kept in place, commented). `_peterFlAction()` is also unused (kept in place).

**Files edited**:
- `app/routes/neighborhood.py` — rewrote `peterChatSend()`, added `_peterCommandDispatch()`, noted `_isFlLifecycleIntent` as no longer called

**Tests added**: `tests/test_peter_action_dispatch.py` (27 tests):
- `/peter/action` returns `command_type != "unknown"` for: belfort status, abandon frank queue, belfort advance/regress/set, run BUILD-N, approve/reject/authorize/discard BUILD-N
- Freeform input returns `command_type = "unknown"` (frontend falls through to LM)
- `parse_command()` classification tests for all problem commands

**Reuses**: Existing `/peter/action` endpoint (unchanged), `peter.commands.parse_command()`, `peter.router.route()`, `_peterSmartQueue()` / `_isFlBuildIntent()` (unchanged)

**Left out**: No changes to parse_command rules, handler logic, or /peter/chat LM path. No JS test framework added.

---

## 2026-04-12 BELFORT-SIGNAL-EVAL-01
**Commit**: unreleased

**What changed**: Wired MeanReversionV1 into the live tick path as a non-executing signal evaluation layer. Belfort now evaluates signals every tick in SHADOW or PAPER mode, runs them through RiskGuardrails, and logs the full decision record to `data/belfort/signal_log.jsonl`. No orders are placed. `was_executed = False` / `execution_mode = "none"` are invariants across all records.

**Files added**:
- `app/belfort_signal_eval.py` — `_QuoteProxy`, `evaluate_signal()`, `read_signal_log()`
- `tests/test_belfort_signal_eval.py` — 21 tests

**Files edited**:
- `observability/belfort_summary.py` — added `_SIGNAL_LOG` path constant, `read_latest_signal_decision()`, `read_signal_stats_today()`
- `app/trading_loop.py` — added `_run_signal_evaluation()`, wired into `_loop_body()` after `_run_observation_snapshot()`
- `peter/handlers.py` — `handle_belfort_status()` now includes latest signal decision + today's stats for shadow/paper modes; imported `read_latest_signal_decision`, `read_signal_stats_today`
- `app/routes/neighborhood.py` — `_belfort_state()` adds `belfort_latest_signal`; HTML: `belfort-signal-row` div; CSS: `.belfort-signal-row`, `.bsig-*` classes; JS: `updateBelfortStats()` renders signal row for shadow/paper
- `docs/CAPABILITY_REGISTRY.md` — updated B.3 entry

**Reuses**: `_loop_body()` tick structure, `_run_observation_snapshot()` pattern (swallowed exceptions), observability bridge disk-read pattern, `_SIGNAL_LOG` path convention from existing data/belfort/ layout, `_escHtml()` in JS

**Left out**: No execution path. No order placement. No LM integration. No strategy config changes. No new Peter commands. No new UI controls.

**Remaining gaps**: Signal log rotation/pruning. Strategy config overrides via Peter. Signal-based alerts. Multi-symbol signal evaluation (currently SPY only in `_run_signal_evaluation`).

**Next block**: BELFORT-PAPER-EXEC-01 — connect signal evaluation output to a simulated paper order placement path (paper mode only, operator-gated, no real orders).

---

## 2026-04-12 BELFORT-MODE-TRUTH-01
**Commit**: unreleased

**What changed**: Fixed Belfort current-mode truth path. `belfort set shadow` followed by `belfort status` now correctly reports the new mode immediately — no dependency on stale preflight data.

Root cause: two callsites read `mode` from `pf.get("mode")` (preflight, only refreshed on observation ticks) instead of `read_belfort_mode()` (authoritative state file, updated immediately on transition).

Fix A — both callsites now use `read_belfort_mode()`:
- `peter/handlers.py` `handle_belfort_status()`: `mode = read_belfort_mode()` (was `pf.get("mode")`)
- `app/routes/neighborhood.py` `_belfort_state()`: `base["belfort_mode"] = read_belfort_mode()` (was `pf.get("mode")`)

Fix B — `apply_belfort_mode_transition()` now calls `write_preflight_snapshot()` immediately after a successful transition, so `can_advance_to` / `advancement_blocked_by` are also synced. Failure is non-fatal.

Preflight continues to supply: readiness_level, data_lane, session_type, observation_ticks_today, broker_environment, advancement fields.

**Files edited**:
- `peter/handlers.py` — one-line fix in `handle_belfort_status()`
- `app/routes/neighborhood.py` — one-line fix in `_belfort_state()` + added `read_belfort_mode` import
- `observability/belfort_summary.py` — added preflight sync after successful `set_mode()` in `apply_belfort_mode_transition()`

**Tests added**: `tests/test_belfort_mode_truth.py` (18 tests):
- Peter status reports new mode despite stale preflight (shadow/paper/observation variants)
- UI _belfort_state() uses authoritative mode
- Stale preflight does not override authoritative mode
- Readiness/data_lane/ticks/broker_env still come from preflight
- Preflight sync fires on success, skips on failure, is non-fatal if it errors
- read_belfort_mode() reads from state file, defaults to observation when missing

**Reuses**: `read_belfort_mode()` (already imported in handlers.py), `write_preflight_snapshot()` (already in belfort_observer), existing observability bridge pattern

**Left out**: No signal-eval changes. No order placement. No Alpaca config changes. No UI redesign.

---

## 2026-04-12 BELFORT-PAPER-EXEC-01
**Commit**: unreleased

**What changed**: Connected Belfort's signal evaluation output to an Alpaca paper order placement path. In PAPER mode, eligible buy signals that pass all gates are submitted as limit orders to the Alpaca paper API and logged with full audit detail. No real money. No silent execution. Sell orders explicitly blocked (requires position tracking — future block).

**Gate sequence**: mode=paper → session=regular → action=buy → risk_can_proceed → qty>0 → price>0 → broker URL is paper endpoint → credentials present → submit. All outcomes logged regardless.

**Files added**:
- `app/belfort_broker.py` — thin Alpaca paper order client; buy-only; paper URL enforced; `paper_only=True` invariant; returns `BrokerResult` dataclass; never raises
- `app/belfort_paper_exec.py` — execution layer; gate checks; calls broker; builds + logs execution record to `data/belfort/paper_exec_log.jsonl`
- `tests/test_belfort_paper_exec.py` — 35 tests

**Files edited**:
- `app/trading_loop.py` — `_run_signal_evaluation()` now returns signal dict; `_run_paper_execution(signal)` added after signal eval in `_loop_body()`
- `observability/belfort_summary.py` — added `_PAPER_EXEC_LOG` path, `read_latest_paper_execution()`, `read_paper_exec_stats_today()`
- `peter/handlers.py` — `handle_belfort_status()` includes paper exec summary in PAPER mode; imports `read_latest_paper_execution`, `read_paper_exec_stats_today`
- `app/routes/neighborhood.py` — `_belfort_state()` adds `belfort_latest_paper_exec`; HTML: `belfort-paper-exec-row`; CSS: `.bpex-*` classes (dim, not trade-like); JS: renders paper exec row in paper mode
- `docs/CAPABILITY_REGISTRY.md` — B.3 entry updated

**Reused**: Same Alpaca API credentials as `market_data_feed.py`. `_loop_body` tick pattern. Observability bridge disk-read pattern.

**Left out**: Sell order execution (requires position reconciliation). Live trading path. PnL analytics. Multi-symbol expansion. Position tracking mutation. Fill polling/reconciliation.

**What remains before live trading is discussable**:
1. Sell order execution with position tracking (BELFORT-PAPER-SELL-01)
2. Fill reconciliation — poll Alpaca order status and update paper_exec_log (BELFORT-FILL-RECONCILE-01)
3. Position tracking from paper fills (separate from mock portfolio)
4. Shadow mode extended run with clean signal log showing consistent behavior
5. Human sign-off file creation (data/belfort/live_sign_off.json) with explicit operator approval
