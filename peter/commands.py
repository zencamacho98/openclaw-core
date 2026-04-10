# peter/commands.py
#
# Command schema for Peter.
#
# A Command is the normalized representation of any operator request,
# regardless of which transport it arrived on. The raw_text is preserved
# for logging. All transport-specific parsing happens before this layer.
#
# parse_command() converts free-form text → Command.
# It uses simple prefix matching — no NLP, deterministic output.
#
# Public API:
#   CommandType    — str enum of all recognized command names
#   Command        — dataclass: type, args, transport, operator_id, raw_text
#   parse_command(text, transport, operator_id) → Command

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CommandType(str, Enum):
    """All recognized Peter commands."""
    STATUS             = "status"
    INSPECT_CAMPAIGN   = "inspect_campaign"
    BEST_CANDIDATE     = "best_candidate"
    LIST_REVIEW_WORTHY = "list_review_worthy"
    PROMOTE_GUIDANCE   = "promote_guidance"
    EXPLAIN_RESULT     = "explain_result"
    RUN_CAMPAIGN       = "run_campaign"
    RESUME_CAMPAIGN    = "resume_campaign"
    HELP               = "help"
    UNKNOWN            = "unknown"
    # ── v1 action commands (UI + Discord command surface) ──────────────────────
    START_AUTO         = "start_auto"          # start research, auto-choose goal
    STOP_CAMPAIGN      = "stop_campaign"       # request stop after current session
    CANCEL_STOP        = "cancel_stop"         # cancel pending stop signal
    HOLD_REVIEW        = "hold_review"         # hold current candidate review
    RESUME_REVIEW      = "resume_review"       # resume a held review
    APPLY_AND_CONTINUE = "apply_and_continue"  # apply candidate + start next run
    WHAT_LAST          = "what_last"           # recent activity (event-log sourced)
    # ── v2 continuous loop commands ────────────────────────────────────────────
    START_CONTINUOUS   = "start_continuous"    # enable continuous learning loop
    SHOW_QUEUE         = "show_queue"          # list pending upgrade queue
    APPROVE_CANDIDATE  = "approve_candidate"   # approve top pending candidate
    REJECT_CANDIDATE   = "reject_candidate"    # reject top pending candidate
    HOLD_QUEUED        = "hold_queued"         # hold (defer) top pending candidate
    CHECKER_FINDINGS   = "checker_findings"    # show checker health findings
    CUSTODIAN_HEALTH   = "custodian_health"    # show Custodian runtime health report
    SENTINEL_STATUS    = "sentinel_status"     # show Test Sentinel patch-safety verdict
    WARDEN_STATUS      = "warden_status"       # show Cost Warden routing policy and usage


@dataclass
class Command:
    """
    Normalized operator command.

    Fields:
        type:        CommandType — what the operator wants
        args:        Extra parameters parsed from raw_text (e.g. campaign_id, goal)
        transport:   "cli" | "discord" | "whatsapp" — where the command came from
        operator_id: Transport-specific caller identifier (checked against identity.json)
        raw_text:    Original unmodified text (for logging)
    """
    type:        CommandType
    args:        dict[str, Any]
    transport:   str
    operator_id: str
    raw_text:    str


# ── Command parser ─────────────────────────────────────────────────────────────

def parse_command(
    text:        str,
    transport:   str = "cli",
    operator_id: str = "cli",
) -> Command:
    """
    Convert free-form text to a Command.

    Matching rules (checked in order, first match wins):
      "status"                        → STATUS
      "inspect campaign [id]"         → INSPECT_CAMPAIGN, args.campaign_id optional
      "best candidate"                → BEST_CANDIDATE
      "list review"/"review-worthy"   → LIST_REVIEW_WORTHY
      "promote"/"promotion guidance"  → PROMOTE_GUIDANCE
      "explain result [id]"           → EXPLAIN_RESULT, args.artifact_id optional
      "run campaign GOAL..."          → RUN_CAMPAIGN, args.goal required
      "resume campaign ID"            → RESUME_CAMPAIGN, args.campaign_id required
      "help"                          → HELP
      anything else                   → UNKNOWN
    """
    t = text.strip()

    def _cmd(ctype: CommandType, args: dict | None = None) -> Command:
        return Command(
            type        = ctype,
            args        = args or {},
            transport   = transport,
            operator_id = operator_id,
            raw_text    = text,
        )

    lower = t.lower()

    # status
    if lower in ("status", "st", "s"):
        return _cmd(CommandType.STATUS)

    # inspect campaign [campaign_id]
    if lower.startswith("inspect campaign"):
        rest = t[len("inspect campaign"):].strip()
        args: dict[str, Any] = {}
        if rest:
            args["campaign_id"] = rest
        return _cmd(CommandType.INSPECT_CAMPAIGN, args)

    if lower in ("inspect", "campaign"):
        return _cmd(CommandType.INSPECT_CAMPAIGN)

    # best candidate
    if lower in ("best candidate", "best", "bc"):
        return _cmd(CommandType.BEST_CANDIDATE)

    # what happened last → WHAT_LAST (event-log sourced; must precede generic "what is" → STATUS)
    if lower.startswith("what happened") or lower in ("last",):
        return _cmd(CommandType.WHAT_LAST)

    # why / what is belfort doing → STATUS (reuses existing handler)
    if lower.startswith("why") or lower.startswith("what is"):
        return _cmd(CommandType.STATUS)

    # list review-worthy / review
    if any(lower.startswith(p) for p in ("list review", "review-worthy", "review worthy", "review")):
        return _cmd(CommandType.LIST_REVIEW_WORTHY)

    # apply and continue → APPLY_AND_CONTINUE
    if lower.startswith("apply"):
        return _cmd(CommandType.APPLY_AND_CONTINUE)

    # hold review / hold / defer → HOLD_REVIEW
    if lower.startswith("hold") or lower in ("defer",):
        return _cmd(CommandType.HOLD_REVIEW)

    # promote guidance / promote
    if any(lower.startswith(p) for p in ("promote guidance", "promote", "promotion")):
        return _cmd(CommandType.PROMOTE_GUIDANCE)

    # explain result [artifact_id]
    if lower.startswith("explain"):
        rest = t.split(None, 2)
        args = {}
        if len(rest) >= 3:
            args["artifact_id"] = rest[2]
        return _cmd(CommandType.EXPLAIN_RESULT, args)

    # run campaign GOAL TEXT
    if lower.startswith("run campaign"):
        goal = t[len("run campaign"):].strip()
        return _cmd(CommandType.RUN_CAMPAIGN, {"goal": goal})

    # resume review → RESUME_REVIEW — MUST precede generic "resume" to avoid RESUME_CAMPAIGN match
    if lower.startswith("resume review"):
        return _cmd(CommandType.RESUME_REVIEW)

    # resume campaign CAMPAIGN_ID
    # Use "resume campaign " (with trailing space) to avoid matching "resume campaign_id"
    if lower.startswith("resume campaign "):
        rest = t[len("resume campaign "):].strip()
        return _cmd(CommandType.RESUME_CAMPAIGN, {"campaign_id": rest})

    if lower == "resume campaign":
        return _cmd(CommandType.RESUME_CAMPAIGN)

    if lower.startswith("resume"):
        rest = t[len("resume"):].strip()
        return _cmd(CommandType.RESUME_CAMPAIGN, {"campaign_id": rest})

    # cancel stop — before generic start/stop rules
    if lower.startswith("cancel stop") or lower in ("keep going",):
        return _cmd(CommandType.CANCEL_STOP)

    # checker findings — before generic "check" matches
    if lower.startswith("checker") or lower.startswith("check findings") or lower in ("findings",):
        return _cmd(CommandType.CHECKER_FINDINGS)

    # custodian health — runtime service health
    if lower.startswith("custodian") or lower.startswith("runtime health") or lower in ("health", "services"):
        return _cmd(CommandType.CUSTODIAN_HEALTH)

    # sentinel / test results — patch-safety verdict
    if lower.startswith("sentinel") or lower.startswith("test sentinel") or lower in ("tests", "patch safe", "test status"):
        return _cmd(CommandType.SENTINEL_STATUS)

    # cost warden — LM routing policy and usage
    if lower.startswith("warden") or lower.startswith("cost warden") or lower in ("cost", "routing policy", "lm usage"):
        return _cmd(CommandType.WARDEN_STATUS)

    # show queue / upgrade queue — before generic "start"
    if any(lower.startswith(p) for p in ("show queue", "upgrade queue", "queue")):
        return _cmd(CommandType.SHOW_QUEUE)

    # approve candidate — MUST precede "apply" rule to avoid APPLY_AND_CONTINUE match
    if lower.startswith("approve") or lower in ("ok", "accept"):
        rest = t.split(None, 1)
        queue_id = rest[1].strip() if len(rest) > 1 else ""
        return _cmd(CommandType.APPROVE_CANDIDATE, {"queue_id": queue_id} if queue_id else {})

    # reject candidate
    if lower.startswith("reject") or lower in ("no",):
        rest = t.split(None, 1)
        queue_id = rest[1].strip() if len(rest) > 1 else ""
        return _cmd(CommandType.REJECT_CANDIDATE, {"queue_id": queue_id} if queue_id else {})

    # hold queued — MUST precede generic "hold" rule
    if lower.startswith("hold queue") or lower in ("defer queue",):
        rest = t.split(None, 2)
        queue_id = rest[2].strip() if len(rest) > 2 else ""
        return _cmd(CommandType.HOLD_QUEUED, {"queue_id": queue_id} if queue_id else {})

    # start continuous loop — MUST precede generic "start" rule
    if lower.startswith("start continuous") or lower.startswith("enable loop") or lower in ("continuous",):
        return _cmd(CommandType.START_CONTINUOUS)

    # start auto research
    if lower.startswith("start") or lower in ("go",):
        return _cmd(CommandType.START_AUTO)

    # stop after current session
    if lower.startswith("stop") or lower in ("halt",):
        return _cmd(CommandType.STOP_CAMPAIGN)

    # help
    if lower in ("help", "h", "?"):
        return _cmd(CommandType.HELP)

    return _cmd(CommandType.UNKNOWN)


# ── Help text ─────────────────────────────────────────────────────────────────

HELP_TEXT = """\
Peter — OpenClaw Research Supervisor

Action commands (execute immediately):
  start [auto research]         Start a research campaign — goal auto-chosen from history
  start continuous              Enable the continuous learning loop (auto-restart after each cycle)
  stop                          Request stop after the current session completes
  cancel stop                   Cancel a pending stop signal
  hold [review]                 Defer the pending candidate review for later
  resume review                 Resume a deferred candidate review
  apply [and continue]          Apply the current candidate and start the next research run
  resume [safe]                 Resume the most recent interrupted campaign
  approve [QUEUE_ID]            Approve the top pending upgrade candidate (or by ID)
  reject [QUEUE_ID]             Reject the top pending upgrade candidate (or by ID)
  hold queue [QUEUE_ID]         Defer the top pending upgrade candidate without blocking loop

Information commands (read-only, no side effects):
  status                        Current system state (campaign, experiments, best candidate)
  why                           Why did Mr Belfort stop?
  what happened [last]          Recent activity from the event log
  show queue                    List pending candidates in the upgrade queue
  checker [findings]            Show health audit findings from the loop checker
  custodian [health]            Show runtime service health (backend, UI, port drift)
  sentinel [status]             Show Test Sentinel patch-safety verdict (last run)
  warden [status]               Show Cost Warden LM routing policy and usage summary
  inspect campaign [id]         Campaign details (latest if no id given)
  best candidate                Best candidate + promotion command
  review-worthy                 List accepted candidates with score >= 66 from recent runs
  promote guidance              Exact command to promote the best candidate
  explain result [id]           Summarize a specific batch or session result
  run campaign GOAL             Show the command to start a campaign (does not execute it)
  resume campaign CAMPAIGN_ID   Show the command to resume a campaign (does not execute it)
  help                          Show this message
"""
