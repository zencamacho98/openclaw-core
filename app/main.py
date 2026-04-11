from contextlib import asynccontextmanager

from fastapi import FastAPI
from datetime import datetime
from app.state import manager
from app.worker import run_once
from app.logger import get_logs
from app.loop import start_loop, stop_loop
from app.routes.monitor import router as monitor_router
from app.routes.supervisor import router as supervisor_router
from app.routes.custodian import router as custodian_router
from app.routes.test_sentinel import router as sentinel_router
from app.routes.cost_warden import router as warden_router
from app.routes.neighborhood import router as neighborhood_router
from app.routes.belfort_readiness import router as readiness_router
from app.routes.belfort_learning import router as learning_router
from app.routes.belfort_diagnostics import router as diagnostics_router
from app.routes.event_query import router as event_query_router
from app.routes.frank_lloyd_status import router as frank_lloyd_status_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────────
    # Start supervisor daemon if the loop was enabled when the backend last stopped.
    from app.supervisor import start_supervisor, supervisor_enabled
    if supervisor_enabled():
        start_supervisor()

    # Start checker daemon unconditionally — it is read-only and low-overhead.
    from app.checker import start_checker
    start_checker()

    # Write Cost Warden policy snapshot to disk so Peter handlers can read it.
    from app.cost_warden import cache_policy
    cache_policy()

    yield
    # ── Shutdown ───────────────────────────────────────────────────────────────
    # Daemon threads exit with the process — nothing to clean up explicitly.


app = FastAPI(title="OpenClaw Core", lifespan=lifespan)
app.include_router(monitor_router)
app.include_router(supervisor_router)
app.include_router(custodian_router)
app.include_router(sentinel_router)
app.include_router(warden_router)
app.include_router(neighborhood_router)
app.include_router(readiness_router)
app.include_router(learning_router)
app.include_router(diagnostics_router)
app.include_router(event_query_router)
app.include_router(frank_lloyd_status_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "time": datetime.utcnow().isoformat(),
        "service": "openclaw-core"
    }


@app.get("/agents")
def agents():
    return manager.get_agents()


@app.post("/agents/assign")
def assign(agent: str, task: str):
    return manager.assign(agent, task)


@app.post("/run")
def run_worker(max_tasks: int = 1):
    return run_once(max_tasks=max_tasks)


@app.get("/logs")
def logs():
    return get_logs()


@app.post("/loop/start")
def loop_start(interval: int = 5, max_tasks: int = 1):
    return start_loop(interval, max_tasks)


@app.post("/loop/stop")
def loop_stop():
    return stop_loop()
