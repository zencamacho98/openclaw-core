# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Project

Activate the virtual environment first (Python 3.12.3, located at `.venv/`):
```bash
source .venv/bin/activate
```

**FastAPI backend** (port 8000):
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Streamlit dashboard** (separate terminal):
```bash
streamlit run ui/dashboard.py
```

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

## Configuration

Runtime config is in `.env` at the project root:
- `OPENROUTER_API_KEY` — used by tasks that call language models via OpenRouter
- `APP_ENV` — e.g. `dev`
