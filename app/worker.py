from app.logger import add_log
from app.state import manager
from app.tasks import TASK_MAP


def execute_task(agent_name, task):
    add_log(agent_name, task, "started")
    print(f"[EXECUTING] {agent_name} -> {task}")

    func = TASK_MAP.get(task)

    if not func:
        result = {"error": "unknown task"}
    else:
        result = func()

    print(f"[DONE] {agent_name} -> {task} | result={result}")
    add_log(agent_name, task, "completed")


def run_once(max_tasks: int = 1):
    processed = 0
    agents = manager.agents

    for name, agent in agents.items():
        while agent.status == "idle" and agent.queue and processed < max_tasks:
            task = agent.start_next_task()

            if task:
                execute_task(name, task)
                agent.complete_task()
                processed += 1

            if processed >= max_tasks:
                break

    return {"processed": processed}
