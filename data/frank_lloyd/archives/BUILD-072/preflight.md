# Frank Lloyd — BUILD-072 Pre-flight Checklist

**Build ID**: BUILD-072  
**Title**: Create API endpoint provides current portfolio  
**Generated**: 2026-04-12T00:33:17.732308+00:00  
**Status**: Awaiting operator review

---

## 1. Capability reuse check

> Does anything in CAPABILITY_REGISTRY already cover part of this request? Did you check docs/frank_lloyd/ for existing data structures this would use?

**Answer**: No existing capabilities directly provide this functionality.

---

## 2. Existing house domain check

> Does this request belong inside an existing house's domain? Could it be an extension of Belfort, Peter, or an operating service?

**Answer**: The new endpoint aligns with the portfolio management domain.

---

## 3. Minimum file set

> What is the smallest set of files that satisfies the success criterion? Is every proposed file necessary, or is any speculative?

**Answer**: The minimum file set includes only the new endpoint file and its test.

---

## 4. Off-limits file check

> Does this request require touching `app/main.py`, `scripts/ctl.sh`, `app/loop.py`, or `app/routes/neighborhood.py`? If yes: name the file, describe the change, and flag it explicitly.

**Answer**: No off-limits files required. The proposed file set does not include `app/main.py`, `scripts/ctl.sh`, `app/loop.py`, or `app/routes/neighborhood.py`.

---

## 5. Architecture layer compliance

> Where does this artifact sit in the 4-layer model? Does it cross a layer boundary? If so, why is that crossing justified?

**Answer**: The architecture layer is compliant as it serves the frontend.

---

## 6. Blast radius assessment

> What breaks if this artifact contains a bug? Is the failure mode silent (data corruption) or loud (startup crash)? Can rollback happen by deleting one file?

**Answer**: The blast radius assessment indicates minimal risk due to isolation of the new service.

---

## 7. Test coverage plan

> What existing tests cover related behavior? What new tests would be needed? Name the test file(s). Map: source file → test file.

**Answer**: The test coverage plan includes 'app/routes/portfolio_snapshot.py' for the source file and 'tests/test_portfolio_snapshot.py' for the test file.

---

## 8. Approval checkpoint list

> List every human approval gate this build will require, in order.

**Answer**: 1. **Spec approval** (this document) — operator reviews `spec.yaml` + `preflight.md` and approves before any code is written.
2. (Stage 2+) Code review — operator reviews staged code artifacts before promotion to live repo.
3. (Stage 2+) Promotion — operator explicitly promotes staged artifacts to the live repo.

No automated approvals at Stage 1. Spec approval does not authorize Stage 2.

---
