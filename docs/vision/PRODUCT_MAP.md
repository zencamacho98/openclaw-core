# Product Map — The Abode
*The surfaces, their hierarchy, and what each is for.*

---

## Surface hierarchy

```
PRIMARY:    Neighborhood UI
SECONDARY:  Dev Dashboard (Streamlit)
INTERNAL:   Backend API
```

The neighborhood is the product. The dev dashboard is for developers and advanced control. The API is the plumbing behind both.

---

## Neighborhood UI

**URL**: `http://localhost:8502` → `/neighborhood` (served from FastAPI backend at port 8001)  
**Audience**: operator/owner — normal user, not developer  
**Design intent**: glanceable, calm, plain English, truthful

What the neighborhood must do:
- Show the workforce at a glance — who is active, what they are doing, whether they are healthy
- Let the user talk to Peter without opening a separate interface
- Let the user understand Belfort's trading state without reading logs
- Surface important decisions (e.g., research candidate review) without burying them
- Expand naturally as new houses are added — the visual space should reflect real workforce growth

What the neighborhood must not do:
- Substitute animation or visual polish for real system state
- Show backstage operating services as first-class presences equal to houses
- Duplicate the full dev dashboard capability inside the neighborhood

---

## Dev Dashboard

**URL**: `http://localhost:8502` (Streamlit)  
**Audience**: developer/builder  
**Design intent**: full control, raw state, no constraints

What the dev dashboard is for:
- Raw agent state inspection
- Manual test runs, campaign triggers, parameter overrides
- Cost/usage analysis
- Deep debugging without UX constraints

The dev dashboard is the escape hatch. It should not be the primary experience.

---

## Backend API

**URL**: `http://127.0.0.1:8001`  
**Audience**: internal (powers both surfaces)

All state reads, agent commands, loop control, research triggers, and data writes go through this API. Neither the neighborhood nor the dev dashboard should write data directly — everything routes through the API.

---

## Future product surface

Peter should eventually be reachable through personal channels (WhatsApp, Discord) not just the neighborhood.  
This is a future direction — do not build it until the neighborhood is stable and Peter's command surface is proven.
