# Deferred Production Roadmap

These capabilities are deliberately deferred. Current single-process architecture is sufficient until real usage creates the trigger conditions below.

## Browser end-to-end tests

### Implement when

- UI changes frequently
- browser regressions reach users
- multiple browsers/mobile support becomes required
- upload-to-download flow becomes release-critical

### Smallest viable implementation

Use Playwright with Chromium only. Cover:

1. upload valid/invalid GPX
2. preview success/failure
3. render submission and queued/running/completed states
4. HTTP 429 and 503 UI messages
5. MP4 download link
6. keyboard accessibility smoke test

Run smoke tests on pull requests. Keep full cross-browser coverage optional until needed.

### Non-goals

- visual testing across every viewport
- self-healing selectors
- hosted browser service
- broad browser matrix from day one

## Durable database and render queue

### Implement when

- jobs must survive process restarts/deployments
- multiple web/render processes are needed
- renders regularly take several minutes
- retry/cancellation becomes a product requirement

### Smallest viable implementation

- SQLite or PostgreSQL for job metadata
- Redis plus one RQ/Arq/Dramatiq worker for render jobs
- API creates job row and enqueues job ID
- worker renders and updates shared state
- startup marks interrupted jobs failed or requeues by explicit policy

Keep output storage local initially if one worker host remains sufficient.

### Non-goals

- event-sourced job state
- Kubernetes autoscaling
- multi-region queues
- workflow orchestration platform
- exactly-once distributed execution

## Operational dashboards

### Implement when

- app receives regular public traffic
- operational incidents need diagnosis
- Google API cost or render capacity needs active monitoring
- service objectives exist

### Smallest viable implementation

Start with structured logs and a few counters:

- active/queued/rejected renders
- preview/render rate-limit events
- render duration and FFmpeg failures
- Google map request count and latency
- retained jobs and storage bytes
- cleanup deletions/failures

Use existing platform log queries first. Add Prometheus/Grafana, New Relic, Datadog, or CloudWatch dashboards only after these signals prove useful.

### Non-goals

- custom analytics warehouse
- high-cardinality per-user telemetry
- full distributed tracing
- alerting on every metric

## Review cadence

Revisit this document when one trigger condition becomes true. Implement only the smallest relevant section; do not adopt all three capabilities together.
