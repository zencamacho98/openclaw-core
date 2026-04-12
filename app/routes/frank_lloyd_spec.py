# app/routes/frank_lloyd_spec.py
#
# Thin route adapter for Frank Lloyd Stage 1 spec generation.
#
# All domain logic lives in frank_lloyd/spec_writer.py.
# This file wires HTTP endpoints to the domain functions.
#
# Endpoints:
#   POST /frank-lloyd/{build_id}/spec  — generate spec.yaml + preflight.md for a queued build
#   GET  /frank-lloyd/next-queued      — return the next build_id pending spec generation

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/frank-lloyd/{build_id}/spec")
def frank_lloyd_generate_spec(build_id: str) -> dict:
    """
    Generate spec.yaml + preflight.md for a queued Frank Lloyd build.

    The build must be in pending_spec state (request_queued event exists,
    no spec_ready or terminal event follows it).

    Returns the generate_spec_packet result dict. On validation errors (wrong
    state, missing request file) returns HTTP 400. Blocked state (LM failure)
    returns 200 with blocked=True.
    """
    from frank_lloyd.spec_writer import generate_spec_packet
    result = generate_spec_packet(build_id)
    if not result["ok"] and not result.get("blocked"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/frank-lloyd/next-queued")
def frank_lloyd_next_queued() -> dict:
    """
    Return the build_id of the next build pending spec generation, or null.
    FIFO: earliest request_queued event in the log wins.
    """
    from frank_lloyd.spec_writer import find_next_queued_build
    return {"build_id": find_next_queued_build()}
