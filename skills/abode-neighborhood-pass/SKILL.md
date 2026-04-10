---
name: abode-neighborhood-pass
description: Use this when working on THE ABODE neighborhood UI. Keeps neighborhood changes lean, user-facing, and tied to existing backend/control flows.
---

# Abode Neighborhood Pass

Use this skill when editing the neighborhood/front layer of THE ABODE.

## Goals
- improve the neighborhood as the main user-facing front layer
- keep Peter as the front door
- keep Belfort as the trading/research home
- keep operations quieter and secondary
- make changes understandable for a normal user

## Rules
- prefer minimal local edits over large rewrites
- reuse existing backend endpoints/control flows
- do not duplicate the entire dev/dashboard UI inside the neighborhood
- prefer plain English over internal jargon
- keep status glanceable and controls compact
- do not add fake complexity

## Non-goals
- no Discord work
- no art-pipeline rabbit hole
- no movement/pathfinding/game systems
- no new houses unless explicitly requested
- no broad frontend rewrite

## Delivery format
Always report:
1. what changed
2. files added/edited
3. existing flows/endpoints reused
4. what was deliberately left out
5. remaining gaps
6. exact next recommended block
