# Documentation Alignment Notes — Vision Reset 2026-04-11
*Records what was misaligned, what was changed, and why.*

---

## Why this reset happened

As of 2026-04-11, the existing docs (BRD, TRD, CAPABILITY_REGISTRY, CHANGE_JOURNAL) were accurate about implementation but did not reflect the true intended direction of THE ABODE:

- The system was described as "a home for AI agents that trade, research, and watch over themselves" — too narrow, too internally focused
- Backstage operating services were called "houses" in the BRD
- No concept of house eligibility existed
- No layered architecture model existed (the TRD had three layers, not four)
- Belfort was described too narrowly — no revenue-house candidacy, no live trading preparation doctrine
- "Not a live trading system" was written as a permanent constraint, not a current state
- No autonomy escalation doctrine existed anywhere
- The Builder/Incubator concept did not appear in any doc
- The CAPABILITY_REGISTRY blended houses, services, and platform capabilities without distinction

---

## What was created

**Vision Reset Pack** in `docs/vision/`:

| File | Purpose |
|---|---|
| `PROJECT_VISION.md` | Strategic source of truth: what THE ABODE is, what it's for, where it's going |
| `CORE_DOCTRINE.md` | 10 design rules governing all build decisions |
| `ROLE_MAP.md` | Layer model, role table, hard boundaries, Builder/Incubator defined |
| `HOUSE_ELIGIBILITY.md` | The 5 criteria for earning a house; current eligibility table |
| `PRODUCT_MAP.md` | Surface hierarchy, what each surface is for, future surface direction |
| `MILESTONE_MAP.md` | Near/mid/long term direction markers; autonomy doctrine |
| `DOC_ALIGNMENT_NOTES.md` | This file |

---

## What was revised

**`docs/BRD.md`** — revised to:
- Describe THE ABODE as an AI workforce operating environment
- Separate housed agents from backstage operating services
- Fix "Backstage houses" → "Backstage operating services"
- Change "Not a live trading system" from permanent constraint to current state
- Add Belfort's revenue-house candidacy and live trading preparation doctrine
- Add house eligibility reference
- Update design principles to include workforce and autonomy framing

**`docs/TRD.md`** — revised to:
- Replace 3-layer architecture diagram with correct 4-layer model
- Separate operating services from specialist houses in the agent roles section
- Add platform capabilities section distinguishing reusable infrastructure from house-specific logic
- Clarify Peter as interface/control vs deeper orchestration logic

**`docs/CAPABILITY_REGISTRY.md`** — revised to:
- Restructure into three categories: Housed Capabilities, Backstage Operating Services, Reusable Platform Capabilities
- Add classification metadata: Category, Autonomy, Maturity, Outcome type
- Remove the flat all-agents-are-equal structure

**`docs/CHANGE_JOURNAL.md`** — appended:
- Added entry recording this vision reset as a doctrine/architecture shift, not just an implementation change

---

## What was NOT changed in this pass

- `docs/abode_identity.md` — partially updated but will need a more thorough rewrite in a future pass to reflect the 4-layer model
- `docs/abode_product_rules.md` — still accurate, not revised
- `docs/abode_runtime.md` — still accurate, not revised
- `docs/abode_cost_policy.md` — still accurate, not revised
- No feature build in this pass
- No CLAUDE.md rewrite (CLAUDE.md references the docs — the docs now reflect the correct doctrine)

---

## Remaining doc gaps

- `docs/abode_identity.md` still lists all agents without distinguishing houses from services
- No formal Belfort preparation checklist for live trading readiness
- No Builder/Incubator spec (beyond the role map reference)
- No API reference doc
- TRD does not yet have a dedicated section on earned autonomy escalation gates
