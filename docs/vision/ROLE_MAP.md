# Role Map — The Abode
*Who lives here, what they own, and where they sit in the architecture.*

---

## Layer model

```
[ Experience Layer ]
  Neighborhood UI — primary product surface
  Dev Dashboard  — advanced/fallback surface

[ Executive / Control Layer ]
  Peter          — user-facing front door, coordinator, reporter

[ Specialist House Layer ]
  Mr Belfort     — trading research / prototype revenue house
  Frank Lloyd    — (planned) construction house / workforce creation and evolution

[ Operating Services Layer ]
  Loop Supervisor — bounded execution coordinator
  Loop Checker    — audit / suspicious-pattern finder
  Custodian       — runtime health monitor
  Test Sentinel   — patch-safety validator
  Cost Warden     — LM routing and budget discipline
```

---

## Role table

| Role | Type | Layer | Status | Core ownership |
|---|---|---|---|---|
| Peter | House (interface) | Executive/Control | Live | Operator communication, delegation, reporting |
| Mr Belfort | House (specialist) | Specialist | Live — prototype | Mock trading, research, readiness, learning |
| Frank Lloyd | House (specialist) | Specialist | Planned | Construction house — agent/house creation, modification, evolution |
| Loop Supervisor | Operating service | Operating Services | Live | Research campaign orchestration, bounded execution |
| Loop Checker | Operating service | Operating Services | Live | Audit, suspicious-pattern detection |
| Custodian | Operating service | Operating Services | Live | Runtime health, process liveness |
| Test Sentinel | Operating service | Operating Services | Live | Patch-safety validation, targeted test runs |
| Cost Warden | Operating service | Operating Services | Live | LM routing policy, usage logging, budget awareness |

---

## Hard boundaries

- Peter reads from agents and reports upward. Peter does not execute Belfort's trading logic or run checks.
- Belfort owns trading, research, readiness, and learning. Belfort is not a generic coordinator.
- Supervisor/Checker/Custodian/Sentinel/Warden are backstage. They are not the front door. Their outputs surface through Peter or the dev dashboard — not as first-class neighborhood identities unless explicitly promoted to house status.
- Operating services must not absorb specialist house responsibilities.
- Specialist houses must not absorb operating service responsibilities.

---

## Frank Lloyd (planned)

Frank Lloyd is the Abode's construction house. It will handle: creating new agents, modifying existing agents, duplicating house templates, and evolving the workforce over time.

The goal is to stop the current flow of: "talk to ChatGPT → copy into Claude Code → manually build."  
Instead: talk to Peter → Peter routes to Frank Lloyd → Frank Lloyd handles construction.

Frank Lloyd earns its house when it can: accept a defined spec, execute a build, and return a working artifact — with the operator reviewing rather than directing every step.
