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

*To add a new entry: copy the format block above, fill in the fields, append at the bottom.*  
*Keep entries factual. The why and left-out fields matter most for future context.*
