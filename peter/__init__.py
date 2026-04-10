# peter/ — Supervisor agent interface layer
#
# Peter is the top-level operator-facing control layer for OpenClaw.
# He sits above the campaign / session / batch research system and provides
# a transport-agnostic command interface.
#
# Architecture:
#   commands.py   — Command schema (CommandType, Command, parse_command)
#   responses.py  — Response contract (Response, to_dict, to_chat_text)
#   handlers.py   — One handler per command; reads artifacts from disk
#   router.py     — Dispatches Command → handler → Response (with auth check)
#   identity.py   — Approved operator identities (local config only)
#   identity.json — Operator config file (edit to add Discord user IDs later)
#
# Design constraints:
#   - Peter does NOT import research/, app/, discord, twilio, or any external transport
#   - Peter reads JSON artifacts from disk (data/campaigns/, data/research_ledger/)
#   - Peter never executes long-running work — he returns commands to run
#   - All promotion remains manual — Peter gives the exact command, never runs it
#
# First transport: CLI via scripts/peter.py
# Future transports: Discord, WhatsApp — add an adapter that calls route()
