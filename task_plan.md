# Task Plan: Google Tag Manager installation

## Goal
Install supplied GTM-KR9D2RPW script once near the start of head and supplied noscript immediately after body, with regression coverage.

## Phases
- [x] Phase 1: Inspect template, rendering path, tests, and graph impact
- [x] Phase 2: Confirm minimal installation approach
- [x] Phase 3: Install snippets and add regression test on feature branch
- [x] Phase 4: Run tests, validate diff, and deliver

## Key Questions
1. Which template renders the public page?
2. Are existing tracking tags or content security policy settings relevant?

## Decisions Made
- Branch: feat/google-tag-manager. No commit, push, or deployment requested.
- Install head snippet once despite duplicate paste; preserve supplied container ID and code.
- Replace completed historical task plan for current request; historical plan remains in Git history.
- Scope is GTM bootstrap installation, not new GA4 event definitions or consent UI.

## Errors Encountered
- New GTM regression test failed before installation as expected (missing head snippet).
- First full suite: 208 passed, one failed. Existing page test rejected GTM getTime() due broad substring assertion against Time. Narrowed assertion to visible Time label after LOW function impact (zero callers/processes).

## Status
**Complete locally** - 209 tests passed in 3.25 s; one existing Starlette/httpx deprecation warning. Python syntax check and git diff --check passed. Node execution verified single async GTM script insertion with correct URL and timestamped gtm.js dataLayer event. Rendered-response test verifies placement and no duplicate installation. Changes not committed, pushed, or deployed; live network beacons unverified.

## Impact Evidence
- index.html: LOW, zero indexed direct callers and processes. Literal search confirms app.py renders index.html; no existing GTM or CSP found in source/deployment files.
- tests/test_api.py: LOW, four direct dependents, zero affected processes. Only a new independent test will be added; shared helpers unchanged.
- Python Playwright not installed; validate rendered response and execute bootstrap with Node DOM stub. Live beacon/tag configuration remains outside this installation check.
