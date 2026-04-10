# observability/
#
# Durable run-state and telemetry layer for Mr Belfort and Peter.
#
# Packages:
#   agent_state  — per-agent JSON state (status, learning, campaign, heartbeat)
#   telemetry    — append-only token/cost records per scope (batch/session/campaign)
#   budget       — budget config + threshold evaluation
#   summary      — Peter-ready text summaries from state + artifacts
#
# State files:     data/agent_state/{agent_name}.json
# Telemetry files: data/telemetry/{campaign_id}_telemetry.jsonl
