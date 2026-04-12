# frank_lloyd/control.py
#
# Frank Lloyd enabled/disabled gate.
#
# When Frank is disabled, Peter intake and the HTTP compose/smart-queue
# endpoints reject new build requests immediately with a clear message.
# The operator must explicitly re-enable before new builds can be accepted.
#
# This is NOT a runtime kill-switch for in-progress LM calls (use
# auto_runner.request_stop() for that). This gate prevents new intake
# from entering the queue after a hard-stop-and-purge cycle.
#
# State file: data/frank_lloyd/control.json
#
# Public API:
#   is_enabled()  → bool
#   disable(reason: str = "") → dict
#   enable() → dict
#   read_control() → dict

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_CONTROL_FILE = _ROOT / "data" / "frank_lloyd" / "control.json"

_DEFAULT: dict = {
    "enabled":     True,
    "disabled_at": None,
    "disabled_reason": "",
    "enabled_at":  None,
}


def read_control() -> dict:
    """Read the current control state. Returns default (enabled) if file absent."""
    if not _CONTROL_FILE.exists():
        return dict(_DEFAULT)
    try:
        return json.loads(_CONTROL_FILE.read_text(encoding="utf-8"))
    except Exception:
        return dict(_DEFAULT)


def is_enabled() -> bool:
    """Return True if Frank Lloyd intake is enabled (default: True)."""
    return read_control().get("enabled", True)


def disable(reason: str = "") -> dict:
    """
    Disable Frank Lloyd intake.

    New build requests from Peter or the neighborhood UI will be rejected
    until enable() is called. In-progress pipelines are NOT interrupted
    (call auto_runner.request_stop() for that).

    Returns {ok, enabled, disabled_at, disabled_reason}.
    """
    state = {
        "enabled":         False,
        "disabled_at":     datetime.now(timezone.utc).isoformat(),
        "disabled_reason": (reason.strip() or "Disabled by operator"),
        "enabled_at":      None,
    }
    try:
        _CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONTROL_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"Failed to write control file: {exc}"}
    return {"ok": True, **state}


def enable() -> dict:
    """
    Re-enable Frank Lloyd intake.

    Returns {ok, enabled, enabled_at}.
    """
    state = {
        "enabled":         True,
        "disabled_at":     None,
        "disabled_reason": "",
        "enabled_at":      datetime.now(timezone.utc).isoformat(),
    }
    try:
        _CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONTROL_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"Failed to write control file: {exc}"}
    return {"ok": True, **state}
