# Abode runtime source of truth

## Canonical control flow
Use:
- `./scripts/ctl.sh`

```bash
./scripts/ctl.sh start      # start backend + UI, wait for readiness, print URL
./scripts/ctl.sh stop       # stop repo-owned processes (safe, by PID)
./scripts/ctl.sh restart    # stop then start
./scripts/ctl.sh status     # show PIDs, health, ports, canonical URL
./scripts/ctl.sh logs       # follow both logs (Ctrl-C to stop)
```

## Canonical ports
- backend: `127.0.0.1:8001` — matches `API_BASE` in `ui/dashboard.py`
- UI: `http://localhost:8502`

## Port rule
- do not drift back to old/random ports
- `8501` may show an old stale UI (system-managed) and is not canonical

## Log and PID files
- `logs/backend.log`, `logs/ui.log` — created on first start
- `run/backend.pid`, `run/ui.pid` — created on start, deleted on stop

## Dependencies
- no `requirements.txt` — dependencies live only in `.venv/`
- no test framework or linter is configured

## Configuration
Runtime config is in `.env` at the project root:
- `OPENROUTER_API_KEY` — used by tasks that call language models via OpenRouter
- `APP_ENV` — e.g. `dev`
- `CHEAP_MODEL` — override default cheap-tier model (default: `openai/gpt-4o-mini`)
- `STRONG_MODEL` — override default strong-tier model (default: `anthropic/claude-sonnet-4-6`)

## Runtime philosophy
- keep runtime control stable
- preserve canonical relaunch workflow
- avoid one-off manual process sprawl when existing control scripts already solve it
