---
name: abode-role-boundary-check
description: Use this when designing or changing agents, UI copy, or workflows in THE ABODE. Prevents role collapse and keeps the product architecture clear.
---

# Abode Role Boundary Check

Use this skill whenever a change could blur responsibilities between Peter, Belfort, and backstage agents.

## Hard boundaries
- Peter = main operator-facing interface, coordinator, delegator, reporter
- Belfort = trading research / mock trading / research worker
- Loop Supervisor = bounded execution coordinator
- Loop Checker = audit / suspicious-pattern finder
- Custodian = runtime health
- Test Sentinel = test/validation checker
- Cost Warden = LM routing and budget discipline

## Checks
Before finalizing any change, verify:
- Peter is not absorbing Belfort's identity
- Peter is not replacing supervisor/checker roles
- Belfort is not becoming a generic coordinator
- operations agents remain quieter and backstage
- the neighborhood still feels like a product, not a dev console

## Preferred behavior
- front-door interactions go through Peter
- trading/research interactions belong to Belfort
- health/checking/cost remain secondary and supportive

## Output
State clearly:
- whether role boundaries stayed intact
- any boundary risk introduced
- the smallest fix if a role started collapsing
