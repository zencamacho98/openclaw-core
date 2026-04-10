#!/usr/bin/env python3
"""
scripts/peter.py — CLI adapter for Peter, the OpenClaw research supervisor.

This is the first transport adapter. It proves the command/response abstraction
before Discord or WhatsApp are added. The same route() call will be used by
future transport adapters — only the input parsing and output formatting differ.

Usage:
    python scripts/peter.py status
    python scripts/peter.py "inspect campaign"
    python scripts/peter.py "inspect campaign campaign_20260409T120000"
    python scripts/peter.py "best candidate"
    python scripts/peter.py "review-worthy"
    python scripts/peter.py "promote guidance"
    python scripts/peter.py "explain result"
    python scripts/peter.py "explain result batch_20260409T232624"
    python scripts/peter.py "run campaign improve entry quality filters"
    python scripts/peter.py "resume campaign campaign_20260409T120000"
    python scripts/peter.py help

Environment:
    Transport = "cli"
    Operator  = "cli" (matched against peter/identity.json, transport_id "*")

Adding Discord later:
    Create peter/adapters/discord_adapter.py
    Parse incoming message → raw_text
    Call parse_command(raw_text, transport="discord", operator_id=str(message.author.id))
    Call route(command) → response
    Send response.to_chat_text() back to the channel (or format response.to_dict()
    with Discord embeds for richer output)
"""
from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from peter.commands import parse_command
from peter.router   import route


def main() -> int:
    if len(sys.argv) < 2:
        _print_usage()
        return 0

    # Join all argv parts as the raw command text
    raw_text = " ".join(sys.argv[1:])

    # Parse → route → respond
    command  = parse_command(raw_text, transport="cli", operator_id="cli")
    response = route(command)

    # Print the chat-ready text to stdout
    print(response.to_chat_text())

    return 0 if response.ok else 1


def _print_usage() -> None:
    print(
        "Peter — OpenClaw Research Supervisor\n"
        "\n"
        "Usage: python scripts/peter.py <command>\n"
        "\n"
        "Examples:\n"
        "  python scripts/peter.py status\n"
        "  python scripts/peter.py 'best candidate'\n"
        "  python scripts/peter.py 'review-worthy'\n"
        "  python scripts/peter.py 'promote guidance'\n"
        "  python scripts/peter.py 'run campaign reduce tail risk'\n"
        "  python scripts/peter.py 'resume campaign campaign_20260409T120000'\n"
        "  python scripts/peter.py help\n"
    )


if __name__ == "__main__":
    sys.exit(main())
