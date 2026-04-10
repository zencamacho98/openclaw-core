# THE ABODE

This repository builds **THE ABODE**.

See:
- @docs/abode_identity.md
- @docs/abode_runtime.md
- @docs/abode_product_rules.md
- @docs/abode_cost_policy.md

## Skills
- @skills/abode-neighborhood-pass/SKILL.md
- @skills/abode-role-boundary-check/SKILL.md
- @skills/abode-delivery-report/SKILL.md

## Working style
- Complete one coherent vertical slice per prompt.
- Bundle only closely related tasks on the same surface.
- Reuse existing backend/control flows whenever possible.
- Prefer minimal edits over broad rewrites.
- Stop once the slice is complete enough to pause.

## Hard non-goals
- Do not rush Discord.
- Do not add fake complexity.
- Do not broaden scope casually.
- Do not replace deterministic cores with vague LM behavior.
- Do not duplicate the dev/control UI inside the neighborhood unless it is part of the core user loop.

## Delivery style
After each implementation block, always report:
1. what changed
2. files added/edited
3. existing endpoints/control flows reused
4. what was deliberately left out
5. remaining gaps
6. exact next recommended block
