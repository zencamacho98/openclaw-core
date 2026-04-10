# peter/responses.py
#
# Response contract for Peter.
#
# Every command handler returns a Response. The Response is transport-agnostic:
#   - to_dict()      → machine-readable dict (for logging, JSON API, future bot frameworks)
#   - to_chat_text() → plain-text for chat delivery (CLI today, Discord/WhatsApp later)
#
# Transport adapters receive a Response and decide how to format it.
# Peter's core never knows or cares which transport is being used.
#
# Public API:
#   Response          — main response dataclass
#   error_response()  — helper for failure cases
#   unauthorized_response() — helper for auth failures

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Response:
    """
    Structured result from a Peter command handler.

    Fields:
        command_type         — echo of the command that produced this response
        ok                   — False only on errors or auth failure
        summary              — 1–3 sentence plain-English description
        metrics              — key numbers as a flat dict (for easy rendering)
        artifacts            — name → path/value for relevant output files
        next_action          — what the operator should do next (single sentence or command)
        human_review_needed  — True if operator attention is explicitly required
        human_review_reason  — explains why review is needed (empty string if not needed)
        raw                  — full machine-readable data (handler-specific)
    """
    command_type:        str
    ok:                  bool
    summary:             str
    metrics:             dict[str, Any]          = field(default_factory=dict)
    artifacts:           dict[str, str]          = field(default_factory=dict)
    next_action:         str                     = ""
    human_review_needed: bool                    = False
    human_review_reason: str                     = ""
    raw:                 dict[str, Any]          = field(default_factory=dict)

    # ── Serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Machine-readable representation. Safe to log or serialize to JSON."""
        return {
            "command_type":        self.command_type,
            "ok":                  self.ok,
            "summary":             self.summary,
            "metrics":             self.metrics,
            "artifacts":           self.artifacts,
            "next_action":         self.next_action,
            "human_review_needed": self.human_review_needed,
            "human_review_reason": self.human_review_reason,
            "raw":                 self.raw,
        }

    def to_chat_text(self) -> str:
        """
        Plain-text representation suitable for delivery via any chat transport.

        Format is intentionally minimal — no transport-specific markdown.
        Discord/WhatsApp adapters can wrap this or format response.to_dict()
        however they like.
        """
        sep = "─" * 48
        lines: list[str] = [
            f"[Peter] {self.command_type.replace('_', ' ')}",
            sep,
            self.summary,
        ]

        if self.metrics:
            lines.append("")
            for k, v in self.metrics.items():
                lines.append(f"  {k}: {v}")

        if self.artifacts:
            lines.append("")
            for name, path in self.artifacts.items():
                if path and path != "N/A":
                    lines.append(f"  {name}: {path}")

        if self.next_action:
            lines.append("")
            lines.append(f"Next: {self.next_action}")

        if self.human_review_needed:
            lines.append("")
            lines.append(f"* Human review required: {self.human_review_reason}")

        lines.append(sep)
        return "\n".join(lines)


# ── Factory helpers ────────────────────────────────────────────────────────────

def error_response(command_type: str, reason: str) -> Response:
    """Return a standard error response."""
    return Response(
        command_type = command_type,
        ok           = False,
        summary      = f"Error: {reason}",
        next_action  = "Check the system or try 'peter help'.",
    )


def unauthorized_response(command_type: str, transport: str, operator_id: str) -> Response:
    """Return a standard unauthorized response."""
    return Response(
        command_type = command_type,
        ok           = False,
        summary      = (
            f"Unauthorized: operator '{operator_id}' on transport '{transport}' "
            "is not in the approved identity list."
        ),
        next_action  = "Edit peter/identity.json to add this operator.",
    )


def no_data_response(command_type: str, what: str) -> Response:
    """Return a standard 'no data found' response."""
    return Response(
        command_type = command_type,
        ok           = True,
        summary      = f"No {what} found. Run a campaign or session first.",
        next_action  = "python scripts/run_campaign.py --goal \"your goal here\"",
    )
