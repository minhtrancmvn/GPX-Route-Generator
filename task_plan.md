# Task Plan: GPX Route Generator Optimization Review

## Goal
Produce evidence-based optimization priorities, measurement plan, and staged implementation roadmap without changing application code.

## Phases
- [x] Phase 1: Inventory architecture, runtime paths, and current validation commands
- [x] Phase 2: Review performance hotspots, resource usage, caching, and client/server boundaries
- [x] Phase 3: Synthesize prioritized optimization plan with metrics, risks, and sequencing
- [x] Phase 4: Verify evidence, preserve existing worktree changes, and deliver plan

## Phase 1/2 Evidence
- `architecture-map.md` records system shape, data flows, deployment constraints, and current-checkout line references.
- `notes.md` records source-backed findings, agent review results, limits, baseline metrics, and proposed sequencing.
- GitNexus MCP could not resolve this repository; direct source inspection used instead.
- Parallel reviews found three O(frame_count²) render paths, event-loop blocking, FFmpeg stderr deadlock potential, unbounded render/job resources, and thread-safety/lifecycle gaps.

## Key Questions
1. Which user flows and execution paths dominate latency, CPU, memory, network, or external API cost?
2. Which optimizations already exist, and where do they leave measurable gaps?
3. What instrumentation and baseline benchmarks are needed before changing behavior?
4. Which improvements are low-risk/high-impact, and which require architectural decisions?
5. How can each proposed change be validated without regressing route rendering correctness?

## Decisions Made
- Keep review read-only for application code; produce recommendations and measurement steps only.
- Treat existing working-tree changes as user-owned; do not modify or revert them.
- Use GitNexus impact/context data when available; repository was absent from MCP registry, so use direct source inspection and available tests/scripts as fallback.
- Prioritize reliability fixes that protect benchmark validity before algorithmic optimization.
- Avoid persistent map caching until duplicate request rate, cache-key correctness, licensing/retention constraints, and quota savings are measured.

## Errors Encountered
- `codebase-overview` fork returned malformed upstream response after timeout; replaced with direct inspection and parallel bounded agents.
- `explore-pipeline` fork returned malformed upstream response after timeout; a partial architecture artifact and direct source inspection supplied equivalent evidence.
- GitNexus MCP registry did not contain this repository; graph impact/context requirements could not run. Direct source/test inspection used and limitation recorded.
- Test suite could not run because current Python environment lacks pytest; graph benchmark also lacks Pillow. Commands and exact failures recorded rather than claiming tests pass.

## Verification Record
- Deliverables: `architecture-map.md`, `notes.md`, `optimization-plan.md`, `task_plan.md` exist in current worktree.
- Existing user changes preserved; no tracked application files edited.
- `python3 --version`: Python 3.14.6.
- `python3 -m pytest -q`: blocked because pytest is not installed (`No module named pytest`).
- `ffmpeg -version`: pass, FFmpeg 9.0.2 present.
- `data/jobs`: 43M, 10 MP4 files at review time.
- Camera benchmark: 450 samples 0.0867s; 900 samples 0.2342s; 1,800 samples 0.5591s. Pillow-dependent graph benchmark unavailable because Pillow is not installed.
- GitNexus impact/context unavailable: repository absent from MCP registry; local index stale.

## Resumed Agent Pass
- Resumed failed architecture/performance agent; completed with correction pass.
- Resumed failed concurrency recheck; completed.
- Resumed failed performance recheck; completed.
- Launched replacement read-only exploration agent; completed.
- Net plan changes: added preview-specific frame-zero planning, map-provider bounded retry policy, speed-graph timestamp decision, zoom-honoring caveat, and unused-helper/dependency notes.
- Confirmed non-issues kept out of plan: `resample_by_distance` is linear; per-render segment reuse already prevents one map request per frame.

## Status
**Complete** - Read-only optimization review delivered; resumed agent findings merged
