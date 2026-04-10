# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Project

Use the control script — it is the single source of truth for starting, stopping, and inspecting the services:

```bash
./scripts/ctl.sh start      # start backend + UI, wait for readiness, print URL
./scripts/ctl.sh stop       # stop repo-owned processes (safe, by PID)
./scripts/ctl.sh restart    # stop then start
./scripts/ctl.sh status     # show PIDs, health, ports, canonical URL
./scripts/ctl.sh logs       # follow both logs (Ctrl-C to stop)
```

**Canonical ports (hardwired in the script):**
- Backend : `127.0.0.1:8001` — matches `API_BASE` in `ui/dashboard.py`
- UI      : `http://localhost:8502`

**Log files** (created on first start):
- Backend : `logs/backend.log`
- UI      : `logs/ui.log`

**PID files** (created on start, deleted on stop):
- `run/backend.pid`
- `run/ui.pid`

**Note on port 8501:** A system-managed (zenca/systemd) Streamlit instance may be running on port 8501 serving older code. Do not use `http://localhost:8501`. The canonical dev UI is always `http://localhost:8502`.

No test framework or linter is configured. No `requirements.txt` exists — dependencies live only in `.venv/`.

## Architecture

This is a multi-agent task execution system with a FastAPI control plane and a Streamlit monitoring UI.

**Key layers:**

- **`app/agents/manager.py`** — Core of the system. `Agent` holds a task queue and status (`idle`/`working`). `AgentManager` is a singleton that owns named agents (`trader`, `ui_builder`). Agents are purely in-memory.

- **`app/tasks.py`** — All executable work lives here as plain functions registered in `TASK_MAP` (a `dict[str, Callable]`). Adding a new capability means writing a function and adding it to `TASK_MAP`.

- **`app/worker.py`** — `run_once()` iterates idle agents, dequeues tasks, and calls `execute_task()`, which dispatches via `TASK_MAP`. Logs each execution.

- **`app/loop.py`** — `start_loop()` spawns a daemon thread that calls `run_once()` on a configurable interval. Controlled via `/loop/start` and `/loop/stop` API endpoints.

- **`app/main.py`** — FastAPI app exposing: `GET /health`, `GET /agents`, `POST /agents/assign`, `POST /run`, `GET /logs`, `POST /loop/start`, `POST /loop/stop`.

- **`app/logger.py`** — Simple in-memory log ring buffer (last 50 entries). No persistence.

- **`ui/dashboard.py`** — Streamlit app that calls the FastAPI backend over HTTP to display agent status, assign tasks, trigger runs, and tail logs.

- **`manager.py`** (root) — Legacy file, superseded by `app/agents/manager.py`. Ignore.

**Data flow:** API endpoint → `AgentManager.assign_task()` enqueues task name → `run_once()` dequeues and executes via `TASK_MAP` → result logged to in-memory logger.

All state (agent queues, logs) is in-memory and resets on restart.

## Agent LM Architecture Rule

All major agents in The Abode may eventually have OpenRouter-backed LM support so they can be more adaptable and learn over time. The design rule is:

- **Bones** = deterministic checks / rules / data access / safe actions (always required)
- **Brain** = LM-backed summarization / interpretation / recommendation / classification (optional layer)
- **Guardrails** = bounded context, allowlists, confirmation for risky actions, cost-aware routing (always required when LM is used)

**Do NOT replace deterministic cores with vague LM behaviour.**
**Do NOT make expensive models the default path.**

**Routing tiers** (defined in `app/cost_warden.py`):
- `deterministic` — rule-based; no LM needed (health checks, test runs, data lookups)
- `cheap` — routine summarization, intent parsing, bounded analysis → `CHEAP_MODEL` (default: `openai/gpt-4o-mini`)
- `strong` — architecture review, safety boundaries, complex tradeoffs → `STRONG_MODEL` (default: `anthropic/claude-sonnet-4-6`)

**Pattern for adding LM support to an agent** (`app/cost_warden.LMHelper`):
```python
from app.cost_warden import LMHelper

helper = LMHelper("my_agent", "health_explain", max_tokens=200)
result = helper.call(system="Explain findings in plain English.", user=data_str)
if result.ok:
    explanation = result.content
else:
    explanation = f"[LM unavailable: {result.error}]"  # graceful fallback
```

## Configuration

Runtime config is in `.env` at the project root:
- `OPENROUTER_API_KEY` — used by tasks that call language models via OpenRouter
- `APP_ENV` — e.g. `dev`
- `CHEAP_MODEL` — override default cheap-tier model (default: `openai/gpt-4o-mini`)
- `STRONG_MODEL` — override default strong-tier model (default: `anthropic/claude-sonnet-4-6`)
