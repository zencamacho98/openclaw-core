# Frank Lloyd Staging Model
*Status: DRAFT — design pass only.*  
*Last updated: 2026-04-11*

---

## What staging solves

Frank Lloyd must never write to the live repo directly. Staging is the controlled buffer between "Frank Lloyd produced an artifact" and "the artifact is live." It gives the operator a reviewable, Sentinel-validated snapshot before any commitment to the live codebase.

The staging model must satisfy:
1. **Zero live risk during build** — in-progress or rejected artifacts cannot affect running code
2. **Full auditability** — the governance trail (what was proposed, what Sentinel said, what the operator approved) is durable and inspectable
3. **Operator reviewability** — the operator can see exactly what will change before approving
4. **Repo cleanliness** — draft code artifacts do not permanently pollute git history
5. **Doctrine alignment** — "every serious action must be explainable and auditable" (CORE_DOCTRINE rule 8)

---

## Option A: Inside repo, tracked in git

**Structure:**
```
staging/
  builder/
    BUILD-001/
      spec.json
      spec.md
      manifest.json
      sentinel_report.json
      artifacts/
        app/routes/event_query.py
        (diffs/ for modifications)
      status.json
```

**Evaluation:**

| Dimension | Assessment |
|---|---|
| Auditability | High — full git history of every staging build. Anyone with repo access can inspect past builds. |
| Repo cleanliness | Low — rejected and aborted builds accumulate in git history permanently. Draft code becomes part of the repo record. |
| Ease of review | High — operator can browse staging artifacts using any git tooling. |
| Risk to core system | Low for files (staging is isolated from `app/`), but there is a risk of accidentally importing staging Python files if paths are not carefully managed. |
| Doctrine fit | Partially — aligns with auditability doctrine, but permanently storing rejected draft code is not the same as "append-only audit trail." |

**Assessment:** The auditability benefit is real, but polluting git history with draft code artifacts is a practical problem. Rejected builds would permanently occupy repo history. Code review tools would show staging files as changes. Over time this degrades the quality of the git record.

---

## Option B: Outside repo

**Structure:**
```
~/.abode/staging/frank_lloyd/BUILD-001/
  spec.json
  artifacts/...
```

Or a sibling directory: `../abode-staging/BUILD-001/`

**Evaluation:**

| Dimension | Assessment |
|---|---|
| Auditability | Low — staging history is local to one machine. Lost if machine changes. Not accessible for remote review. |
| Repo cleanliness | High — repo is completely unaffected. |
| Ease of review | Low — operator must know where to look; no standard tooling. |
| Risk to core system | Lowest — completely separate from repo. |
| Doctrine fit | Poor — breaks the auditability requirement. A build that has no persistent governance trail is inconsistent with the append-only doctrine. |

**Assessment:** The cleanliness benefit doesn't outweigh the auditability loss. The Abode doctrine is clear that serious actions must be auditable. If Frank Lloyd produces a build that the operator approves and promotes, there should be a permanent record of what Frank Lloyd proposed and what Sentinel said. Outside-repo staging does not provide this without additional infrastructure.

---

## Option C: Hybrid — recommended

**Near-term:**

Staging directory inside the repo at `staging/frank_lloyd/`, **gitignored**. Build artifacts are local and ephemeral. After promotion (or rejection), the governance artifacts — spec, manifest, Sentinel report only, not the code artifacts — are archived to `data/frank_lloyd/archives/{build_id}/` and committed to git. The build log entry at `data/frank_lloyd/build_log.jsonl` is the minimal durable record of every build.

```
# in .gitignore
staging/

# What gets committed after promotion:
data/frank_lloyd/
  build_log.jsonl              # append-only, one line per build event
  archives/
    BUILD-001/
      spec.json                # what was proposed
      manifest.json            # what files were affected
      sentinel_report.json     # what Sentinel said
      # NOT the code artifacts — those are now live at their real paths
```

**Long-term:**

Same pattern, with Frank Lloyd automating the archive step as part of the promotion workflow. After the operator approves promotion, Frank Lloyd: (1) moves artifacts to live paths, (2) copies governance artifacts to archive, (3) appends to build_log.jsonl, (4) deletes the staging build directory.

**Evaluation:**

| Dimension | Assessment |
|---|---|
| Auditability | High — governance trail is durable and committed. Code artifacts are auditable at their live paths via git. |
| Repo cleanliness | High — no draft code in git history. Only governance artifacts (small JSON/markdown) are committed. |
| Ease of review | High — operator reviews staging locally during the review window; governance is archived after. |
| Risk to core system | Low — staging directory is gitignored, never imported, never referenced by live code. |
| Doctrine fit | Strong — append-only audit trail preserved; draft code kept local and ephemeral. Separation of concerns: live code in repo, governance trail in data/builder. |

---

## Recommendation

**Near-term: Option C hybrid.**

`staging/frank_lloyd/` inside repo, gitignored. Governance artifacts archived to `data/frank_lloyd/archives/{build_id}/` after promotion. Build log at `data/frank_lloyd/build_log.jsonl`.

**Long-term: Same pattern with automated promotion workflow.**

Frank Lloyd handles the archive step, build log append, and staging cleanup as part of the promotion sequence. The operator's only action is the approval signal.

---

## Staging directory structure (proposed)

```
staging/                    ← gitignored
  builder/
    {build_id}/             ← e.g. BUILD-001
      spec.json             ← structured frontmatter fields
      spec.md               ← full spec document (human-readable)
      manifest.json         ← file list: what will be created/modified/deleted
      sentinel_report.json  ← Sentinel's output after running against artifacts
      status.json           ← current status (in_build | staged | in_review)
      artifacts/            ← code artifacts mirroring repo structure
        app/
          routes/
            event_query.py  ← (example)
      diffs/                ← for modifications: unified diffs vs current live files
        app.main.py.diff    ← (example)

data/                       ← tracked in git
  builder/
    build_log.jsonl         ← append-only, one entry per status transition
    archives/
      {build_id}/
        spec.json
        manifest.json
        sentinel_report.json
```

---

## Gitignore rule

Add to `.gitignore`:
```
# Frank Lloyd staging area — ephemeral artifacts, never committed
staging/
```

The `data/frank_lloyd/` directory is tracked in git (same pattern as `data/warden_usage.jsonl`, `data/event_log.jsonl`).

---

## Build log entry format

Each entry in `data/frank_lloyd/build_log.jsonl` records one status transition:

```json
{
  "timestamp": "2026-04-11T14:05:00Z",
  "build_id": "BUILD-001",
  "title": "Event log query endpoint",
  "build_type": "platform_capability",
  "risk_level": "high",
  "event": "spec_approved | build_started | staged | sentinel_passed | sentinel_failed | approved | promoted | rejected | aborted",
  "operator": "operator",
  "notes": "optional free text"
}
```

The build log follows the same pattern as `observability/event_log.py` — append-only JSONL, write errors swallowed, malformed lines skipped on read.

---

## Promotion sequence (near-term, manual)

1. Operator reviews `staging/frank_lloyd/{build_id}/spec.md` and artifacts
2. Operator runs Sentinel against staged files
3. Operator approves (or rejects)
4. If approved:
   a. Operator copies artifacts from `staging/frank_lloyd/{build_id}/artifacts/` to live paths
   b. Operator applies any diffs from `staging/frank_lloyd/{build_id}/diffs/`
   c. Operator copies spec.json, manifest.json, sentinel_report.json to `data/frank_lloyd/archives/{build_id}/`
   d. Operator appends "promoted" entry to build_log.jsonl
   e. Operator deletes `staging/frank_lloyd/{build_id}/`
5. If rejected:
   a. Operator appends "rejected" entry to build_log.jsonl
   b. Operator deletes `staging/frank_lloyd/{build_id}/`

This is manual at Stage 1. Frank Lloyd automates steps 4a–4e at later autonomy stages.

---

## Safety rules for the staging area

1. **Never import from staging.** No live Python file should ever have an import path into `staging/`. The gitignore prevents accidental commits; import discipline prevents accidental execution.
2. **Staging is not the build log.** The build log is the durable record. Staging is ephemeral. Do not treat a staging directory as evidence that a build was completed — always check the build log.
3. **One build at a time (near-term).** A `staging/frank_lloyd/.build.lock` file should be created when a build starts and removed on completion/abort — same pattern as `data/campaigns/.campaign.lock`.
4. **Never promote a build that has no Sentinel report.** Even if the Sentinel report says "no tests configured for these files," the report must exist before promotion.
