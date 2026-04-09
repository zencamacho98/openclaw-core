from typing import Dict, List


class Agent:
    def __init__(self, name: str):
        self.name = name
        self.status = "idle"
        self.current_task = None
        self.queue: List[str] = []

    def add_task(self, task: str):
        self.queue.append(task)

    def start_next_task(self):
        if not self.queue:
            return None

        self.current_task = self.queue.pop(0)
        self.status = "working"
        return self.current_task

    def complete_task(self):
        self.current_task = None
        self.status = "idle"


class AgentManager:
    def __init__(self):
        self.agents: Dict[str, Agent] = {
            "trader": Agent("trader"),
            "ui_builder": Agent("ui_builder"),
        }

    def get_agents(self):
        return {
            name: {
                "status": agent.status,
                "current_task": agent.current_task,
                "queue": agent.queue
            }
            for name, agent in self.agents.items()
        }

    def assign(self, agent_name: str, task: str):
        if agent_name not in self.agents:
            return {"error": "agent not found"}

        agent = self.agents[agent_name]
        agent.add_task(task)

        return {"message": f"{task} added to {agent_name} queue"}
