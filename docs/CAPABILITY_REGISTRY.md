# Capability Registry — The Abode
*Last updated: 2026-04-10*

This registry is an inventory of all live capabilities in the system. Each entry shows what it does for the user (business purpose), what it does technically, where the code lives, and what it can be reused for.

---

## How to read this registry

**Status**: `live` | `partial` | `planned`  
**Owner**: which agent or system is responsible  
**Reuse**: what other blocks can build on this capability  

---

## 1. Peter — Coordinator and front door

### 1.1 Peter chat interface
| Field | Value |
|---|---|
| Status | live |
| Owner | Peter |
| Business purpose | User asks Peter anything about the system; Peter responds in plain English |
| Technical description | Intent parsing via `cheap` LM tier; routes to system state reads; LMHelper for response summarization |
| Code location | `app/routes/monitor.py` — `/peter/chat` |
| Reuse | Any new agent capability can surface via Peter by adding a command handler |

### 1.2 System status report
| Field | Value |
|---|---|
| Status | live |
| Owner | Peter |
| Business purpose | Peter gives a one-sentence summary of what is happening right now |
| Technical description | Reads supervisor state, Belfort state, portfolio snapshot; LM summarization if available |
| Code location | `app/routes/monitor.py` — `/peter/status` |
| Reuse | Neighborhood state endpoint calls this to populate Peter's panel |

### 1.3 Loop control
| Field | Value |
|---|---|
| Status | live |
| Owner | Peter / System |
| Business purpose | Start and stop the research loop |
| Technical description | `POST /loop/start`, `POST /loop/stop` — delegates to `app/loop.py` |
| Code location | `app/main.py`, `app/loop.py` |
| Reuse | Neighborhood supervisor panel; dev dashboard loop controls |

---

## 2. Mr Belfort — Trading research worker

### 2.1 Mock trading engine
| Field | Value |
|---|---|
| Status | live |
| Owner | Belfort |
| Business purpose | Belfort runs a simulated trading strategy and tracks real P&L, positions, and trade history |
| Technical description | Mean-reversion + MA crossover + ER filter. Portfolio state in `data/portfolio.json`. Trades logged per session. |
| Code location | `app/strategy/mean_reversion.py`, `app/portfolio.py`, `app/mock_trade_task.py` |
| Reuse | All Belfort readiness, learning, and diagnostics endpoints read from `get_snapshot()` and `get_trades()` |

### 2.2 Readiness scorecard
| Field | Value |
|---|---|
| Status | live |
| Owner | Belfort |
| Business purpose | 8-gate pass/fail scorecard showing whether Belfort is ready to trade and how the current strategy compares to baseline |
| Technical description | Deterministic gates: trading enabled, regime warmup, win rate, expectancy, drawdown, baseline comparison, soft signals, research trigger. 5 readiness levels. |
| Code location | `app/routes/belfort_readiness.py` — `GET /belfort/readiness` |
| Reuse | Diagnostics endpoint imports helpers. Neighborhood Belfort panel renders gates. |

### 2.3 Baseline reset
| Field | Value |
|---|---|
| Status | live |
| Owner | Belfort |
| Business purpose | Records a config snapshot after a strategy is promoted, so drift can be detected |
| Technical description | Writes `data/baseline_adoption_record.json` with current config, P&L, trade count, strategy label |
| Code location | `app/routes/belfort_readiness.py` — `POST /belfort/readiness/reset` |
| Reuse | Diagnostics reads this to compute strategy drift |

### 2.4 Research trigger engine
| Field | Value |
|---|---|
| Status | live |
| Owner | Belfort |
| Business purpose | Detects when strategy performance is slipping — fires hard alarm or soft warning |
| Technical description | 6 hard triggers (sustained loss, drawdown, win rate, expectancy, regime mismatch, win-rate regression); 3 soft triggers (any negative expectancy after 5 trades, PF < 1.0, drawdown from peak > $1k). Pressure level: none/soft/hard. |
| Code location | `app/routes/belfort_readiness.py` — `_research_triggers()`, `_soft_triggers()` |
| Reuse | Learning endpoint imports `_research_triggers()` for verdict. Diagnostics imports for trigger detail. |

### 2.5 Learning summary and verdict
| Field | Value |
|---|---|
| Status | live |
| Owner | Belfort |
| Business purpose | Plain-English summary of Belfort's current learning state: what the system recommends and why |
| Technical description | Reads win rate, expectancy, regime, research triggers, candidate queue. Maps pressure level to verdict: Continue / Monitor / Tune / Research / Pause. Optionally enriches with `cheap` LM. |
| Code location | `app/routes/belfort_learning.py` — `GET /belfort/learning` |
| Reuse | Neighborhood Belfort panel renders verdict chip + note |

### 2.6 Diagnostics panel
| Field | Value |
|---|---|
| Status | live |
| Owner | Belfort |
| Business purpose | Shows operator: has the strategy drifted from baseline? Is P&L on a good/bad path? Why hasn't a research trigger fired? |
| Technical description | Three deterministic sub-reports: strategy drift (config key comparison), session P&L path (expectancy, peak, drawdown), trigger detail (active signals, gaps to thresholds, research bridge message) |
| Code location | `app/routes/belfort_diagnostics.py` — `GET /belfort/diagnostics` |
| Reuse | Self-contained; uses helpers from readiness. No LM. |

### 2.7 Memory / state snapshot
| Field | Value |
|---|---|
| Status | live |
| Owner | Belfort |
| Business purpose | Persists Belfort's running state (last trade, position, regime, session metrics) across restarts |
| Technical description | Reads/writes `data/agent_state/mr_belfort.json`. Includes last seen regime, last trade summary, session P&L markers. |
| Code location | `app/routes/belfort_memory.py` — `GET /belfort/memory` |
| Reuse | Neighborhood Belfort panel reads this for position + last trade display |

---

## 3. Loop Supervisor — Bounded execution coordinator

### 3.1 Supervisor daemon
| Field | Value |
|---|---|
| Status | live |
| Owner | Loop Supervisor |
| Business purpose | Runs research campaigns on a bounded schedule; wakes up, checks conditions, triggers runs, sleeps |
| Technical description | Background thread started at lifespan if enabled. Reads `data/supervisor_state.json`. Delegates campaign execution to `research/` package. |
| Code location | `app/supervisor.py`, `app/routes/supervisor.py` |
| Reuse | Supervisor state is read by Peter and Neighborhood state endpoint |

### 3.2 Campaign orchestration
| Field | Value |
|---|---|
| Status | live |
| Owner | Loop Supervisor |
| Business purpose | Manages a full parameter-sweep research session: starts, runs to stop conditions, writes brief, produces candidates |
| Technical description | 5 stop conditions, durable state per campaign, lock safety, operator brief in JSON + markdown. Campaign results fed to candidate queue. |
| Code location | `research/campaign_runner.py`, `research/campaign_state.py`, `research/campaign_brief.py`, `scripts/run_campaign.py` |
| Reuse | Candidate queue is read by Belfort diagnostics, neighborhood, and Peter |

### 3.3 Candidate queue
| Field | Value |
|---|---|
| Status | live |
| Owner | Loop Supervisor |
| Business purpose | Holds research-generated strategy candidates waiting for operator review |
| Technical description | `read_queue()` / `write_queue()` on `data/candidate_queue.json` (or similar). Status: pending / held / approved / rejected. |
| Code location | `research/candidate_queue.py` |
| Reuse | Diagnostics reads queue for research bridge. Neighborhood renders pending count. |

---

## 4. Loop Checker — Audit and pattern finder

### 4.1 Checker daemon
| Field | Value |
|---|---|
| Status | live |
| Owner | Loop Checker |
| Business purpose | Watches for suspicious patterns in trading and system behavior; surfaces findings without mutating state |
| Technical description | Background thread started unconditionally at lifespan. Low-overhead, read-only. Findings logged to event log. |
| Code location | `app/checker.py` |
| Reuse | Findings surface through Peter's status summaries |

---

## 5. Custodian — Runtime health monitor

### 5.1 Runtime health check
| Field | Value |
|---|---|
| Status | live |
| Owner | Custodian |
| Business purpose | Tells operator if the backend, UI, and processes are healthy without them having to check manually |
| Technical description | Checks PID files, process liveness, port availability (8001, 8502), flags stale port 8501. Read/diagnose/report — never mutates. |
| Code location | `app/routes/custodian.py` — `GET /custodian/check` |
| Reuse | Peter `health` command calls this; dev dashboard health line reads it |

---

## 6. Test Sentinel — Patch-safety validator

### 6.1 Targeted test runner
| Field | Value |
|---|---|
| Status | live |
| Owner | Test Sentinel |
| Business purpose | Before patching a file, operator can run relevant tests and get a safety verdict |
| Technical description | `FILE_TEST_MAP` maps source files to test scripts. Modes: smoke / auto / full. Verdict: safe / review / not_ready. |
| Code location | `app/routes/test_sentinel.py` — `POST /sentinel/run` |
| Reuse | Peter `test` command invokes this. Dev dashboard Controls tab shows verdict. |

---

## 7. Cost Warden — LM routing and budget awareness

### 7.1 LM routing policy
| Field | Value |
|---|---|
| Status | live |
| Owner | Cost Warden |
| Business purpose | Ensures all LM calls go through a consistent policy: right tier, logged, cost-aware |
| Technical description | `TASK_POLICY` maps (agent, task) → tier. `route()` selects model. `LMHelper` is the standard interface for LM calls. All calls logged to `data/warden_usage.jsonl`. |
| Code location | `app/cost_warden.py` |
| Reuse | Every agent that uses LM should use `LMHelper` — currently used by Peter, Belfort learning |

### 7.2 Usage reporting
| Field | Value |
|---|---|
| Status | live |
| Owner | Cost Warden |
| Business purpose | Shows operator how many LM calls have been made, at what cost tier |
| Technical description | Reads `data/warden_usage.jsonl`, aggregates by tier and agent. |
| Code location | `app/routes/cost_warden.py` — `GET /warden/usage`, `GET /warden/status` |
| Reuse | Dev dashboard cost tab; neighborhood Warden panel |

---

## 8. Neighborhood — User-facing frontend

### 8.1 Neighborhood state endpoint
| Field | Value |
|---|---|
| Status | live |
| Owner | System / Peter |
| Business purpose | Single endpoint that gives the neighborhood HTML everything it needs to render all panels |
| Technical description | Aggregates: portfolio snapshot, Belfort state, supervisor state, warden state, regime, loop status. Polled every 5s. |
| Code location | `app/routes/neighborhood.py` — `GET /neighborhood/state` |
| Reuse | All neighborhood panels read from this one endpoint; sub-panels (readiness, learning, diagnostics) have their own endpoints for on-demand detail |

### 8.2 Neighborhood HTML frontend
| Field | Value |
|---|---|
| Status | live |
| Owner | System |
| Business purpose | Pixel-art community UI — the primary operator-facing window into The Abode |
| Technical description | Single-file HTML/CSS/JS (~2700 lines) embedded in neighborhood.py. Houses for each agent. Panels with cooldown guards to prevent stutter. |
| Code location | `app/routes/neighborhood.py` — `GET /neighborhood` |
| Reuse | Each agent's panel reuses the state endpoint and its own detail endpoint |

---

## 9. Observability layer

### 9.1 Agent state persistence
| Field | Value |
|---|---|
| Status | live |
| Owner | System |
| Business purpose | Each agent's live state is persisted to disk so restarts don't lose context |
| Technical description | JSON files in `data/agent_state/`. Read by routes and neighborhood. |
| Code location | `observability/` package, `data/agent_state/` |
| Reuse | All agent panels in neighborhood read from this layer |

### 9.2 Telemetry
| Field | Value |
|---|---|
| Status | live |
| Owner | System |
| Business purpose | Per-campaign performance telemetry for post-run analysis |
| Technical description | Append-only JSONL files in `data/telemetry/`. One file per campaign. |
| Code location | `observability/`, `data/telemetry/` |
| Reuse | Research ledger reads telemetry for summary reports |
