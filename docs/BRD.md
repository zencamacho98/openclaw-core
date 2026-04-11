# Business Requirements Document — The Abode
*Last updated: 2026-04-10*

---

## 1. What is The Abode?

The Abode is a home for AI agents that trade, research, and watch over themselves.

The central experience is:
- **You talk to Peter.** Peter is the front door. He tells you what matters.
- **You watch Belfort trade.** Belfort runs a mock trading strategy, tracks his own performance, and triggers research when the strategy is slipping.
- **The system monitors itself.** Backstage agents (Supervisor, Checker, Custodian, Sentinel, Warden) keep things running without requiring constant operator attention.

The goal is not raw performance dashboards. The goal is a calm, readable, understandable system — one a normal user can glance at and know what is happening.

---

## 2. Who uses it?

**Primary user: operator/owner**
- Wants to understand what Belfort is doing without reading code
- Wants to approve or reject strategy changes when prompted
- Wants to trust the system is monitoring itself

**Secondary user: developer/builder**
- Needs to inspect raw state, configure parameters, trigger runs manually
- Uses the dev dashboard (Streamlit) and direct API calls
- Comfort level: high technical familiarity

---

## 3. Surfaces

### 3.1 Neighborhood (primary user-facing layer)
URL: `http://localhost:8502` (served via FastAPI at `/neighborhood`)

- Pixel-art community visual with clickable houses
- Each house → resident panel with glanceable status
- Peter's house: conversation + current situation summary
- Belfort's house: trading status, position, P&L, research state, readiness scorecard, learning verdict, diagnostics
- Backstage houses: Supervisor, Custodian, Test Sentinel, Cost Warden
- Refreshes automatically every 5 seconds
- Calm, compact, plain-English first

### 3.2 Dev Dashboard (secondary/control surface)
URL: `http://localhost:8502` (Streamlit, same port, or port 8502)

- Raw state panels, test controls, campaign management
- Fallback and advanced control surface — not primary UX
- Full portfolio view, agent state, cost warden usage

### 3.3 Backend API
URL: `http://127.0.0.1:8001`

- FastAPI; powers both surfaces
- All state reads, loop control, agent commands, research triggers

---

## 4. Core User Workflows

### 4.1 Watching Belfort trade
**User opens Belfort's house → sees:**
- Trading ON/OFF
- Current position (or "flat")
- Cash, P&L, trade count
- Last trade summary
- Regime label (what kind of market)

**Result:** User understands current state without reading logs.

### 4.2 Understanding Belfort's health
**User sees in Belfort panel:**
- Readiness scorecard (8 gates, pass/fail)
- Learning verdict: Continue / Monitor / Tune / Research / Pause
- Diagnostics: strategy drift from baseline, expectancy path, trigger pressure

**Result:** User knows if Belfort is performing well or slipping.

### 4.3 Reviewing a research candidate
**When Belfort triggers research:**
- Supervisor runs a campaign, generates candidate configs
- Candidate appears in queue with performance summary
- User sees prompt in Peter panel or Belfort panel: "Research found a candidate — review?"
- User approves or rejects

**Result:** Strategy only changes with operator sign-off.

### 4.4 Talking to Peter
**User types a question or command in Peter's panel:**
- Peter reads system state, gives plain-English summary
- Peter can run: research review, status check, readiness report, diagnostics, sentiment check
- Peter delegates to other agents; reports back

**Result:** Front-door experience — user doesn't need to know which endpoint to call.

### 4.5 Operator override
**Dev dashboard or direct API:**
- `/supervisor/enable`, `/supervisor/disable` — start/stop research loop
- `/belfort/readiness/reset` — reset baseline after promoting a strategy
- `/sentinel/run` — run targeted tests before patching
- `/custodian/check` — runtime health audit

---

## 5. What success looks like

| Goal | Success signal |
|---|---|
| User understands state at a glance | Neighborhood panel loads in < 2s, readable without tooltips |
| Belfort's performance is tracked | Trade count, P&L, expectancy, win rate always current |
| Weak strategies surface early | Soft trigger fires before hard failure threshold is crossed |
| Strategy changes require approval | No config change applies without operator confirmation |
| LM costs stay bounded | Cheap-tier model handles routine tasks; strong-tier used sparingly |
| System monitors itself | Backstage agents run without operator-initiated commands |
| Developer can audit everything | Event log, research ledger, telemetry are append-only and queryable |

---

## 6. What The Abode is NOT

- Not a live trading system (mock only)
- Not a high-frequency strategy engine
- Not a Discord bot (not a current goal)
- Not an autonomous agent with unreviewed strategy authority
- Not a real-time market data subscriber

---

## 7. Design principles

1. **Plain English over internal jargon** — "Trading OFF" not "loop_enabled: false"
2. **Deterministic core first** — facts before LM interpretation
3. **Operator in the loop** — strategy changes are proposed, not applied automatically
4. **Calm, stable UI** — no stutter, no flash, no unnecessary refreshes
5. **Minimal surface area** — don't build features that aren't in the core user loop
