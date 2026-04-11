# Capability Registry — The Abode
*Last updated: 2026-04-11 (Frank Lloyd identity pass)*

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

**Category**: house | **Maturity**: planned | **Autonomy**: supervised (when built) | **Outcome type**: force_multiplier

Frank Lloyd owns the construction, modification, duplication, and evolution of agents and houses inside the Abode. It is the mechanism by which the workforce can grow itself rather than requiring all construction work to happen outside the system.

**Status: PLANNED — Stage 1 infrastructure only. See `docs/frank_lloyd/FRANK_LLOYD_SPEC.md` for the full spec.**

### A.0.1 Intent elaboration and spec writing
| Field | Value |
|---|---|
| Status | planned |
| Business purpose | Accepts high-level operator intent and produces a structured spec: mission, workflows, eligibility assessment, architecture layer placement, approval boundaries |
| Technical description | LM-backed elaboration (cheap tier) + deterministic eligibility check against HOUSE_ELIGIBILITY criteria. Output: markdown spec in staging area. |
| Code location | not yet built |
| Reuse | `LMHelper`, `research/manifest.py` patterns |

### A.0.2 House eligibility assessment
| Field | Value |
|---|---|
| Status | planned |
| Business purpose | For any candidate concept, returns an honest verdict: house / backstage service / not ready. Defaults to skepticism — backstage service unless all five criteria are clearly met. |
| Technical description | Deterministic check against five criteria from HOUSE_ELIGIBILITY.md. LM-enriched explanation optional. |
| Code location | not yet built |
| Reuse | HOUSE_ELIGIBILITY.md criteria as logic rules |

### A.0.3 Build execution (staging)
| Field | Value |
|---|---|
| Status | planned |
| Business purpose | From an approved spec, produces code artifacts in a staging area. Never writes to the live repo. Auto-triggers Sentinel. Produces diff + build manifest for operator review. |
| Technical description | LM-backed code generation (strong tier). Output to `staging/frank_lloyd/{build_id}/`. Sentinel integration. Build manifest listing all files to be created/modified. |
| Code location | not yet built |
| Reuse | `LMHelper`, `observability/event_log.py`, `research/approval_policy.py`, `research/governance.py` |

### A.0.4 Build log
| Field | Value |
|---|---|
| Status | planned |
| Business purpose | Append-only record of every build request, artifact, approval, and rejection |
| Technical description | `data/frank_lloyd/build_log.jsonl` — same pattern as event_log and warden_usage |
| Code location | not yet built |
| Reuse | `observability/event_log.py` pattern |

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
