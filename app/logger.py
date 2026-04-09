from datetime import datetime

LOGS = []

def add_log(agent: str, task: str, status: str):
    LOGS.append({
        "time": datetime.utcnow().isoformat(),
        "agent": agent,
        "task": task,
        "status": status,
    })

def get_logs():
    return LOGS[-50:]
