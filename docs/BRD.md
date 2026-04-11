# Business Requirements Document — The Abode
*Last updated: 2026-04-11 (vision reset)*

---

## 1. What is The Abode?

THE ABODE is a visual operating environment for an AI workforce.

It is a living neighborhood of specialized autonomous agents that own real workflows, can improve over time, and are built to create economic value or materially multiply productivity. The neighborhood UI is the true product surface — not a cosmetic wrapper. Houses represent real specializations with measurable ownership and outcomes.

The central experience is:
- **You talk to Peter.** Peter is the front door. He tells you what matters, delegates to the workforce, and reports back.
- **You watch Belfort work.** Belfort runs a trading research operation — mock trading today, real trading when readiness is earned.
- **The workforce monitors itself.** Backstage operating services (Supervisor, Checker, Custodian, Sentinel, Warden) keep things running without constant operator attention.

The long-term goal is to move from supervised, trustworthy agent work into self-sustaining, profitable, potentially sellable agent businesses with increasing earned autonomy.

See `docs/vision/PROJECT_VISION.md` for the full strategic framing.

---

## 2. Who uses it?

**Primary user: operator/owner**
- Wants to understand what the workforce is doing without reading code
- Wants to approve or reject strategy changes when prompted
- Wants the system to monitor itself and surface what matters

**Secondary user: developer/builder**
- Needs to inspect raw state, configure parameters, trigger runs manually
- Uses the dev dashboard (Streamlit) and direct API calls
- Comfort level: high technical familiarity

---

## 3. Surfaces

### 3.1 Neighborhood (primary product surface)
URL: `http://localhost:8001/neighborhood` (served from FastAPI backend at port 8001)

- Pixel-art community visual with clickable houses
- Each house represents a real agent with real ownership and real outcomes
- Peter's house: conversation, current situation summary, key decisions pending
- Belfort's house: trading status, position, P&L, research state, readiness scorecard, learning verdict, diagnostics
- Backstage operating services: currently visible in an ops row with expandable panels. Goal: secondary presences, not primary houses equal in weight to Peter and Belfort.
- Refreshes automatically every 5 seconds
- Calm, compact, plain-English first

Rule: visuals reflect real system state. Animation and lore must not substitute for honest performance.

### 3.2 Dev Dashboard (secondary/control surface)
URL: `http://localhost:8502` (Streamlit)

- Raw state panels, test controls, campaign management
- Fallback and advanced control surface — not primary UX
- Full portfolio view, agent state, cost warden usage

### 3.3 Backend API
URL: `http://127.0.0.1:8001`

- FastAPI; powers both surfaces
- All state reads, loop control, agent commands, research triggers
- Neither surface writes data directly — everything routes through the API

---

## 4. Housed agents vs backstage operating services

### Housed agents (earn a named house in the neighborhood)
These meet the house eligibility criteria: durable specialized role, measurable outcomes, some autonomy, standalone value, real workflow ownership. See `docs/vision/HOUSE_ELIGIBILITY.md`.

- **Peter** — operator-facing coordinator, reporter, front door
- **Mr Belfort** — trading research, prototype revenue house, proving ground for learning infrastructure

Planned:
- **Frank Lloyd** — construction house: agent and house creation, modification, and evolution

### Backstage operating services (infrastructure, not houses)
These are essential but do not own a business domain with independent value:

- **Loop Supervisor** — research campaign orchestration, bounded execution
- **Loop Checker** — audit, suspicious-pattern detection
- **Custodian** — runtime health, process monitoring
- **Test Sentinel** — patch-safety validation, targeted test runs
- **Cost Warden** — LM routing policy, budget discipline, usage logging

A backstage service can earn house status if it matures into a real specialized workflow owner with independent value. See eligibility criteria.

---

## 5. Core User Workflows

### 5.1 Watching Belfort trade
**User opens Belfort's house → sees:**
- Trading ON/OFF
- Current position (or "flat")
- Cash, P&L, trade count
- Last trade summary
- Regime label (what kind of market)

**Result:** User understands current state without reading logs.

### 5.2 Understanding Belfort's health
**User sees in Belfort panel:**
- Readiness scorecard (8 gates, pass/fail)
- Learning verdict: Continue / Monitor / Tune / Research / Pause
- Diagnostics: strategy drift from baseline, expectancy path, trigger pressure

**Result:** User knows if Belfort is performing well or slipping.

### 5.3 Reviewing a research candidate
**When Belfort triggers research:**
- Supervisor runs a campaign, generates candidate configs
- Candidate appears in queue with performance summary
- User sees prompt in Peter panel or Belfort panel: "Research found a candidate — review?"
- User approves or rejects

**Result:** Strategy only changes with operator sign-off.

### 5.4 Talking to Peter
**User types a question or command in Peter's panel:**
- Peter reads system state, gives plain-English summary
- Peter can run: research review, status check, readiness report, diagnostics, sentiment check
- Peter delegates to other agents; reports back

**Result:** Front-door experience — user doesn't need to know which endpoint to call.

### 5.5 Operator override
**Dev dashboard or direct API:**
- `/supervisor/enable`, `/supervisor/disable` — start/stop research loop
- `/belfort/readiness/reset` — reset baseline after promoting a strategy
- `/sentinel/run` — run targeted tests before patching
- `/custodian/check` — runtime health audit

---

## 6. What success looks like

| Goal | Success signal |
|---|---|
| User understands state at a glance | Neighborhood panel loads in < 2s, readable without tooltips |
| Belfort's performance is tracked | Trade count, P&L, expectancy, win rate always current |
| Weak strategies surface early | Soft trigger fires before hard failure threshold is crossed |
| Strategy changes require approval | No config change applies without operator confirmation |
| LM costs stay bounded | Cheap-tier model handles routine tasks; strong-tier used sparingly |
| System monitors itself | Backstage services run without operator-initiated commands |
| Developer can audit everything | Event log, research ledger, telemetry are append-only and queryable |
| Workforce requires less babysitting over time | Operator attention shifts from routine to strategic |

---

## 7. What The Abode is NOT

- Not a live trading system yet — live deployment requires earned readiness, risk controls, and measurable performance proof. The current mock-trading state is a stage, not a ceiling.
- Not a high-frequency strategy engine
- Not a Discord bot (not a current goal)
- Not a flat list of scripts that happen to call LLMs
- Not a system where every subsystem gets a named public-facing house identity
- Not a simulation with theater substituting for real performance

---

## 8. Design principles

1. **Plain English over internal jargon** — "Trading OFF" not "loop_enabled: false"
2. **Deterministic core first** — facts before LM interpretation
3. **Operator in the loop** — strategy changes are proposed, not applied automatically
4. **Calm, stable UI** — no stutter, no flash, no unnecessary refreshes
5. **Minimal surface area** — don't build features that aren't in the core user loop
6. **Houses must be earned** — UI real estate reflects real agent maturity, not aspirational branding
7. **Autonomy escalates with evidence** — no agent gets expanded authority by declaration
8. **Truthful visuals** — the neighborhood shows real state; it does not hide weakness behind animation
