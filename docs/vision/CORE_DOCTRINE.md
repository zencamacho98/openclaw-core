# Core Doctrine — The Abode
*These rules govern design decisions across all layers of the system.*

---

1. **Workforce first.**
   The Abode is an AI workforce, not a dashboard. Every build decision should ask: does this make the workforce more capable, more trustworthy, or more autonomous?

2. **The neighborhood is the product surface.**
   Houses and characters are not decoration. They express specialization, ownership, activity, relationships, health, and growth. Visuals must reflect real system state.

3. **Peter stays clean and lightweight.**
   Peter is the front door, chief of staff, coordinator, and reporter. Heavy management logic, governance, and execution belong behind him — not collapsed into Peter as a monolith.

4. **A house must be earned.**
   Something earns a house only if it: performs a durable specialized role, has measurable outcomes, can act with some autonomy, is potentially sellable or has clear standalone value, and owns a real workflow or business function. See `HOUSE_ELIGIBILITY.md`.

5. **Backstage services are not automatically houses.**
   Custodian, Test Sentinel, Cost Warden, Loop Checker, and similar operating services exist to keep the neighborhood healthy and safe. They are infrastructure — not houses — unless they mature into real specialized workflow owners with independent value.

6. **Learning must be real.**
   "Learning" cannot mean prompt growth, notes, or self-reflection theater. It means measurable improvement in future performance, validated by observable outcomes.
   The current system implements **supervised optimization**: deterministic verdicts trigger operator-approved research campaigns; the operator promotes better configs. That is a meaningful and honest form of improvement, but it is not autonomous learning. Autonomous improvement without operator approval is a future milestone, not the current state.

7. **Autonomy must be earned.**
   The system moves from supervised output to increasing autonomy only when evidence and safeguards justify it. No house gets autonomous authority by declaration.

8. **Every serious action must be explainable and auditable.**
   If an agent takes an action with real consequences, the reasoning must be inspectable after the fact. Append-only audit trails are non-negotiable.

9. **Value is broader than direct revenue.**
   Some houses will make money directly. Others will be force multipliers — materially improving profitability, reliability, build speed, governance, or scalability. Both count.

10. **The system should become less babysit-heavy over time.**
    The goal is a workforce that requires decreasing operator attention as trust is established, not increasing complexity that demands more hand-holding.
