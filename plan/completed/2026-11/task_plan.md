# Task Plan: FFmpeg lifecycle test timing

## Goal
Diagnose cleanup deadlines, fix CI-sensitive stderr-descendant test without losing regression coverage, validate, commit on feature branch, merge main, and push.

## Phases
- [x] Phase 1: Reproduce and diagnose cleanup timing
- [x] Phase 2: Confirm root cause with controlled failing regression
- [x] Phase 3: Apply minimal test fix
- [x] Phase 4: Validate, record learning, commit, merge, and push

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
**Phase 4 complete** — Fix committed as `30cf883ab56eea1d58a8fac8541be8925fb90f30` and verified as an ancestor of remote `main`. [CI run 40070912493](https://github.com/minhtrancmvn/GPX-Route-Generator/actions/runs/40070912493) passed tests, compilation, dependency consistency, fatal Ruff checks, and Docker build. Original local verification: 209 passed (3.24s), existing Starlette/httpx deprecation warning only; learning database entry recorded. Rechecked on 2026-11-03: all seven FFmpeg lifecycle tests passed in 0.97s. No remaining implementation or release step for this task.

---

# Task Plan: Apply redesign to production GPX app

## Goal
Make production GPX generator reflect accepted redesign while preserving upload, preview, rendering, progress, and download behavior.

## Phases
- [x] Phase 1: Inspect production template, CSS, JavaScript selectors, and prototype
- [x] Phase 2: Establish contextual visual direction and analyze UI blast radius
- [x] Phase 3: Repair corrupted template and finish responsive production UI
- [x] Phase 4: Run regression tests, drive browser workflow, inspect screenshots, and analyze graph changes

## Key Questions
1. Do production controls retain their IDs, payload fields, and defaults?
2. Does real GPX preview/render/download work across landscape and portrait?
3. Does mobile layout avoid overflow and keep preview prominent?

## Decisions Made
- Continue on feat/apply-route-redesign at 67b765d; no new commit, push, or merge without authorization.
- Keep FastAPI/Jinja and real workflows; prototype remains a separate demo.
- Route Atlas Studio direction: survey-paper surfaces, focused dark preview, route blue, DM Sans and Source Sans 3. No fake map or fabricated render state.
- Preview precedes settings on narrow screens; settings and preview sit side by side on desktop.
- Restore original FFmpeg plan verbatim above; append this task rather than discard unrelated history.
- GitNexus bound to GPX-Route-Generator at /Users/coffeemug/Programming/GPX Route Generator. Refreshed index to current branch/HEAD before further edits. Template and stylesheet File impact LOW, zero indexed callers/processes; format update previously showed one direct caller (app.js), no indexed processes. Cross-language template references require response/browser checks too.

## Errors Encountered
- Prior template edit inserted unrelated prose after stylesheet link. Source and HTTP response confirmed corruption; replaced template with clean markup while preserving all control contracts.
- Prior inspection captured corrupted page and was incorrectly named before; final screenshots must be captured separately after repair.
- Prior task plan overwrite discarded unrelated FFmpeg plan; recovered original from HEAD and preserved above.
- Initial draw used unsupported --kind settings; earlier retry used devtools.
- First File impact lookup passed empty target_uid and returned UNKNOWN; explicit File UID resolved to LOW.
- Prior frontend smoke helper read attribute names instead of ID values; replace with assertions against parsed IDs.
- Returned frontend tests used machine-specific path/fallback IDs; replaced with repo-relative source extraction and compact HTML parser, added controlled head-text mutation check. Canonical suite: 215 passed, one existing Starlette/httpx deprecation warning in 3.55s; full output in .taste-skill/verification/pytest.log.
- Source lint originally found four checkerboard gradients and static shadows; removed them. Remaining four warnings are contextual panel labels (three source matches) and focus-only shadow (one), not decorative headings/shadows.
- 320px browser check caught landscape empty-state clipping; mandatory stylesheet impact LOW with zero indexed callers/processes, then hid optional icon at widths up to 360px. Recheck passed layout bounds.
- Initial theme helper read media-query styles before browser painted updated emulation; added double requestAnimationFrame before computed-style assertions.
- Three eyebrow source matches are sentence-case functional panel labels/shared style; one box-shadow is input focus affordance. Kept for orientation and keyboard visibility, not decoration.
- Browser workflow agent used isolated worktree as well as canonical PYTHONPATH. Reviewed its source and JSON evidence; it reports production code untouched. Do not remove either agent worktree; project cleanup policy requires commit and push first, and no such authorization exists.

## Status
**Phase 4 complete** — Canonical suite 215 passed (one existing Starlette/httpx deprecation warning), py_compile, JS syntax, Ruff, pip check, git diff --check passed. Real browser smoke completed with injected offline map provider: invalid GPX rejection/recovery; landscape 1280×720 and portrait 720×1280 PNG preview; advanced controls; both 5s H.264 renders at 6 fps; progress 0→100; playback and MP4 download. Independent ffprobe confirmed both files. Responsive checks at 1440/768/390/320 across both formats found no horizontal overflow or clipping; phone targets 44px+, theme/contrast/reduced-motion/focus checks passed. Inspector: zero findings. GitNexus detect_changes on canonical checkout: three touched JS functions, no affected indexed processes, LOW risk. No commit, push, merge, or deploy performed; production Google Maps credentials/provider not exercised (offline fixture only).
