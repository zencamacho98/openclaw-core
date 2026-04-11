# House Eligibility Standard — The Abode
*A house is not given. It is earned.*

---

## The five criteria

Something earns a house only if it meets all five:

1. **Durable specialized role**
   It owns a specific domain of work that doesn't belong to any other agent. Its responsibilities are distinct and bounded.

2. **Measurable outcomes**
   Its performance can be tracked over time. There is a clear answer to: "is this house doing well or poorly?"

3. **Operates with some autonomy**
   It can execute its core workflow without operator direction for every step. Supervision is periodic, not continuous.

4. **Potentially sellable or force-multiplying**
   Its function has standalone value beyond this specific installation — either as a product, a service, or a clear multiplier on the profitability or reliability of the wider system.

5. **Owns a real workflow or business function**
   It does real work that produces real outputs, not just monitoring, reporting, or routing another agent's work.

---

## Current status

| Candidate | Qualifies? | Notes |
|---|---|---|
| Peter | Yes (conditional) | Owns operator communication, coordination, reporting. Standalone value as chief-of-staff interface is credible but currently aspirational — present implementation is a command-routing chat interface. Qualifies on role clarity and domain ownership; standalone sellability depends on future channel integrations. |
| Mr Belfort | Yes (prototype) | Owns trading/research domain. Outcomes measurable. Revenue candidacy established. Live deployment pending earned readiness. |
| Frank Lloyd | Conditional (planned) | Qualifies if it can accept a spec, execute a build, and return a working artifact autonomously. Currently not built. |
| Loop Supervisor | No | Orchestration service. Does not own a business domain. Outputs (campaign results) belong to Belfort. |
| Loop Checker | No | Audit service. Read-only pattern finding. No standalone value as a product. |
| Custodian | No | Runtime health service. Valuable but infrastructure. |
| Test Sentinel | No | Patch-safety tool. Not a workflow owner. |
| Cost Warden | No | Routing policy enforcer. Pure infrastructure. |

---

## Promotion path

A backstage service can eventually earn house status if it:
- Develops a workflow that produces outputs with measurable value independent of other houses
- Reaches a level of autonomy where it operates without constant operator guidance
- Has a plausible standalone identity: someone would pay for this capability separately

If a backstage service starts developing those properties, define its house identity before building the UI — not after.
