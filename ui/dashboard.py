import streamlit as st
import requests

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(page_title="OpenClaw Mission Control", layout="wide")

st.title("OpenClaw Mission Control")
st.caption("Safe control panel for agent management")


def get_agents():
    try:
        response = requests.get(f"{API_BASE}/agents", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Failed to load agents: {e}")
        return {}


def get_logs():
    try:
        response = requests.get(f"{API_BASE}/logs", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Failed to load logs: {e}")
        return []


def assign_task(agent: str, task: str):
    try:
        response = requests.post(
            f"{API_BASE}/agents/assign",
            params={"agent": agent, "task": task},
            timeout=5,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def run_worker(max_tasks: int):
    try:
        response = requests.post(
            f"{API_BASE}/run",
            params={"max_tasks": max_tasks},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}


col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Agents")
    agents = get_agents()

    if not agents:
        st.warning("No agent data available.")
    else:
        for agent_name, info in agents.items():
            with st.container(border=True):
                st.markdown(f"### {agent_name}")
                st.write(f"**Status:** {info.get('status', 'unknown')}")
                st.write(f"**Current Task:** {info.get('current_task', None)}")
                st.write(f"**Queue:** {info.get('queue', [])}")

with col2:
    st.subheader("Assign Task")

    agent_name = st.selectbox("Choose agent", ["trader", "ui_builder"])
    task_name = st.text_input("Task", placeholder="analyze_spy")

    if st.button("Assign Task", use_container_width=True):
        if not task_name.strip():
            st.warning("Enter a task first.")
        else:
            result = assign_task(agent_name, task_name.strip())
            if "error" in result:
                st.error(result["error"])
            else:
                st.success(result.get("message", "Task assigned"))

    max_tasks = st.number_input("Max tasks per run", min_value=1, max_value=10, value=1, step=1)

    if st.button("Run Worker", use_container_width=True):
        result = run_worker(int(max_tasks))
        if "error" in result:
            st.error(result["error"])
        else:
            st.success(f"Worker executed. Processed {result.get('processed', 0)} task(s).")

    if st.button("Refresh", use_container_width=True):
        st.rerun()

st.divider()

st.subheader("Recent Logs")
logs = get_logs()

if not logs:
    st.write("No logs yet.")
else:
    for log in reversed(logs):
        with st.container(border=True):
            st.write(f"**Time:** {log['time']}")
            st.write(f"**Agent:** {log['agent']}")
            st.write(f"**Task:** {log['task']}")
            st.write(f"**Status:** {log['status']}")

st.divider()

st.subheader("System Notes")
st.write("- UI does not run agents by itself")
st.write("- No auto-refresh loops")
st.write("- Worker stops after configured max tasks")
