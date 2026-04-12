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

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ── Natural-language Frank Lloyd build intent regex ────────────────────────────
# Matches phrasing where the operator asks Frank Lloyd to build something.
# The end of the match (m.end()) marks where the description begins.
# Examples:
#   "Have Frank Lloyd build a page that shows approved builds"
#   "Can Frank Lloyd add a simple helper module for X"
#   "I want Frank Lloyd to make a small tool for viewing build history"
#   "Frank Lloyd, build a cache module"
#   "Frank Lloyd should write a route for GET /x"
# ── Frank Lloyd NL lifecycle patterns ────────────────────────────────────────
# These cover conversational references to existing FL lifecycle actions WITHOUT
# an explicit BUILD-N identifier. Structured commands (with BUILD-N) are handled
# by dedicated rules earlier in the parse chain and are never overridden here.

# Extract BUILD-N from anywhere in the text (supplements the NL layer)
_FL_BUILD_ANYWHERE_RE = re.compile(r'\b(BUILD-\d+)\b', re.IGNORECASE)

# Status query — "What is Frank Lloyd doing / waiting on / blocked on?"
_FL_STATUS_QUERY_RE = re.compile(
    r'(?:'
    r'what(?:\s+is|\s*\'s)\s+frank\s*lloyd\b'
    r'|where(?:\s+is|\s*\'s)\s+frank\s*lloyd\b'
    r'|how(?:\s+is|\s*\'s)\s+frank\s*lloyd\b'
    r'|frank\s*lloyd\s+status\b'
    r'|what(?:\s+is|\s*\'s)\s+frank\s*lloyd\s+(?:doing|working|waiting|blocked|ready|at)\b'
    r')',
    re.IGNORECASE,
)

# Discard — "discard/scrap/throw away that draft"
# Run (auto-run safe-lane) — "run that build", "go ahead and run BUILD-N"
_FL_RUN_NL_RE = re.compile(
    r'(?:'
    r'\brun\s+(?:that|this|the)?\s*build\b'
    r'|\bgo\s+ahead\s+(?:and\s+)?run\b'
    r'|\bauto.?run\b'
    r'|\brun\b.{0,20}\bfrank\s*lloyd\b'
    r'|\bfrank\s*lloyd\b.{0,20}\brun\b'
    r')',
    re.IGNORECASE,
)

_FL_DISCARD_NL_RE = re.compile(
    r'(?:'
    r'\b(?:scrap|toss|throw\s+away|ditch|get\s+rid\s+of)\b.{0,30}\b(?:draft|stage\s*2)\b'
    r'|\bdiscard\b.{0,20}\b(?:draft|stage\s*2|retry|attempt)\b'
    r'|\bdiscard\b.{0,30}\bfrank\s*lloyd\b'
    r'|\bfrank\s*lloyd\b.{0,30}\bdiscard\b'
    r')',
    re.IGNORECASE,
)

# Authorize Stage 2 — "let Frank Lloyd into Stage 2", "move that into Stage 2"
_FL_AUTHORIZE_S2_NL_RE = re.compile(
    r'(?:'
    r'\blet\b.{0,30}\bstage\s*2\b'
    r'|\bmove\b.{0,30}\bstage\s*2\b'
    r'|\bgreenlight\b.{0,30}\bstage\s*2\b'
    r'|\binto\s+stage\s*2\b'
    r'|\bgo\s+to\s+stage\s*2\b'
    r'|\bauthorize\b.{0,30}\bstage\s*2\b'
    r'|\bstage\s*2\b.{0,30}\bauthorize\b'
    r')',
    re.IGNORECASE,
)

# Draft — "try drafting again", "have Frank Lloyd draft that", "generate the draft"
_FL_DRAFT_NL_RE = re.compile(
    r'(?:'
    r'\btry\b.{0,20}\bdraft(?:ing)?\b'
    r'|\bgenerate\b.{0,20}\bdraft\b'
    r'|\brun\b.{0,20}\bdraft\b'
    r'|\bhave\b.{0,30}\bdraft\b'
    r'|\btell\b.{0,30}\bdraft\b'
    r'|\bask\b.{0,30}\bdraft\b'
    r'|\bfrank\s*lloyd\b.{0,30}\bdraft\b'
    r'|\bdraft\b.{0,30}\bfrank\s*lloyd\b'
    r'|\bdraft\b\s+(?:that|it|again|once\s+more|now)\b'
    r')',
    re.IGNORECASE,
)

# Promote NL — "promote the draft", "ship that draft" (no BUILD-N + no path)
_FL_PROMOTE_NL_RE = re.compile(
    r'(?:'
    r'\bpromote\b.{0,30}\bfrank\s*lloyd\b'
    r'|\bfrank\s*lloyd\b.{0,30}\bpromote\b'
    r'|\bpromote\b.{0,20}\bdraft\b'
    r'|\bship\b.{0,20}\bdraft\b'
    r'|\bmerge\b.{0,20}\bdraft\b'
    r'|\bpush\b.{0,20}\bdraft\b'
    r')',
    re.IGNORECASE,
)

# Reject NL — "reject that Frank Lloyd build/spec" (no BUILD-N, FL context required)
_FL_REJECT_NL_RE = re.compile(
    r'(?:'
    r'\breject\b.{0,30}\bfrank\s*lloyd\b'
    r'|\bfrank\s*lloyd\b.{0,30}\breject\b'
    r'|\breject\b\s+(?:that|this|the)\s+(?:build|spec|draft|one)\b'
    r'|\breject\b.{0,30}\b(?:build|spec)\b'
    r')',
    re.IGNORECASE,
)

# Approve NL — "approve that Frank Lloyd build/spec" (no BUILD-N, FL context required)
_FL_APPROVE_NL_RE = re.compile(
    r'(?:'
    r'\bapprove\b.{0,30}\bfrank\s*lloyd\b'
    r'|\bfrank\s*lloyd\b.{0,30}\bapprove\b'
    r'|\bapprove\b\s+(?:that|this|the)\s+(?:build|spec|draft|one)\b'
    r'|\bgo\s+ahead\s+(?:and\s+)?approve\b'
    r'|\bapprove\b.{0,20}\b(?:build|spec)\b'
    r')',
    re.IGNORECASE,
)

# Reason extractor — grabs text after common reason markers
_FL_REASON_MARKER_RE = re.compile(
    r'(?:because|reason[:\s]|since|--\s*|—\s*)',
    re.IGNORECASE,
)


def _fl_extract_reason(text: str) -> str:
    """Extract reason/notes from NL text after a reason marker. Returns '' if none found."""
    m = _FL_REASON_MARKER_RE.search(text)
    if m:
        return text[m.end():].strip().rstrip(".,;?")
    return ""


def _fl_lifecycle_match(text: str, lower: str) -> dict | None:
    """
    Detect a Frank Lloyd NL lifecycle request without a full structured command.
    Returns args dict {action, build_id, reason, notes, target_path} or None.

    Checked in priority order so more specific patterns fire first.
    Structured commands (with explicit BUILD-N) are never overridden here —
    they are caught by earlier rules in parse_command().
    """
    bid_m    = _FL_BUILD_ANYWHERE_RE.search(text)
    build_id = bid_m.group(1).upper() if bid_m else ""

    # Run (auto-run safe-lane pipeline)
    if _FL_RUN_NL_RE.search(lower):
        return {"action": "run", "build_id": build_id, "notes": "", "reason": "", "target_path": ""}

    # Discard (before approve/reject to avoid "discard and retry" ambiguity)
    if _FL_DISCARD_NL_RE.search(lower):
        return {"action": "discard", "build_id": build_id, "notes": _fl_extract_reason(text), "reason": "", "target_path": ""}

    # Authorize Stage 2
    if _FL_AUTHORIZE_S2_NL_RE.search(lower):
        return {"action": "authorize_stage2", "build_id": build_id, "notes": _fl_extract_reason(text), "reason": "", "target_path": ""}

    # Draft
    if _FL_DRAFT_NL_RE.search(lower):
        return {"action": "draft", "build_id": build_id, "notes": _fl_extract_reason(text), "reason": "", "target_path": ""}

    # Promote
    if _FL_PROMOTE_NL_RE.search(lower):
        return {"action": "promote", "build_id": build_id, "notes": "", "reason": "", "target_path": ""}

    # Reject (FL context required — "reject that spec/build" not "reject candidate")
    if _FL_REJECT_NL_RE.search(lower):
        return {"action": "reject", "build_id": build_id, "reason": _fl_extract_reason(text), "notes": "", "target_path": ""}

    # Approve (FL context required)
    if _FL_APPROVE_NL_RE.search(lower):
        return {"action": "approve", "build_id": build_id, "notes": _fl_extract_reason(text), "reason": "", "target_path": ""}

    return None


_FL_NL_BUILD_RE = re.compile(
    r"""
    ^(?:
        # Indirect: "have/can/ask/let/get/tell Frank Lloyd [to] <verb> ..."
        (?:have|can|ask|let|get|tell)\s+frank\s*lloyd\s+
        (?:to\s+)?
        (?:build|make|create|add|write|develop|implement|generate)\s+
        |
        # First-person: "I want/need/I'd like Frank Lloyd to <verb> ..."
        (?:i\s+(?:want|need)|i\s*'?d\s+like)\s+frank\s*lloyd\s+to\s+
        (?:build|make|create|add|write|develop|implement|generate)\s+
        |
        # Direct address: "Frank Lloyd, build ..." / "Frank Lloyd build ..."
        frank\s*lloyd\s*[,\s]\s*(?:please\s+)?
        (?:build|make|create|add|write|develop|implement|generate)\s+
        |
        # Declarative: "Frank Lloyd should build ..."
        frank\s*lloyd\s+should\s+(?:also\s+)?
        (?:build|make|create|add|write|develop|implement|generate)\s+
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


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
    # ── Frank Lloyd intake ─────────────────────────────────────────────────────
    BUILD_INTENT       = "build_intent"        # queue a build request for Frank Lloyd
    # ── Frank Lloyd Stage 1 terminal gate ──────────────────────────────────────
    APPROVE_BUILD      = "approve_build"       # approve a pending_review build spec
    REJECT_BUILD       = "reject_build"        # reject a pending_review build spec
    # ── Frank Lloyd Stage 2 authorization gate ─────────────────────────────────
    AUTHORIZE_STAGE2   = "authorize_stage2"    # authorize Stage 2 for a spec_approved build
    # ── Frank Lloyd Stage 2 draft generation ───────────────────────────────────
    DRAFT_STAGE2       = "draft_stage2"        # generate first Stage 2 draft for authorized build
    # ── Frank Lloyd Stage 2 draft promotion ─────────────────────────────────────
    PROMOTE_DRAFT      = "promote_draft"       # promote staged draft to live repo (code_draft_low only)
    # ── Frank Lloyd Stage 2 draft discard ───────────────────────────────────────
    DISCARD_DRAFT      = "discard_draft"       # discard stage2 artifacts, reset to stage2_authorized
    # ── Frank Lloyd conversational lifecycle ────────────────────────────────────
    FL_LIFECYCLE_NL    = "fl_lifecycle_nl"     # NL lifecycle request (approve/reject/auth/draft/promote/discard/status)
    # ── Market layer commands ────────────────────────────────────────────────────
    MARKET_STATUS      = "market_status"       # feed, session, spread, cost model status
    MARKET_READINESS   = "market_readiness"    # readiness scorecard evaluation
    KILL_TRADING       = "kill_trading"        # engage kill switch (paper / live)
    # ── Frank Lloyd bulk maintenance ──────────────────────────────────────────────
    FL_BULK_ABANDON      = "fl_bulk_abandon"       # abandon all non-terminal builds by source
    # ── Belfort mode/preflight commands ──────────────────────────────────────────
    BELFORT_STATUS       = "belfort_status"        # current mode + readiness claim
    BELFORT_MODE_CONTROL = "belfort_mode_control"  # advance / regress / set mode


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

    # Natural-language Frank Lloyd build intent — MUST precede structured "build " rule.
    # Extracts the description from after the NL prefix and sets nl_intake=True so
    # the handler can use more conversational response text.
    _nl_m = _FL_NL_BUILD_RE.match(t)
    if _nl_m:
        extracted = t[_nl_m.end():].strip()
        return _cmd(CommandType.BUILD_INTENT, {"raw_request": extracted, "nl_intake": True})

    # build intent → BUILD_INTENT (must precede "best" / "start" rules)
    if lower.startswith("build ") or lower == "build":
        raw_request = t[6:].strip() if lower.startswith("build ") else ""
        return _cmd(CommandType.BUILD_INTENT, {"raw_request": raw_request or t})

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

    # Frank Lloyd status query — must precede generic "what is" → STATUS
    if _FL_STATUS_QUERY_RE.search(lower):
        bid_m = _FL_BUILD_ANYWHERE_RE.search(t)
        return _cmd(CommandType.FL_LIFECYCLE_NL, {
            "action": "status_query", "build_id": bid_m.group(1).upper() if bid_m else "",
            "notes": "", "reason": "", "target_path": "",
        })

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

    # Frank Lloyd draft discard — discard BUILD-N [notes]
    if lower.startswith("discard "):
        parts = t.split(None, 2)
        if len(parts) >= 2 and parts[1].upper().startswith("BUILD-"):
            bid   = parts[1].upper()
            notes = parts[2].strip() if len(parts) >= 3 else ""
            return _cmd(CommandType.DISCARD_DRAFT, {"build_id": bid, "notes": notes})

    # Frank Lloyd draft promotion — MUST precede generic "promote" handler.
    # Format: promote BUILD-N path/to/file.py [notes]
    # Discriminator: second token starts with "BUILD-" (case-insensitive).
    if lower.startswith("promote "):
        parts = t.split(None, 3)
        if len(parts) >= 2 and parts[1].upper().startswith("BUILD-"):
            bid         = parts[1].upper()
            target_path = parts[2].strip() if len(parts) >= 3 else ""
            notes       = parts[3].strip() if len(parts) >= 4 else ""
            return _cmd(CommandType.PROMOTE_DRAFT,
                        {"build_id": bid, "target_path": target_path, "notes": notes})
        # NL promote: "promote the draft", "promote the latest Frank Lloyd draft"
        if _FL_PROMOTE_NL_RE.search(lower):
            bid_m = _FL_BUILD_ANYWHERE_RE.search(t)
            return _cmd(CommandType.FL_LIFECYCLE_NL, {
                "action": "promote", "build_id": bid_m.group(1).upper() if bid_m else "",
                "notes": "", "reason": "", "target_path": "",
            })

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

    # market status / market report — Wave 1 observation layer
    if lower in ("market", "market status", "market report", "feed status", "feed"):
        return _cmd(CommandType.MARKET_STATUS)

    # market readiness — readiness scorecard
    if lower in ("readiness", "market readiness", "live readiness", "readiness scorecard"):
        return _cmd(CommandType.MARKET_READINESS)

    # FL bulk abandon — clear auto-generated Frank Lloyd builds by source
    # "abandon frank queue" / "clean frank queue" → peter_chat_smart (the main orphan source)
    # "abandon frank queue <source>" → explicit source
    if lower in (
        "abandon frank queue", "clean frank queue",
        "abandon peter chat builds", "clear frank queue",
        "frank queue cleanup",
    ):
        return _cmd(CommandType.FL_BULK_ABANDON, {"source": "peter_chat_smart"})
    if lower.startswith("abandon frank queue "):
        source = t[len("abandon frank queue "):].strip()
        return _cmd(CommandType.FL_BULK_ABANDON, {"source": source})

    # belfort mode control — advance / regress / set
    # Must precede belfort status / belfort mode rules.
    if lower.startswith("belfort advance"):
        tail = t[len("belfort advance"):].strip()
        reason = (tail[len("because"):].strip() if tail.lower().startswith("because") else tail)
        return _cmd(CommandType.BELFORT_MODE_CONTROL, {"action": "advance", "reason": reason})

    if lower.startswith("belfort regress"):
        tail = t[len("belfort regress"):].strip()
        reason = (tail[len("because"):].strip() if tail.lower().startswith("because") else tail)
        return _cmd(CommandType.BELFORT_MODE_CONTROL, {"action": "regress", "reason": reason})

    if lower.startswith("belfort set "):
        rest   = t[len("belfort set "):].strip()
        tokens = rest.split(None, 1)
        target = tokens[0].lower() if tokens else ""
        reason = tokens[1].strip() if len(tokens) > 1 else ""
        return _cmd(CommandType.BELFORT_MODE_CONTROL,
                    {"action": "set", "target_mode": target, "reason": reason})

    # belfort status / mode / preflight / observation status
    if lower in (
        "belfort status", "belfort mode", "belfort preflight",
        "observation status", "belfort", "preflight",
    ) or lower.startswith("belfort status") or lower.startswith("belfort mode"):
        return _cmd(CommandType.BELFORT_STATUS)

    # kill trading — engage kill switch ("kill", "kill trading", "kill switch", "kill live trading", …)
    if lower.startswith("kill"):
        env = "live" if "live" in lower else "paper"
        return _cmd(CommandType.KILL_TRADING, {"environment": env})

    # show queue / upgrade queue — before generic "start"
    if any(lower.startswith(p) for p in ("show queue", "upgrade queue", "queue")):
        return _cmd(CommandType.SHOW_QUEUE)

    # Frank Lloyd Stage 2 authorization — MUST precede approve_build rules.
    # Format: authorize BUILD-N stage2 [optional notes]
    # Discriminator: second token starts with "BUILD-", third token is "stage2".
    if lower.startswith("authorize "):
        parts = t.split(None, 3)
        if (len(parts) >= 3
                and parts[1].upper().startswith("BUILD-")
                and parts[2].lower() == "stage2"):
            bid   = parts[1].upper()
            notes = parts[3].strip() if len(parts) > 3 else ""
            return _cmd(CommandType.AUTHORIZE_STAGE2, {"build_id": bid, "notes": notes})

    # Frank Lloyd Stage 2 draft generation — MUST precede generic "draft" matches.
    # Format: draft BUILD-N [optional notes]
    # Discriminator: second token starts with "BUILD-".
    if lower.startswith("draft "):
        parts = t.split(None)
        if len(parts) >= 2 and parts[1].upper().startswith("BUILD-"):
            bid   = parts[1].upper()
            notes = " ".join(parts[2:]) if len(parts) > 2 else ""
            return _cmd(CommandType.DRAFT_STAGE2, {"build_id": bid, "notes": notes})

    # Frank Lloyd build approval/rejection — MUST precede approve_candidate / reject_candidate.
    # Discriminator: second token starts with "BUILD-" (case-insensitive).
    if lower.startswith("approve "):
        second = t.split(None, 1)[1].strip() if " " in t else ""
        if second.upper().startswith("BUILD-"):
            tokens = second.split(None, 1)
            bid    = tokens[0].strip().upper()
            notes  = tokens[1].strip() if len(tokens) > 1 else ""
            return _cmd(CommandType.APPROVE_BUILD, {"build_id": bid, "notes": notes})

    if lower.startswith("reject "):
        second = t.split(None, 1)[1].strip() if " " in t else ""
        if second.upper().startswith("BUILD-"):
            tokens = second.split(None, 1)
            bid    = tokens[0].strip().upper()
            reason = tokens[1].strip() if len(tokens) > 1 else ""
            return _cmd(CommandType.REJECT_BUILD, {"build_id": bid, "reason": reason})

    # Frank Lloyd NL lifecycle — catches FL action phrases without an explicit BUILD-N.
    # Checked AFTER all structured FL rules (which require BUILD-N) so those are never shadowed.
    # Checked BEFORE generic approve/reject candidate to prevent FL phrases from routing there.
    _fl_nl = _fl_lifecycle_match(t, lower)
    if _fl_nl:
        return _cmd(CommandType.FL_LIFECYCLE_NL, _fl_nl)

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

Build commands:
  build <request>               Queue a build request for Frank Lloyd (Stage 1 spec)
                                  Include a testable success criterion, e.g.:
                                  build add route GET /x. success: curl /x returns {ok: true}
  approve BUILD-N [notes]       Approve the spec for BUILD-N (moves it to spec_approved)
  reject BUILD-N <reason>       Reject the spec for BUILD-N with a required reason
  authorize BUILD-N stage2 [notes]
                                Authorize Stage 2 draft generation for BUILD-N
                                  Requires: build is in spec_approved state
  draft BUILD-N [notes]         Generate first Stage 2 draft artifacts for BUILD-N
                                  Requires: build is in stage2_authorized state
                                  Writes to staging only — does not touch the live repo
  promote BUILD-N path/to/file.py [notes]
                                Promote staged draft to live repo (code_draft_low only)
                                  New .py files only — will not overwrite existing files
                                  Requires: build is in draft_generated state
  discard BUILD-N [notes]       Discard Stage 2 draft artifacts and reset to stage2_authorized
                                  Removes staging/frank_lloyd/{build_id}/stage2/ only
                                  Preserves Stage 1 archive and Stage 2 authorization record
                                  Allowed states: draft_generated, draft_blocked

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
