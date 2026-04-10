# peter/identity.py
#
# Identity and authorization for Peter.
#
# This is NOT external authentication. It is a local config file that defines
# which operator identities are approved per transport. The purpose is to
# prepare the architecture so that when Discord (or another transport) is added,
# only a specific account can reach Peter — without having to redesign the core.
#
# How it works:
#   - Operators are identified by (transport, transport_id) pairs.
#   - transport_id can be "*" to allow any caller on that transport (e.g. CLI).
#   - allowed_commands can be ["all"] or a specific list of CommandType values.
#
# Public API:
#   load_identities() → list[dict]
#   is_approved(transport, transport_id, command_type) → bool
#   operator_name(transport, transport_id) → str | None

from __future__ import annotations

import json
import pathlib
from typing import Any

_CONFIG_PATH = pathlib.Path(__file__).resolve().parent / "identity.json"


def load_identities() -> list[dict[str, Any]]:
    """
    Load the operator list from identity.json.

    Returns an empty list if the file is missing or unreadable.
    """
    if not _CONFIG_PATH.exists():
        return []
    try:
        data = json.loads(_CONFIG_PATH.read_text())
        return data.get("operators", [])
    except Exception:
        return []


def is_approved(
    transport:    str,
    transport_id: str,
    command_type: str = "any",
) -> bool:
    """
    Return True if the (transport, transport_id) pair is in the approved list
    and is allowed to use command_type.

    Rules:
      - transport must match exactly (case-insensitive).
      - transport_id "*" in config matches any caller on that transport.
      - transport_id must match exactly (case-sensitive) otherwise.
      - allowed_commands ["all"] permits every command.
      - allowed_commands ["status", "best_candidate", ...] permits only listed commands.
    """
    operators = load_identities()
    for op in operators:
        if op.get("transport", "").lower() != transport.lower():
            continue
        stored_id = op.get("transport_id", "")
        if stored_id != "*" and stored_id != transport_id:
            continue
        # Transport + identity match — check command scope
        allowed = op.get("allowed_commands", [])
        if "all" in allowed:
            return True
        if command_type in allowed or command_type == "any":
            return True
    return False


def operator_name(transport: str, transport_id: str) -> str | None:
    """
    Return the human-readable name for a (transport, transport_id) pair,
    or None if not found.
    """
    for op in load_identities():
        if op.get("transport", "").lower() != transport.lower():
            continue
        stored_id = op.get("transport_id", "")
        if stored_id == "*" or stored_id == transport_id:
            return op.get("name")
    return None
