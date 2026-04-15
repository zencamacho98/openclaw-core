# Technical Requirements Document — The Abode
*Last updated: 2026-04-15 (Belfort flow leaders, pre-open scoring, and fee-aware pacing)*

---

## 1. Runtime infrastructure

### Ports
| Service | Address | Purpose |
|---|---|---|
| Backend | `127.0.0.1:8001` | FastAPI; all API endpoints |
| UI | `http://localhost:8502` | Streamlit dev dashboard |
| Neighborhood | served from backend at `/neighborhood` | Primary user-facing HTML |

### Control
```bash
./scripts/ctl.sh start|stop|restart|status|logs
```
PID files: `run/backend.pid`, `run/ui.pid`  
Log files: `logs/backend.log`, `logs/ui.log`

### Configuration (`.env`)
```
OPENROUTER_API_KEY=...
APP_ENV=dev
CHEAP_MODEL=openai/gpt-4o-mini        # default cheap-tier
STRONG_MODEL=anthropic/claude-sonnet-4-6  # default strong-tier
```

### Dependencies
All Python dependencies live in `.venv/` — no `requirements.txt`.  
No test framework or linter is configured. Test runs are executed directly as Python scripts.

---

## 2. Architecture layers

The system has four layers. Each layer has a distinct role and must not absorb responsibilities from adjacent layers.

```
┌─────────────────────────────────────────────────┐
│  EXPERIENCE LAYER                               │
│  Neighborhood HTML   → /neighborhood (FastAPI)  │
│  Streamlit Dev UI    → port 8502                │
└───────────────────────────┬─────────────────────┘
                            │ aggregates state from all layers
┌───────────────────────────▼─────────────────────┐
│  EXECUTIVE / CONTROL LAYER                      │
│  Peter — operator interface, coordinator        │
│  Loop control routes (system-owned, not Peter)  │
│  ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ ┄ │
│  [control-plane daemons — operating services,   │
│   not houses, not part of Peter's interface]    │
│  Supervisor daemon (background thread)          │
│  Checker daemon (background thread)             │
└───────────────────────────┬─────────────────────┘
                            │
┌───────────────────────────▼─────────────────────┐
│  SPECIALIST HOUSE LAYER                         │
│  Mr Belfort — trading, research, readiness      │
│  (Frank Lloyd — construction house, planned)    │
└───────────────────────────┬─────────────────────┘
                            │
┌───────────────────────────▼─────────────────────┐
│  OPERATING SERVICES LAYER                       │
│  Custodian    — runtime health                  │
│  Test Sentinel — patch-safety validation        │
│  Cost Warden  — LM routing and budget           │
│  Portfolio / Strategy state                     │
└─────────────────────────────────────────────────┘
             ↑ all layers served by FastAPI at port 8001
```

**Note on Supervisor and Checker placement:** These are control-plane daemons that coordinate and audit execution. They run in the background behind Peter and are architecturally part of the control plane. However, they are operating services — not houses — and are not part of Peter's interface. They are shown in the executive/control layer box only to reflect their runtime placement, not to imply house status.

**Layer discipline:**
- Experience layer aggregates state from multiple downstream layers; it does not own logic
- Executive/control layer: Peter routes and reports; loop control and daemons are system-owned, not Peter-owned
- Specialist houses own domain-specific workflow and data; they do not absorb coordination or health-check logic
- Operating services support all layers; they do not become product-facing identities unless they earn house status

---

## 3. Agent roles and code locations

### Housed agents

#### Peter (executive layer — coordinator, front door)
- **Route**: `app/routes/monitor.py`
- **Endpoints (Peter-owned)**: `/peter/chat`, `/peter/status`, `/logs`
- **System endpoints (accessible via Peter, not owned by Peter)**: `/loop/start`, `/loop/stop` — these are system-level controls routed through `app/main.py` / `app/loop.py`
- **LM use**: `cheap` tier via `LMHelper` for intent parsing and summaries
- **Rule**: Peter reads from other agents and reports upward. Peter is not a backstage worker. Heavy orchestration logic must not collapse into Peter. Loop control, supervisor management, and health checks are system capabilities that Peter can invoke — they are not Peter's capabilities.

#### Mr Belfort (specialist house — trading research)
- **Routes**: `app/routes/belfort_readiness.py`, `app/routes/belfort_learning.py`, `app/routes/belfort_diagnostics.py`, `app/routes/belfort_memory.py`
- **Endpoints**: `/belfort/readiness`, `/belfort/readiness/reset`, `/belfort/learning`, `/belfort/diagnostics`, `/belfort/memory`
- **Desk core**: `app/belfort_scanner.py`, `app/belfort_policy.py`, `app/belfort_signal_eval.py`, `app/belfort_paper_exec.py`, `app/belfort_sim.py`
- **Strategy config + bounded apply path**: `app/strategy/` — `config.py`, `mean_reversion.py`, `applier.py`, `changelog.py`
- **Portfolio**: `app/portfolio.py` — `get_snapshot()`, `get_trades()`
- **State file**: `data/agent_state/mr_belfort.json`
- **Role**: Prototype revenue house, proving ground for learning infrastructure, template for future specialist houses. Currently sim + paper only — live trading requires earned readiness.

### Belfort workspace contract

The Belfort UI is still served from `app/analog_cockpit.py` through `app/routes/neighborhood.py`, but the experience is now organized into four internal workspaces inside the existing `/neighborhood` shell:

- `Trade` — default, operator-first, three-zone trading layout
- `Scanner` — expanded watchlist, flow leaders, catalysts, setup radar, tape context
- `Research` — learning, scorecards, readiness checklist, bounded adjustments, blotter
- `Guide` — `How It Works`, `BRD`, `TRD`

Implementation notes:
- No new backend route was required for the rework
- Existing state sources remain:
  - `/neighborhood/state`
  - `/belfort/learning`
  - `/monitor/proposal`
  - `/monitor/strategy`
  - `/monitor/regime`
- The renderer now groups state client-side into:
  - trade workspace state
  - scanner workspace state
  - research workspace state
- The neighborhood state payload now also derives a strict `belfort_paper_open_readiness` object with:
  - `armed_mode`
  - `broker_ready`
  - `reconciliation_clear`
  - `signal_engine_warm`
  - `scanner_live`
  - `paper_universe_ready`
  - `focus_symbol_tradeable`
  - `regular_session_open`
  - `operator_start_required`
  - `paper_path_proven`
  - `current_blocker`
  - `verdict`
  - `proof_chain`
- The same payload now also exposes trading-truth and desk-capacity fields used across the rail, `Trade`, and `Research`:
  - `current_session`
  - `paper_lane_state`
  - `scanner_focus_symbol`
  - `paper_eligible_symbol`
  - `current_signal_symbol`
  - `why_not_trading`
  - `order_pacing_state`
  - `remaining_daily_capacity`
  - `remaining_exposure_capacity`

### Operating services

#### Loop Supervisor (bounded execution coordinator)
- **Daemon**: `app/supervisor.py` — starts on lifespan if enabled
- **Route**: `app/routes/supervisor.py`
- **Endpoints**: `/supervisor/status`, `/supervisor/enable`, `/supervisor/disable`, `/supervisor/reset`, `/supervisor/step`
- **State**: `data/supervisor_state.json`

#### Loop Checker (audit / pattern finder)
- **Daemon**: `app/checker.py` — starts unconditionally on lifespan
- **No direct route** — findings surface via Peter and event log

#### Custodian (runtime health monitor)
- **Route**: `app/routes/custodian.py`
- **Endpoints**: `/custodian/check`
- **Design**: read/diagnose/report only — never mutates system state

#### Test Sentinel (patch-safety validator)
- **Route**: `app/routes/test_sentinel.py`
- **Endpoints**: `/sentinel/run`
- **Design**: targeted test runner — FILE_TEST_MAP maps changed files to relevant tests; verdicts: `safe/review/not_ready`

#### Cost Warden (LM routing and budget awareness)
- **Module**: `app/cost_warden.py`
- **Route**: `app/routes/cost_warden.py`
- **Endpoints**: `/warden/status`, `/warden/usage`
- **Key exports**: `LMHelper`, `route()`, `TASK_POLICY`, `cache_policy()`
- **State**: `data/warden_usage.jsonl`

---

## 4. LM policy

### Tier routing
1. **deterministic** — rule-based; no LM (health checks, data reads, scorecard gates)
2. **cheap** — routine summarization, intent parsing → `CHEAP_MODEL` (default: `openai/gpt-4o-mini`)
3. **strong** — architecture review, safety boundaries, hard tradeoffs → `STRONG_MODEL` (default: `anthropic/claude-sonnet-4-6`)

### Pattern for LM use
```python
from app.cost_warden import LMHelper

helper = LMHelper("agent_name", "task_name", max_tokens=200)
result = helper.call(system="...", user=data_str)
explanation = result.content if result.ok else f"[LM unavailable: {result.error}]"
```

### Rules
- Do NOT replace deterministic cores with LM behavior
- Do NOT bypass `LMHelper` with private LM clients
- All LM calls are logged in `data/warden_usage.jsonl`
- Always provide a graceful fallback when LM is unavailable

---

## 5. Strategy architecture (Belfort)

### Algorithm
- Scanner ranks symbols from benchmarks, liquid leaders, lower-price watch, and fresh Alpaca news headlines
- Scanner also scores short relative strength versus `SPY`, headline-based catalyst typing, market-cap / float / average-volume structure, relative volume, gap context, float turnover, pre-open opportunity, and risk flags
- Regime-routed policy selector chooses between mean-reversion and trend lenses
- Mean-reversion on 20-bar window, 1.0 std-dev threshold
- MA crossover filter (3-bar / 7-bar short/long windows)
- Kaufman Efficiency Ratio (ER) for regime detection and trade filtering
- Hard stop-loss and take-profit at configurable percentages
- Trade cooldown to prevent rapid re-entries

### Belfort desk flow
1. `app/trading_loop.py` refreshes observation state and the scanner snapshot
2. Scanner picks a `focus_symbol` from quote quality, short tape movement, relative strength versus `SPY`, recent catalysts, and structure-aware ranking
3. Scanner also computes paper tradeability using a stricter structure filter for paper promotion:
   - core liquid universe always eligible
   - expanded liquid-volatility names can become eligible if spread, tape stability, market cap, float, average volume, relative volume, and float turnover all pass
   - lower-quality or structurally weak names remain `watch only` or `blocked`
4. `app/belfort_signal_eval.py` evaluates that symbol in `shadow` or `paper` and writes named setup tags plus scanner context
4. `app/belfort_paper_exec.py` computes a brokerage-ready entry policy before each new buy:
   - daily order capacity
   - rolling hourly trade capacity
   - per-symbol cooldown
   - desk-wide cooldown
   - turnover budget
   - per-name concentration
   - total exposure room
   - active-name limit
   - estimated cost versus expected setup edge
   - training commission reserve plus net-edge-after-cost checks
5. `app/belfort_paper_exec.py` sends only bounded paper orders during paper-tradeable sessions (`pre_market`, `regular`, `after_hours`)
6. Existing open paper positions are grandfathered and remain manageable; the tighter caps apply to new entries, adds, and replacements
7. `app/trading_loop.py` enters a flatten-and-stand-down path into the overnight handoff window so Belfort does not silently become a swing trader
8. `app/belfort_sim.py` practices separately from paper and keeps its own policy memory
9. `observability/belfort_summary.py` builds setup scorecards and bridges the desk state into the UI and guide surfaces

### Scanner and catalyst limits
- Scanner uses Alpaca quotes plus Alpaca news headlines
- Relative strength is currently measured against short `SPY` tape, not a deeper multi-timeframe factor model
- Lower-price watch is still a proxy for small-cap hunting, but scanner ranking now also uses cached market-cap, float, and average-volume structure data
- Catalyst typing and risk flags are keyword-based for now; Belfort does not yet read SEC filings into structured balance-sheet or cash-flow features
- Phase 1 paper trading is intentionally bounded and long-only:
  - `SPY`, `QQQ`, `IWM`
  - liquid large-cap leaders
  - a small allowlisted set of scanner-approved liquid mid-caps
  - lower-price and news-led names remain scanner-visible but usually stay `watch only`

### Key parameters (in `data/strategy_config.json`)
`SHORT_WINDOW`, `LONG_WINDOW`, `MEAN_REV_WINDOW`, `MEAN_REV_THRESHOLD`, `STOP_LOSS_PCT`, `TAKE_PROFIT_PCT`, `TRADE_COOLDOWN`, `MAX_EFFICIENCY_RATIO`, `POSITION_SIZE`, `MR_REBOUND_CAP`

### Key execution policy parameters (config-backed)
- `BELFORT_MAX_ORDERS_PER_DAY`
- `BELFORT_GLOBAL_COOLDOWN_SECONDS`
- `BELFORT_SYMBOL_COOLDOWN_SECONDS`
- `BELFORT_MIN_HOLD_SECONDS`
- `BELFORT_TURNOVER_BUDGET_PCT`
- `BELFORT_MAX_SYMBOL_EXPOSURE_PCT`
- `BELFORT_MAX_TOTAL_EXPOSURE_PCT`
- `BELFORT_MAX_ACTIVE_POSITIONS`
- `BELFORT_COST_EDGE_RATIO_LIMIT`

### Promotion flow
1. Research campaign runs sweeps of candidate configs
2. Best candidate promoted via `/belfort/readiness/reset` (records baseline snapshot)
3. Current strategy tracked against baseline — drift detected in `/belfort/diagnostics`

### Live trading preparation doctrine
Belfort is currently sim + paper trading. Live trading is not unlocked on a schedule — it is earned when:
- Readiness scorecard consistently passes all gates
- Risk controls are real (stop-loss, position sizing, drawdown limits)
- Trade costs and brokerage costs are modeled realistically
- Performance is measurable, explainable, and auditable
- Market scanning and catalyst awareness are incorporated
- Operator has reviewed and accepted the autonomy grant

No live money is deployed until this preparation is complete and documented.

---

## 6. Research and campaign system

### Packages
- `research/` — `candidate_queue.py`, `campaign_runner.py`, `campaign_state.py`, `campaign_brief.py`
- `scripts/run_campaign.py`, `scripts/run_research.py`

### Campaign lifecycle
1. Supervisor triggers campaign when research threshold crossed
2. Campaign state persisted in `data/campaigns/{campaign_id}/state.json`
3. Campaign brief written to `data/campaigns/{campaign_id}/brief.json` and `brief.md`
4. Completed candidates written to candidate queue
5. Operator reviews via neighborhood or Peter command

### Stop conditions (5)
Hard failure, drawdown, win-rate regression, expectancy collapse, regime mismatch

### Lock safety
`data/campaigns/.campaign.lock` — prevents concurrent campaign runs

---

## 7. Intended platform capabilities

These are capabilities currently implemented for Belfort that are **intended** to be reusable across future specialist houses. They are Belfort-specific implementations today — not generic frameworks. Generalization should happen when a second house actually needs them, not speculatively.

| Capability | Current module | Current state | Intended reuse pattern |
|---|---|---|---|
| Readiness scorecard | `app/routes/belfort_readiness.py` | Belfort-specific gates | n-gate pass/fail health check for any house |
| Learning verdict engine | `app/routes/belfort_learning.py` | Belfort-specific metrics | Performance verdict for any house that tracks outcomes over time |
| Diagnostics sub-reports | `app/routes/belfort_diagnostics.py` | Belfort-specific | Drift detection, path analysis, threshold proximity pattern |
| Campaign orchestration | `research/campaign_runner.py` | General-purpose | Parameter sweep or optimization runs for any house |
| Candidate queue | `research/candidate_queue.py` | General-purpose | Operator review queue for any house producing candidates |
| LMHelper / Cost Warden | `app/cost_warden.py` | General-purpose (live) | All agents that need LM calls |
| Agent state persistence | `observability/`, `data/agent_state/` | General-purpose (live) | All agents that need cross-restart state |
| Telemetry | `observability/`, `data/telemetry/` | General-purpose (live) | Per-run performance data for any house |

**Rule:** Do not generalize the Belfort-specific implementations until a second house needs them. Premature abstraction is a non-goal.

---

## 8. Data persistence

| File | Purpose | Append-only? |
|---|---|---|
| `data/portfolio.json` | Positions, cash, trade history | No (updated in place) |
| `data/strategy_config.json` | Current strategy parameters | No |
| `data/baseline_adoption_record.json` | Snapshot at last strategy reset | No |
| `data/supervisor_state.json` | Supervisor loop state | No |
| `data/event_log.jsonl` | Primary audit trail | Yes |
| `data/research_ledger/ledger.jsonl` | Research run history | Yes |
| `data/warden_usage.jsonl` | LM usage log | Yes |
| `data/agent_state/mr_belfort.json` | Belfort live state | No |
| `data/learning_history.jsonl` | Learning summary history | Yes |
| `data/campaigns/{id}/` | Per-campaign state + brief | Yes (new dir per campaign) |

---

## 9. Neighborhood technical design

- Single-file HTML/CSS/JS: `app/analog_cockpit.py` served by `app/routes/neighborhood.py`
- Served at `/neighborhood` (GET returns full HTML page)
- State endpoint: `/neighborhood/state` (polled every 5s)
- Belfort view includes scanner board, catalyst desk, execution lanes, readiness checklist, adjustment desk, and activity ledger
- Guide view reads `BELFORT_HOW_IT_WORKS.md`, `BRD.md`, and `TRD.md` through `/neighborhood/docs`

---

## 10. Key design constraints

1. **No fake complexity** — don't add abstractions for hypothetical needs
2. **No Discord** — not a current goal
3. **Deterministic first** — every agent has a rule-based core before LM is added
4. **Operator in the loop** — strategy changes are proposed and require approval
5. **Minimal blast radius** — backstage services read and report; they don't mutate state casually
6. **Stable ports** — do not drift from 8001 (backend) / 8502 (UI)
7. **Append-only audit trails** — event log and research ledger are never truncated
8. **Layer discipline** — each layer owns its responsibilities; don't collapse adjacent layers
9. **Houses earned, not declared** — UI real estate for agent identities tracks real maturity
