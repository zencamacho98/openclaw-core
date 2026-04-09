from typing import Dict


class Agent:
    def __init__(self, name: str):
        self.name = name
        self.status = "idle"
        self.current_task = None

    def assign_task(self, task: str):
        self.current_task = task
        self.status = "working"

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
                "task": agent.current_task
            }
            for name, agent in self.agents.items()
        }

    def assign(self, agent_name: str, task: str):
        if agent_name not in self.agents:
            return {"error": "agent not found"}

        agent = self.agents[agent_name]
        agent.assign_task(task)

        return {"message": f"{agent_name} assigned task"}
