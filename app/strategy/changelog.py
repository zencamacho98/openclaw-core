# app/strategy/changelog.py
#
# Append-only log for parameter changes.
# Each entry captures what changed and a performance snapshot so before/after
# can be compared. Never auto-applied — only written when the operator confirms.

import json
import pathlib
from datetime import datetime, timezone

CHANGELOG_FILE = pathlib.Path("data/param_changelog.jsonl")


def record(
    parameter: str,
    old_value,
    new_value,
    reason: str,
    performance_snapshot: dict,
) -> dict:
    """Append one change entry and return it."""
    entry = {
        "timestamp":            datetime.now(timezone.utc).isoformat(),
        "parameter":            parameter,
        "old_value":            old_value,
        "new_value":            new_value,
        "reason":               reason,
        "performance_snapshot": performance_snapshot,
    }
    _append(entry)
    return entry


def get_recent(n: int = 20) -> list[dict]:
    """Return the last N changelog entries, newest-first."""
    if not CHANGELOG_FILE.exists():
        return []
    entries = []
    for line in CHANGELOG_FILE.read_text().strip().splitlines():
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    return list(reversed(entries[-n:]))


def _append(entry: dict) -> None:
    CHANGELOG_FILE.parent.mkdir(exist_ok=True)
    with CHANGELOG_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")
