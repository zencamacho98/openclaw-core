import time
import threading
from app.worker import run_once

running = False


def loop_worker(interval: int, max_tasks: int):
    global running
    print("[LOOP] started")

    while running:
        print("[LOOP] tick")
        run_once(max_tasks=max_tasks)
        time.sleep(interval)

    print("[LOOP] stopped")


def start_loop(interval: int = 5, max_tasks: int = 1):
    global running

    if running:
        return {"message": "loop already running"}

    running = True
    thread = threading.Thread(
        target=loop_worker,
        args=(interval, max_tasks),
        daemon=True
    )
    thread.start()

    return {"message": "loop started"}


def stop_loop():
    global running
    running = False
    return {"message": "loop stopped"}
