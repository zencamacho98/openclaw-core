# Capability Registry — The Abode
*Last updated: 2026-04-12 (BELFORT-TRADE-AND-LEARN-01)*

This registry is an inventory of all live capabilities in the system. Capabilities are organized by category:

- **Housed capabilities** — owned by a named house (Peter, Belfort). These are the product.
- **Backstage operating services** — infrastructure that keeps the system healthy, safe, and cost-efficient. Not houses.
- **Reusable platform capabilities** — cross-cutting infrastructure intended for reuse across houses.

---

## How to read this registry

**Status**: `live` | `partial` | `planned`  
**Category**: `house` | `operating_service` | `platform`  
**Maturity**: `prototype` | `stable`  
**Autonomy**: `supervised` | `partial`  
**Outcome type**: `revenue` | `force_multiplier` | `governance` | `reliability` | `infrastructure`

---

---

# A. Housed Capabilities

---

## A.0 Frank Lloyd — Workforce construction house

**Category**: house | **Maturity**: early (operator loop live) | **Autonomy**: supervised | **Outcome type**: force_multiplier

Frank Lloyd owns the construction, modification, duplication, and evolution of agents and houses inside the Abode. It is the mechanism by which the workforce can grow itself rather than requiring all construction work to happen outside the system.

**Status: OPERATIONAL — Full-auto pipeline active. Operator talks to Peter; Peter queues and auto-starts immediately via daemon thread; Frank Lloyd plans, drafts, and promotes. Safe text targets (.md/.yaml/.yml/.json/.txt/.rst) supported in addition to .py. Source-based execution policy: Abode-native sources → auto_apply; external → review_required.**

### A.0.1 Brief shaper (intent classifier)
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Turns freeform operator intent into a structured build brief with mode, description, and testable success criterion |
| Technical description | LM-backed (cheap tier via LMHelper) with deterministic regex fallback. Modes: build, refactor, cleanup, diagnose, improve, monitor, docs. Returns `ShapedBrief`; sets `needs_clarification` when input is too vague. |
| Code location | `frank_lloyd/brief_shaper.py` |
| Reuse | `app/cost_warden.LMHelper` |

### A.0.2 Smart queue intake
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Accepts freeform operator text, shapes it into a brief, queues the build, and fires the full-auto pipeline |
| Technical description | `POST /frank-lloyd/smart-queue` → brief_shaper.shape() → if needs_clarification return question → queue_build() + BackgroundTask(run_full_auto). Also available as `POST /frank-lloyd/queue-and-run` for pre-shaped briefs. All builds get `execution_policy: "auto_apply"` in the request file. |
| Code location | `app/routes/frank_lloyd_actions.py` |
| Reuse | `frank_lloyd.request_writer.queue_build()`, `frank_lloyd.auto_runner.run_full_auto()` |

### A.0.3 Full-auto build pipeline
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Fully automatic plan → build → apply pipeline. Normal safe builds queue, plan, draft, and promote to the repo with no manual gates. Peter relay reports the outcome. |
| Technical description | `auto_runner.run_full_auto()`: spec_gen → spec_approved (auto) → stage2_authorized (auto) → draft_gen → auto_promote. Pauses with relay message if spec is blocked or no target path found in spec. `execution_policy: "auto_apply"` written to all operator-queued request files. Legacy `run_safe_lane()` kept for backward compatibility but no longer called by any intake endpoint. |
| Code location | `frank_lloyd/auto_runner.py`, `frank_lloyd/request_writer.py`, `frank_lloyd/job.py` |
| Reuse | `frank_lloyd/spec_writer.py`, `frank_lloyd/draft_writer.py`, `frank_lloyd/relay.py` |

### A.0.3a Legacy orphan cleanup
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Bulk-abandon `draft_generated` builds with no `execution_policy` — created before the auto-apply policy; would otherwise sit in the Frank panel indefinitely |
| Technical description | `POST /frank-lloyd/cleanup-orphans` → reads `list_jobs()`, filters `status==draft_generated AND execution_policy is None`, calls `abandon_build()` for each |
| Code location | `app/routes/frank_lloyd_actions.py` |
| Reuse | `frank_lloyd.abandoner.abandon_build()`, `frank_lloyd.job.list_jobs()` |

### A.0.4 Build log + FLJob view
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Append-only record of every build lifecycle event; unified job view with humanized event timeline |
| Technical description | `data/frank_lloyd/build_log.jsonl`; `frank_lloyd/job.py` produces `FLJob` with `events: list[dict]` containing humanized labels, timestamps, cls (ok/review/warn/blocked), auto-approval detection |
| Code location | `frank_lloyd/job.py`, `data/frank_lloyd/build_log.jsonl` |
| Reuse | `observability/event_log.py` pattern |

### A.0.5 Apply summary and promotion
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Plain-English summary of what the draft will change before any code is applied; operator-confirmed promotion to live repo |
| Technical description | `frank_lloyd/apply_summary.py` generates summary with deterministic target-path extraction from spec. `POST /frank-lloyd/promote/{build_id}` applies draft. Workspace auto-loads summary on draft_generated. |
| Code location | `frank_lloyd/apply_summary.py`, `app/routes/frank_lloyd_actions.py` |
| Reuse | `frank_lloyd/relay.py` (relay append on promotion) |

### A.0.6 Peter relay queue
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Frank Lloyd → Peter progress messages delivered automatically in Peter's chat panel; operator sees build start, completion, and failure without opening the Frank panel |
| Technical description | Append-only JSONL + cursor in `data/frank_lloyd/`. `relay.append()` at all pipeline moments: `pipeline_start`, `spec_blocked`, `draft_blocked`, `draft_ready`, `promote_failed`, `build_complete`, `build_failed`, `abandoned`. `consume_unread()` called by `/neighborhood/state` tick; messages injected into `_peterChat` array with per-event icons (✅ complete, ⚠️ alert, 🔨 start). All alert events (`spec_blocked`, `draft_blocked`, `promote_failed`, `draft_ready`, `build_failed`, `review_needed`) trigger `needsAttn` indicator. Cursor is advanced on each consumption so messages are never duplicated. |
| Code location | `frank_lloyd/relay.py`, `frank_lloyd/auto_runner.py` (`relay.append` calls), `app/routes/neighborhood.py` (consumption + injection) |
| Reuse | Cursor-advance pattern; `_peterChat` array already used for operator messages |

### A.0.7 Peter lifecycle command routing
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Operator talks to Peter; Peter queues and auto-starts Frank Lloyd immediately — no "run BUILD-N" step needed for normal safe work |
| Technical description | `POST /peter/action` → `peter.commands.parse_command()` → `peter.router.route()`. Build intake (`handle_build_intent`) queues then fires `run_full_auto()` in `threading.Thread(daemon=True)` immediately. Response says "Frank Lloyd is building now." Lifecycle commands (approve/reject/discard/promote) still available for manual intervention. |
| Code location | `app/routes/neighborhood.py`, `peter/router.py`, `peter/handlers.py` |
| Reuse | Full peter router/handler stack; `frank_lloyd.auto_runner.run_full_auto()` |

### A.0.8 Bulk-abandon by source
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Operator cleanup path for orphan builds auto-queued by a source channel (e.g. peter_chat_smart) |
| Technical description | `frank_lloyd.abandoner.abandon_by_source(source)` abandons all non-terminal builds whose `request_queued.extra.source` matches. Exposed via `POST /frank-lloyd/bulk-abandon` and Peter command `abandon frank queue` (defaults to `peter_chat_smart`). |
| Code location | `frank_lloyd/abandoner.py`, `app/routes/frank_lloyd_actions.py`, `peter/commands.py`, `peter/handlers.py` |
| Reuse | `frank_lloyd.abandoner.abandon_build` (single-build path) |

### A.0.10 Source-based execution policy
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Every build carries an `execution_policy` that determines whether it auto-applies or requires review — set at intake time based on who queued it |
| Technical description | `frank_lloyd.request_writer._policy_for_source(source)`: `_ABODE_SOURCES = {"operator", "peter_chat", "peter_chat_smart", "neighborhood_ui", "queue_and_run"}` + `smart_queue_*` prefix → `"auto_apply"`. All other sources → `"review_required"`. Written into every request JSON. `FLJob.execution_policy` exposes it. `load_active_job()` filters `notify_only`/`hidden_import`. Neighborhood suppresses `auto_apply + draft_generating` from the workspace card. |
| Code location | `frank_lloyd/request_writer.py` (`_ABODE_SOURCES`, `_policy_for_source`), `frank_lloyd/job.py` (`FLJob.execution_policy`, `load_active_job` filter), `app/routes/neighborhood.py` (active_job suppression) |
| Reuse | `FLJob` request-file read pattern |

### A.0.11 Safe text target promotion
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Frank Lloyd can now build and promote doc/config files (.md, .yaml, .yml, .json, .txt, .rst) in addition to Python code |
| Technical description | `stage2_promoter._SAFE_TEXT_EXTENSIONS` frozenset; `_validate_target_path()` allows safe text extensions. `stage2_drafter._detect_doc_build_from_spec()` detects doc builds by checking spec's `affected_files` for non-.py extensions; routes to `_DOC_SYSTEM` prompt instead of code prompt. |
| Code location | `frank_lloyd/stage2_promoter.py`, `frank_lloyd/stage2_drafter.py` |
| Reuse | `_detect_modification_build()` pattern in stage2_drafter |

### A.0.12 Frank Lloyd operator emergency controls
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Operator can halt a running build, purge all pending builds, and disable/enable Frank Lloyd intake — without killing the process |
| Technical description | Stop flag (`frank_lloyd.auto_runner._stop_requested`) checked between all 5 pipeline steps in `run_full_auto()`. `request_stop()` sets flag; `get_runner_state()` reports active build. `abandon_all()` in abandoner scans full build log (no source filter) and abandons all non-terminal builds. `frank_lloyd/control.py` owns `data/frank_lloyd/control.json` (enabled/disabled state). Intake gate in `handle_build_intent` calls `is_enabled()` before queueing. HTTP: POST /frank-lloyd/hard-stop, /purge-all, /disable, /enable; GET /frank-lloyd/control-state. Peter commands: "stop frank", "clear frank", "disable frank", "enable frank". Neighborhood: disabled banner, stop/purge/toggle-intake buttons. |
| Code location | `frank_lloyd/auto_runner.py`, `frank_lloyd/abandoner.py`, `frank_lloyd/control.py` (new), `app/routes/frank_lloyd_actions.py`, `peter/handlers.py`, `peter/commands.py`, `peter/router.py`, `app/routes/neighborhood.py` |
| Reuse | `frank_lloyd.abandoner.abandon_build()` (single-build path), observability bridge transport pattern |

### A.0.9 Frank-first routing metadata
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Tracking which builds were built by Frank Lloyd vs escalated to Claude, at what cost tier, and which are candidates for Frank absorption — fulfilling the Frank-first doctrine |
| Technical description | Every build request carries a `routing` block: `builder_lane` (frank/claude), `cost_tier` (cheap/standard/escalated/escalated_high), `escalation_reason`, `absorption_candidate`, `absorption_notes`, `model_used` (from CHEAP_MODEL env). Written into request file and build log event. `FLJob.routing` exposes it via the job model. Peter's queue confirmation shows the routing lane. Neighborhood state includes `last_routing`. |
| Code location | `frank_lloyd/request_writer.py` (`_build_default_routing`, `queue_build`), `frank_lloyd/job.py` (`FLJob.routing`, `_build_job`), `peter/handlers.py` (`_fl_build_default_routing`), `app/routes/neighborhood.py` (`last_routing` in `_frank_lloyd_state`; `_flRenderRoutingRow` JS; `#fl-routing-row` HTML) |
| Reuse | `FLJob` event-sourcing and request-file read pattern |

---

---

## A.1 Peter — Operator interface and coordinator

**Category**: house | **Maturity**: stable | **Autonomy**: supervised | **Outcome type**: force_multiplier

Peter is the front door. He reads from other agents, reports upward, and surfaces what the operator needs to act on. He does not execute Belfort's logic, run checks, or perform operating service work.

### A.1.1 Peter chat interface
| Field | Value |
|---|---|
| Status | live |
| Business purpose | User asks Peter anything about the system; Peter responds in plain English |
| Technical description | Intent parsing via `cheap` LM tier; routes to system state reads; LMHelper for response summarization |
| Code location | `app/routes/monitor.py` — `/peter/chat` |
| Reuse | Any new agent capability can surface via Peter by adding a command handler |

### A.1.2 System status report
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Peter gives a one-sentence summary of what is happening right now |
| Technical description | Reads supervisor state, Belfort state, portfolio snapshot; LM summarization if available |
| Code location | `app/routes/monitor.py` — `/peter/status` |
| Reuse | Neighborhood state endpoint calls this to populate Peter's panel |

### A.1.3 Loop control (surfaced through Peter)
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Start and stop the research loop |
| Technical description | `POST /loop/start`, `POST /loop/stop` — delegates to `app/loop.py`. System capability surfaced through Peter, not owned by Peter. |
| Code location | `app/main.py`, `app/loop.py` |
| Reuse | Neighborhood supervisor panel; dev dashboard loop controls |

---

## A.2 Mr Belfort — Trading research house

**Category**: house | **Maturity**: prototype | **Autonomy**: supervised | **Outcome type**: revenue (prototype)

Belfort is the prototype revenue house and proving ground for real learning infrastructure. He owns mock trading today — live trading is a future milestone earned through demonstrated readiness. Belfort is also the template for future specialist houses.

### A.2.1 Mock trading engine
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Belfort runs a simulated trading strategy and tracks real P&L, positions, and trade history |
| Technical description | Mean-reversion + MA crossover + ER filter. Portfolio state in `data/portfolio.json`. Trades logged per session. |
| Code location | `app/strategy/mean_reversion.py`, `app/portfolio.py`, `app/mock_trade_task.py` |
| Reuse | All Belfort readiness, learning, and diagnostics endpoints read from `get_snapshot()` and `get_trades()` |

### A.2.2 Readiness scorecard
| Field | Value |
|---|---|
| Status | live |
| Business purpose | 8-gate pass/fail scorecard showing whether Belfort is ready to trade and how the current strategy compares to baseline |
| Technical description | Deterministic gates: trading enabled, regime warmup, win rate, expectancy, drawdown, baseline comparison, soft signals, research trigger. 5 readiness levels. |
| Code location | `app/routes/belfort_readiness.py` — `GET /belfort/readiness` |
| Reuse | Diagnostics endpoint imports helpers. Neighborhood Belfort panel renders gates. Currently Belfort-specific — intended for generalization when a second house needs it. |

### A.2.3 Baseline reset
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Records a config snapshot after a strategy is promoted, so drift can be detected |
| Technical description | Writes `data/baseline_adoption_record.json` with current config, P&L, trade count, strategy label |
| Code location | `app/routes/belfort_readiness.py` — `POST /belfort/readiness/reset` |
| Reuse | Diagnostics reads this to compute strategy drift |

### A.2.4 Research trigger engine
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Detects when strategy performance is slipping — fires hard alarm or soft warning |
| Technical description | 6 hard triggers (sustained loss, drawdown, win rate, expectancy, regime mismatch, win-rate regression); 3 soft triggers (any negative expectancy after 5 trades, PF < 1.0, drawdown from peak > $1k). Pressure level: none/soft/hard. |
| Code location | `app/routes/belfort_readiness.py` — `_research_triggers()`, `_soft_triggers()` |
| Reuse | Learning endpoint imports `_research_triggers()` for verdict. Diagnostics imports for trigger detail. |

### A.2.5 Learning summary and verdict
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Plain-English summary of Belfort's current optimization state: what the system recommends and why |
| Technical description | Reads win rate, expectancy, regime, research triggers, candidate queue. Maps pressure level to verdict: Continue / Monitor / Tune / Research / Pause. Optionally enriches with `cheap` LM. This is supervised optimization — verdicts trigger operator-approved research, not autonomous strategy updates. |
| Code location | `app/routes/belfort_learning.py` — `GET /belfort/learning` |
| Reuse | Currently Belfort-specific — intended for generalization when a second house needs a performance verdict engine. |

### A.2.6 Diagnostics panel
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Shows operator: has the strategy drifted from baseline? Is P&L on a good/bad path? Why hasn't a research trigger fired? |
| Technical description | Three deterministic sub-reports: strategy drift (config key comparison), session P&L path (expectancy, peak, drawdown), trigger detail (active signals, gaps to thresholds, research bridge message) |
| Code location | `app/routes/belfort_diagnostics.py` — `GET /belfort/diagnostics` |
| Reuse | Sub-report pattern (drift, path, threshold proximity) reusable for other houses |

### A.2.7 Memory / state snapshot
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Persists Belfort's running state (last trade, position, regime, session metrics) across restarts |
| Technical description | Reads/writes `data/agent_state/mr_belfort.json`. Includes last seen regime, last trade summary, session P&L markers. |
| Code location | `app/routes/belfort_memory.py` — `GET /belfort/memory` |
| Reuse | Neighborhood Belfort panel reads this for position + last trade display |

### A.2.8 Live Readiness Gate
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Evaluates whether paper trading track record meets minimum thresholds for live consideration; provides informational verdict to operator |
| Technical description | Computes trade count, win rate, expectancy from paper portfolio; paper order count from `paper_exec_log.jsonl`; signal block rate from `signal_log.jsonl`. Verdicts: not_enough_data / not_ready / candidate. Informational only — does not block mode-advance. |
| Code location | `app/belfort_live_gate.py` — `compute_live_readiness()`; `observability/belfort_summary.py` — `read_live_readiness()` |
| Reuse | `_belfort_state()` in neighborhood, `handle_belfort_status()` in Peter handlers, existing paper/signal logs |

---

---

# B. Backstage Operating Services

These services are infrastructure. They are not houses and do not appear as primary neighborhood identities. Their outputs surface through Peter or the dev dashboard.

---

## B.1 Loop Supervisor — Bounded execution coordinator

**Category**: operating_service | **Maturity**: stable | **Outcome type**: infrastructure

### B.1.1 Supervisor daemon
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Runs research campaigns on a bounded schedule; wakes up, checks conditions, triggers runs, sleeps |
| Technical description | Background thread started at lifespan if enabled. Reads `data/supervisor_state.json`. Delegates campaign execution to `research/` package. |
| Code location | `app/supervisor.py`, `app/routes/supervisor.py` |
| Reuse | Supervisor state is read by Peter and Neighborhood state endpoint |

### B.1.2 Campaign orchestration
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Manages a full parameter-sweep research session: starts, runs to stop conditions, writes brief, produces candidates |
| Technical description | 5 stop conditions, durable state per campaign, lock safety, operator brief in JSON + markdown. Campaign results fed to candidate queue. |
| Code location | `research/campaign_runner.py`, `research/campaign_state.py`, `research/campaign_brief.py`, `scripts/run_campaign.py` |
| Reuse | Candidate queue is read by Belfort diagnostics, neighborhood, and Peter |

### B.1.3 Candidate queue
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Holds research-generated strategy candidates waiting for operator review |
| Technical description | `read_queue()` / `write_queue()` on `data/candidate_queue.json`. Status: pending / held / approved / rejected. |
| Code location | `research/candidate_queue.py` |
| Reuse | Diagnostics reads queue for research bridge. Neighborhood renders pending count. |

---

## B.2 Loop Checker — Audit and pattern finder

**Category**: operating_service | **Maturity**: stable | **Outcome type**: governance

### B.2.1 Checker daemon
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Watches for suspicious patterns in trading and system behavior; surfaces findings without mutating state |
| Technical description | Background thread started unconditionally at lifespan. Low-overhead, read-only. Findings logged to event log. |
| Code location | `app/checker.py` |
| Reuse | Findings surface through Peter's status summaries |

---

## B.3 Custodian — Runtime health monitor

**Category**: operating_service | **Maturity**: stable | **Outcome type**: reliability

### B.3.1 Runtime health check
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Tells operator if the backend, UI, and processes are healthy without them having to check manually |
| Technical description | Checks PID files, process liveness, port availability (8001, 8502), flags stale port 8501. Read/diagnose/report — never mutates. |
| Code location | `app/routes/custodian.py` — `GET /custodian/check` |
| Reuse | Peter `health` command calls this; dev dashboard health line reads it |

---

## B.4 Test Sentinel — Patch-safety validator

**Category**: operating_service | **Maturity**: stable | **Outcome type**: reliability

### B.4.1 Targeted test runner
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Before patching a file, operator can run relevant tests and get a safety verdict |
| Technical description | `FILE_TEST_MAP` maps source files to test scripts. Modes: smoke / auto / full. Verdict: safe / review / not_ready. |
| Code location | `app/routes/test_sentinel.py` — `POST /sentinel/run` |
| Reuse | Peter `test` command invokes this. Dev dashboard Controls tab shows verdict. |

---

## B.5 Cost Warden — LM routing and budget awareness

**Category**: operating_service | **Maturity**: stable | **Outcome type**: infrastructure

### B.5.1 LM routing policy
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Ensures all LM calls go through a consistent policy: right tier, logged, cost-aware |
| Technical description | `TASK_POLICY` maps (agent, task) → tier. `route()` selects model. `LMHelper` is the standard interface for LM calls. All calls logged to `data/warden_usage.jsonl`. |
| Code location | `app/cost_warden.py` |
| Reuse | Every agent that uses LM should use `LMHelper` — currently used by Peter, Belfort learning |

### B.5.2 Usage reporting
| Field | Value |
|---|---|
| Status | live |
| Business purpose | Shows operator how many LM calls have been made, at what cost tier |
| Technical description | Reads `data/warden_usage.jsonl`, aggregates by tier and agent. |
| Code location | `app/routes/cost_warden.py` — `GET /warden/usage`, `GET /warden/status` |
| Reuse | Dev dashboard cost tab; neighborhood Warden panel |

---

---

# C. Reusable Platform Capabilities

These are cross-cutting capabilities built once, usable by all houses and services.

---

## C.1 Neighborhood state endpoint
| Field | Value |
|---|---|
| Status | live |
| Category | platform |
| Business purpose | Single endpoint that gives the neighborhood HTML everything it needs to render all panels |
| Technical description | Aggregates: portfolio snapshot, Belfort state, supervisor state, warden state, regime, loop status. Polled every 5s. |
| Code location | `app/routes/neighborhood.py` — `GET /neighborhood/state` |
| Owner | System (not Peter) |
| Reuse | All neighborhood panels read from this one endpoint |

## C.2 Neighborhood HTML frontend
| Field | Value |
|---|---|
| Status | live |
| Category | platform |
| Business purpose | Pixel-art community UI — the primary operator-facing window into The Abode |
| Technical description | Single-file HTML/CSS/JS (~2700 lines) embedded in neighborhood.py. Houses for each agent. Panels with cooldown guards to prevent stutter. |
| Code location | `app/routes/neighborhood.py` — `GET /neighborhood` |
| Reuse | New houses add a house unit + panel; existing panel/cooldown patterns apply |

## C.3 Agent state persistence
| Field | Value |
|---|---|
| Status | live |
| Category | platform |
| Business purpose | Each agent's live state is persisted to disk so restarts don't lose context |
| Technical description | JSON files in `data/agent_state/`. Read by routes and neighborhood. |
| Code location | `observability/` package, `data/agent_state/` |
| Reuse | All agents that need cross-restart state |

## C.4 Telemetry
| Field | Value |
|---|---|
| Status | live |
| Category | platform |
| Business purpose | Per-campaign performance telemetry for post-run analysis |
| Technical description | Append-only JSONL files in `data/telemetry/`. One file per campaign. |
| Code location | `observability/`, `data/telemetry/` |
| Reuse | Any house that produces per-run performance data |

---

## B.5 Belfort Foundation + Reflection Layer (BELFORT-FOUNDATION-01 + BELFORT-REFLECTION-AND-CONTROL-01)
| Field | Value |
|---|---|
| Status | live (paper execution active) |
| Category | Belfort house |
| Business purpose | Typed strategy interface, risk guardrails, operating mode state machine, observation runner, preflight snapshot, freshness tracking, signal evaluation path, paper order placement, and Peter mode control — full foundation through paper execution |
| Technical description | 8 core modules + trading loop wiring + freshness bridge + signal eval + paper execution + Peter mode control. `belfort_observer` runs every tick. `belfort_signal_eval` evaluates MeanReversionV1 + RiskGuardrails in SHADOW/PAPER mode. In PAPER mode, eligible buy signals are forwarded to `belfort_paper_exec` which submits limit orders to the Alpaca paper API and logs results. Signal eval and paper exec results are returned to `_loop_body` for clean sequencing. |
| Code location | `app/belfort_mode.py`, `app/belfort_strategy.py`, `app/belfort_risk.py`, `app/belfort_observer.py`, `app/belfort_signal_eval.py`, `app/belfort_broker.py`, `app/belfort_paper_exec.py`, `app/trading_loop.py`, `observability/belfort_summary.py` |
| Data paths | `data/belfort/observation_log.jsonl`, `data/belfort/preflight.json`, `data/agent_state/belfort_mode.json`, `data/belfort/signal_log.jsonl`, `data/belfort/paper_exec_log.jsonl` |
| Observability bridge | `observability/belfort_summary.py` — disk-read bridge for Peter and UI. Functions: `read_latest_signal_decision()`, `read_signal_stats_today()`, `read_latest_paper_execution()`, `read_paper_exec_stats_today()`, `read_latest_sim_trade()`, `read_sim_stats_today()`, `read_sim_running_status()`. |
| Peter commands | `belfort status` — includes signal summary (shadow/paper), paper exec summary (paper only), and sim lane summary (always). `belfort advance/regress/set`. |
| Freshness rule | Regular session: fresh ≤15 min, stale 15–60 min, very_stale >60 min. Off-hours: fresh ≤60 min, stale >60 min. Freshness and readiness always separate. |
| SIP cap rule | `data_lane == "IEX_ONLY"` → readiness_level capped at OBSERVATION_ONLY. Paper execution still runs (gating is independent of readiness label). |
| Signal eval invariants | `was_executed = False` always in signal log. Signal log never triggers orders. |
| Paper exec invariants | `paper_only = True` always. `was_submitted_to_broker` reflects actual submission result. Broker URL validated against `paper-api.alpaca.markets` on every call. No shorting (sell blocked). No margin. No options. All outcomes logged. |
| Paper exec gates | mode=paper + session=regular + action=buy + risk_can_proceed + qty>0 + price>0 — all must pass |
| Mode control contract | `set_mode()` failure: `previous_mode == mode`. Handler never surfaces wrong previous_mode. Mode transitions sync preflight snapshot immediately. |
| UI contract | MODE and READINESS always separate. Lane header always visible with dot indicator (green=active, blue=sim, grey=paused), mode chip, session sub-line. Session notice bar shown for market-closed/stale/sim-running states. Signal row shown for shadow/paper. Paper exec row shown for paper mode only. Sim row shown when sim is running or has ticks today. Learn strip (4-cell: VERDICT/PAPER TODAY/BLOCKED/SIM TODAY). Controls grid 2×2: Observe Live (→Shadow Live→Paper Trade Live based on mode), Practice Sim, Review / Learn, Pause. Mode-advance button (`#btn-mode-advance`, class `.bmode-advance-btn`) shown when next mode is available — calls `/monitor/belfort/mode/advance`. Pause stops all active lanes via `belfortPauseAll()`. |
| Mode advance | `POST /monitor/belfort/mode/advance` — advances observation→shadow→paper one step. LIVE not reachable from UI. Gate-checked by existing `can_advance_to()`. Returns `{ok, mode, previous_mode, error}`. JS: `belfortModeAdvance()` — shows error in `#belfort-mode-note`, refreshes state after 400ms. |
| Operator labels | Observe Live (mode=observation, trading thread running), Shadow Live (mode=shadow, signals evaluated no orders), Paper Trade Live (mode=paper, signals + Alpaca paper), Practice Sim (sim thread, any hour, no broker), Review / Learn (research campaigns via supervisor daemon, not a persistent mode). |
| Sim lane | `app/belfort_sim.py` — separate MeanReversionV1 instance, `_SimQuoteProxy` (session_type→"regular", data_lane→real or IEX_ONLY), mock fill accounting ($10k sim capital, in-memory), daemon thread, `data/belfort/sim_log.jsonl`. All sim records tagged `market_regime: "closed_sim"`. Controls: `/monitor/trading/sim/start`, `/monitor/trading/sim/stop`, `/monitor/trading/sim/status`. |
| Observability bridge additions | `read_learn_strip()` — reads `learning_history.jsonl` (verdict), signal log (blocked count, main blocker), paper exec log (submitted/gated/errored today). `read_regime_metrics()` — per-regime counts (regular/closed_sim/extended). `read_strategy_profile()` — current market session + fitness text per regime. |
| Regime learning | `app/belfort_regime_learning.py` — `compute_regime_metrics()`, `current_strategy_profile()`, `maybe_record_regime_snapshot(tick)`. Auto-snapshot every 20 trading ticks writes to `data/learning_history.jsonl`. Paper exec records tagged `market_regime` from session_type. Extended-hours paper: NOT supported (blocked at 3 layers — honestly labeled in UI and Peter). |
| UI regime elements | Regime indicator chip (`#belfort-regime-chip`) shows REGULAR/CLOSED/PRE-MKT/AFTER-HRS. Strategy profile row (`#belfort-strategy-profile`) shows per-regime fitness text. Both update with each `updateBelfortStats()` call. |
| Reuse | `_loop_body` tick structure, observability bridge pattern, `submit_paper_order` uses same Alpaca credentials as data feed |
| Tests | 326 tests across 12 Belfort test files (adding test_belfort_regime_learning: 64) |

---

## B.4 Belfort Market-Connection Stack
| Field | Value |
|---|---|
| Status | live (paper sim / observation mode) |
| Category | Belfort house |
| Business purpose | Connects Belfort to real market data and paper trading infrastructure; gates live readiness |
| Technical description | 11 modules: market_time (NYSE session), cost_engine (SEC31/TAF/spread), order_ledger (append-only JSONL), kill_switch (disk signal), market_data_feed (Alpaca L1/sim), spread_monitor (observation JSONL), execution_overlay (pre-trade checks), broker_connector (Alpaca connector), reconciler (position audit), shadow_runner (no-order shadow intents), readiness_scorecard (7-gate, 5 levels). |
| Code location | `app/market_time.py`, `app/cost_engine.py`, `app/order_ledger.py`, `app/kill_switch.py`, `app/market_data_feed.py`, `app/spread_monitor.py`, `app/execution_overlay.py`, `app/broker_connector.py`, `app/reconciler.py`, `app/shadow_runner.py`, `app/readiness_scorecard.py`, `app/routes/market.py` |
| Observability bridge | `observability/market_summary.py` — disk-read bridge so Peter handlers never import from app/ |
| Peter commands | `market status`, `market readiness`, `kill trading` |
| Kill signal | Written to `data/kill_signal.json`; `trading_loop._poll_kill_signal()` checks on each tick |
| Readiness levels | NOT_READY → OBSERVATION_ONLY → PAPER_READY → SHADOW_COMPLETE → LIVE_ELIGIBLE |
| Reuse | Peter command/router/handler pattern; append-only JSONL pattern; observability.agent_state; observability.event_log |
