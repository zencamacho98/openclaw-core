# Abode cost and LM policy

## Architecture rule
All major agents in The Abode may eventually have OpenRouter-backed LM support.

But the design rule is always:
- deterministic core first
- LM layer second
- explicit guardrails always

## Mental model
- bones = deterministic checks / rules / data access / safe actions
- brain = LM-backed summarization / interpretation / recommendation / classification
- guardrails = bounded context, allowlists, confirmation for risky actions, cost-aware routing

## Routing tiers
Defined in `app/cost_warden.py`:
- `deterministic` — rule-based; no LM needed (health checks, test runs, data lookups)
- `cheap` — routine summarization, intent parsing, bounded analysis → `CHEAP_MODEL` (default: `openai/gpt-4o-mini`)
- `strong` — architecture review, safety boundaries, complex tradeoffs → `STRONG_MODEL` (default: `anthropic/claude-sonnet-4-6`)

## Routing policy
Default order:
1. deterministic first
2. cheap model for bounded summarization / interpretation / low-risk implementation help
3. stronger model only for architecture, hard debugging, risky review, or ambiguous tradeoffs

## Cost rules
- do not make expensive models the default
- route through shared policy/helpers where possible
- avoid private one-off LM clients that bypass logging/routing
- prefer bounded context and small prompts
- keep advanced cost details secondary in the user-facing product

## Pattern for adding LM support to an agent
Use `app/cost_warden.LMHelper`:

```python
from app.cost_warden import LMHelper

helper = LMHelper("my_agent", "health_explain", max_tokens=200)
result = helper.call(system="Explain findings in plain English.", user=data_str)
if result.ok:
    explanation = result.content
else:
    explanation = f"[LM unavailable: {result.error}]"  # graceful fallback
```

**Do NOT replace deterministic cores with vague LM behaviour.**
**Do NOT make expensive models the default path.**
