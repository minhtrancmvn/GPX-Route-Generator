# Task Plan: FFmpeg lifecycle test timing

## Goal
Diagnose cleanup deadlines, fix CI-sensitive stderr-descendant test without losing regression coverage, validate, commit on feature branch, merge main, and push.

## Phases
- [x] Phase 1: Reproduce and diagnose cleanup timing
- [x] Phase 2: Confirm root cause with controlled failing regression
- [x] Phase 3: Apply minimal test fix
- [ ] Phase 4: Validate, record learning, commit, merge, and push

## Key Questions
1. Does cleanup exceed configured deadlines, or does test measure unrelated scheduling?
2. Can bounded cleanup be asserted independently of machine speed?

## Decisions Made
- Feature branch: fix/ffmpeg-lifecycle-test-timing.
- Initial test impact LOW: zero indexed callers/processes; index refreshed after source mismatch.
- Production code unchanged. Real stderr thread remains blocked until test finally releases it; join must use configured positive timeout exactly once.
- Keep expected stderr-reader error, process kill, no published output; add partial-output deletion check and thread cleanup.
- CI log confirms 0.311431385s elapsed. Existing test fails 3/3 with controlled 0.3s pre-render setup delay despite bounded stderr joins of 0.011–0.013s; fixed test passes 3/3 under same delay.
- Mutation verification rejects unbounded, zero, excessive, skipped joins and missing stderr-reader error. Thirty repeat runs pass with thread count unchanged (1).

## Errors Encountered
- CI c68839d elapsed assertion failed; local target passed three baseline runs. Root cause: whole-render stopwatch conflates setup/scheduling with cleanup, not incorrect cleanup deadline.
- Refreshed graph changed indexed branch; first main-qualified context failed, corrected to feature branch.
- Local .venv lacks Ruff executable; uvx ruff ran identical CI fatal checks successfully.
- First scratch mutation harness copied module globals before monkeypatches, causing route validation error; execute function against live renderer globals instead.
- Isolated review agent saw no uncommitted diff; its clean verdict discarded. Agent worktree already absent; main worktree list verified.
- git diff --check caught extra blank line at plan EOF; removed.

## Status
**Phase 4** - Local verification: 209 passed (3.24s), existing Starlette/httpx deprecation warning only; compileall, pip check, fatal Ruff checks passed. Learning database entry recorded; run graph change analysis, commit feature branch, verify CI before merge/push.
