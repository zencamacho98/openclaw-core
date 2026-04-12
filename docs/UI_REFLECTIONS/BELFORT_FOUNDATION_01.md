# UI Reflection Contract — BELFORT-FOUNDATION-01

This document maps every new backend truth introduced by BELFORT-FOUNDATION-01 to the
existing Abode UI surfaces. It defines what each surface must show, what it must keep
separate, and what it must never do.

---

## Critical Separation Rule

**Mode** and **readiness_level** must always be presented as two distinct pieces of information.
They must never be merged into a single status field, badge, or label.

| Field              | Meaning                                 | Example value         |
|--------------------|-----------------------------------------|-----------------------|
| `mode`             | What Belfort is currently doing         | `shadow`              |
| `readiness_level`  | What advancement Belfort has earned     | `OBSERVATION_ONLY`    |

A build in `shadow` mode on IEX data must show:
- **Current mode:** Shadow
- **Current readiness claim:** Observation Only

Never: "Shadow / Observation Only" merged into one status chip.

---

## Data source

All UI surfaces read from `data/belfort/preflight.json` via `observability/belfort_summary.py`.
No surface imports from `app.*` directly.

```
preflight.json → observability/belfort_summary.read_belfort_preflight()
              → peter/handlers.handle_belfort_status()
              → Peter command response / neighborhood tile / panel
```

---

## Preflight JSON fields (source of truth)

```json
{
  "written_at":              "ISO 8601 UTC",
  "mode":                    "observation | shadow | paper | live",
  "broker_environment":      "paper | live | not_configured",
  "paper_credentials":       true | false,
  "data_lane":               "IEX_ONLY | SIP_CONSOLIDATED | UNKNOWN",
  "session_type":            "regular | pre_market | after_hours | closed",
  "universe":                ["SPY", "QQQ", "AAPL", "MSFT", "TSLA"],
  "readiness_level":         "NOT_READY | OBSERVATION_ONLY | PAPER_READY | SHADOW_COMPLETE | LIVE_ELIGIBLE",
  "can_advance_to":          "shadow | paper | live | null",
  "advancement_blocked_by":  "reason string | null",
  "observation_ticks_today": 0,
  "last_tick_at":            "ISO 8601 UTC | null"
}
```

---

## Surface 1: Peter command response (`belfort status`)

**Trigger:** User types `belfort status`, `belfort mode`, `belfort preflight`, `observation status`

**Handler:** `peter/handlers.handle_belfort_status()`

**Required content:**
- Current mode (plain English, not enum value)
- Current readiness claim (separate line or sentence from mode)
- Data lane (`IEX_ONLY` / `SIP_CONSOLIDATED` / `UNKNOWN`)
- Session type
- Observation ticks today
- Advancement status (can advance to X, or blocked by reason)

**Example response:**
```
Current mode: Observation — watching market data, no execution.
Current readiness claim: Observation only — IEX data, cannot claim higher.
Data lane: IEX_ONLY. Session: regular.
Observation ticks today: 12 (last at 2026-04-11T14:22:00+00:00).
Blocked: IEX_ONLY data lane — SIP required for higher readiness claims.
```

**Must not:**
- Merge mode and readiness into one line like "Observation / OBSERVATION_ONLY"
- Show raw enum names (`OBSERVATION_ONLY`) without a plain-English label
- Reference internal file paths or module names

---

## Surface 2: Belfort right-side panel (dashboard detail view)

**Location:** Belfort house detail panel (existing Belfort dashboard tab)

**Fields to surface:**

| Label                   | Field                          | Notes                                     |
|-------------------------|--------------------------------|-------------------------------------------|
| Operating Mode          | `mode`                         | Plain English, not enum                   |
| Readiness Claim         | `readiness_level`              | Plain English, not enum. Separate row.    |
| Data Lane               | `data_lane`                    | IEX / SIP / Unknown                       |
| Session                 | `session_type`                 | Regular / Pre-market / After-hours / Closed |
| Broker Environment      | `broker_environment`           | Paper / Live / Not configured             |
| Paper Credentials       | `paper_credentials`            | Yes / No                                  |
| Ticks Today             | `observation_ticks_today`      | Count                                     |
| Last Tick               | `last_tick_at`                 | Human-readable time, or "never"           |
| Can Advance To          | `can_advance_to`               | Next mode or "—"                          |
| Advancement Blocked By  | `advancement_blocked_by`       | Reason string or "—"                      |

**Must not:**
- Show both `mode` and `readiness_level` in the same chip/badge
- Show `OBSERVATION_ONLY` without explaining it in plain English
- Hide `advancement_blocked_by` when it is non-null

---

## Surface 3: Belfort neighborhood/house tile

**Location:** Neighborhood main view, Belfort house tile

**Compact display (glanceable):**

Line 1: Mode indicator — `Observation` / `Shadow` / `Paper` / `Live`
Line 2: Readiness indicator — `Observation Only` / `Paper Ready` / etc. (distinct from mode)

**Rules:**
- Both lines must be visible without interaction
- They must appear on separate visual rows, never concatenated
- If `written_at` is more than 5 minutes old, show a staleness warning ("Preflight stale")
- If `last_tick_at` is null, show "No ticks yet"

**Must not:**
- Use a single combined field like "Observation (Observation Only)"
- Show raw Python enum values (e.g., `OBSERVATION_ONLY`)

---

## Surface 4: Full dashboard / dev control surface

**Location:** Dashboard tab (existing dev/fallback surface)

**All fields exposed.** This surface may show technical detail including:
- Raw `data_lane` value
- `broker_environment` and `paper_credentials` bool
- `universe` list
- `written_at` timestamp
- All readiness advancement detail

**Still must:**
- Show mode and readiness_level as separate labeled fields even in the detailed view
- Label `IEX_ONLY` clearly so a non-technical user understands it as "single-exchange only"

---

## IEX cap — UI implication

When `data_lane == "IEX_ONLY"`:
- `readiness_level` is capped at `OBSERVATION_ONLY` by the backend
- The UI should surface the cap explanation from `advancement_blocked_by`
- The UI must NOT present IEX data as equivalent to SIP for readiness claims
- If the user is in `shadow` mode but `readiness_level == OBSERVATION_ONLY`, both facts must be visible:
  - Mode: Shadow (what we're doing)
  - Readiness: Observation Only (what we've earned — capped by IEX lane)

---

## Staleness handling

The preflight snapshot is written by `app/belfort_observer.py` on each tick.
If no tick has run, `written_at` will be null and all surfaces should show a "not yet observed" state, not zeros or errors.

| Condition                          | UI treatment                             |
|------------------------------------|------------------------------------------|
| `written_at` is null               | "No observation data yet"                |
| `observation_ticks_today` == 0     | "No ticks today"                         |
| `last_tick_at` is null             | "Never" (not an error)                   |
| Snapshot > 5 min old               | Optional staleness indicator             |
| `readiness_level == "NOT_READY"`   | Neutral — not an error state             |

---

## Not in scope for BELFORT-FOUNDATION-01

The following are NOT surfaced by this block and must not be added to UI before they exist in the backend:

- Order placement controls (paper or live)
- Signal evaluation display
- Risk guardrail status table
- Mode advancement controls (buttons to advance Belfort to shadow/paper/live)
- Real-time quote streaming
- P&L or position data

These belong to a future block after BELFORT-FOUNDATION-01 is stable.
