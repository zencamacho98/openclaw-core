# Abode identity and roles

## System name
The overall system/community is **THE ABODE**.

## Core vision
THE ABODE is a visual operating environment for an AI workforce — a living neighborhood of specialized agents that own real workflows and are built toward creating economic value or materially multiplying productivity.

## Houses
Agents that have earned a named house. They own a durable specialized domain, produce measurable outcomes, and operate with some autonomy.

- **Peter** = operator-facing front door, coordinator, delegator, reporter
- **Mr Belfort** = trading research / mock trading / supervised optimization worker / prototype revenue house
- **Frank Lloyd** = *(planned)* construction house — workforce creation, modification, evolution

## Operating services
Infrastructure that keeps the neighborhood healthy, safe, and cost-efficient. These are backstage services — not houses. They do not get front-door identities.

- **Loop Supervisor** = bounded execution coordinator / research campaign orchestrator
- **Loop Checker** = audit / suspicious-pattern finder / read-only watchdog
- **Custodian** = runtime health / environment drift / process liveness monitor
- **Test Sentinel** = targeted test runner / patch-safety validator
- **Cost Warden** = LM routing discipline / budget awareness / usage logging

## Role boundaries
- Peter is the front door. He reads from agents and reports upward.
- Peter does not execute Belfort's trading logic, run checks, or own operating service responsibilities.
- Belfort owns trading, research, readiness, and supervised optimization. Belfort is not a generic coordinator.
- Operating services are backstage. Their outputs surface through Peter or the dev dashboard — not as first-class neighborhood identities.
- A backstage service becomes a house only when it meets the house eligibility criteria (see `docs/vision/HOUSE_ELIGIBILITY.md`).
