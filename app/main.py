from app.loop import start_loop, stop_loop
from fastapi import FastAPI
from datetime import datetime
from app.state import manager
from app.worker import run_once
from app.logger import get_logs
from app.routes.monitor import router as monitor_router

app = FastAPI(title="OpenClaw Core")
app.include_router(monitor_router)


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
