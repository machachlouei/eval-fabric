# 0006. OpenTelemetry as the only observability primitive

* **Status:** Accepted
* **Date:** 2026-01-29
* **Deciders:** Eval-fabric core team
* **Tags:** observability, runtime

## Context and problem statement

The framework needs to emit telemetry: traces showing the structure of a run, metrics showing throughput and latency, and logs documenting interesting events. Operators of `eval-fabric` deployments need this telemetry to define SLOs, build dashboards, and debug failures.

The temptation in any observability layer is to invent: a `Tracer` interface, a `MetricsClient` interface, a custom log format. This makes the framework harder to integrate, not easier. Operators want to plug eval-fabric into the same observability stack they already operate (Datadog, Grafana, Honeycomb, Splunk, internal). They do not want a bespoke shim.

## Decision drivers

* Operators must be able to ship telemetry to their existing platform without writing adapter code.
* The framework must not require any specific vendor.
* The framework's telemetry must be inspectable by automated tests.
* Plugin authors should emit telemetry the same way the framework does.

## Considered options

1. **Custom `Tracer` / `Metrics` / `Logger` interfaces with pluggable backends.**
2. **OpenTelemetry directly. No abstraction layer.**
3. **`structlog` for logs, Prometheus client for metrics, no traces.**
4. **Vendor-specific (e.g., Datadog SDK).**

## Decision

We chose **OpenTelemetry directly**, with no eval-fabric-specific abstraction layer.

The framework calls `opentelemetry.trace.get_tracer(__name__).start_as_current_span(...)` and `opentelemetry.metrics.get_meter(__name__).create_counter(...)` directly in code paths that need them. We document the spans and metrics we emit; we do not wrap them.

For logs, we use the stdlib `logging` module configured to emit through OTel's logging bridge.

## Consequences

### Positive

- **Operators configure telemetry the way they configure every other Python service.** Set the `OTEL_*` environment variables, install the right exporter, done.
- **No abstraction debt.** When OTel adds a feature (gauges, histograms, exemplars), we use it without coordinating an interface change.
- **Testing is well-supported.** OTel ships in-memory exporters (`InMemorySpanExporter`) that we use to assert span structure in tests.
- **Plugin authors benefit too.** A judge that emits its own spans gets nested correctly inside the runner's spans without coordination.
- **Vendors compete on integration quality, not on whose SDK we picked.** Every observability platform supports OTel.

### Negative

- **OTel API surface is large.** It is not a small library to read. Newcomers may find the entry point intimidating; we mitigate with a short observability primer in `docs/observability.md`.
- **OTel is still maturing in some areas.** Logs and metrics stabilized later than traces. We pin minimum versions and avoid features that are still experimental.
- **No way to silence telemetry without going through OTel's configuration.** Setting `OTEL_TRACES_EXPORTER=none` is the answer; we document it.

### Neutral

- The framework does not log evaluator inputs or outputs at INFO level by default. They can contain sensitive data. This is documented in `SECURITY.md`. Operators who want full payload logs can enable it explicitly via a configuration flag, with the understanding that they are now responsible for their data handling.

## What we emit

### Spans (traces)

| Span name             | Attributes                                                                | When emitted                  |
| --------------------- | ------------------------------------------------------------------------- | ----------------------------- |
| `eval.run`            | `run_id`, `spec_id`, `spec_version`, `dataset_size`                        | One per run, root span         |
| `eval.task`           | `item_id`, `evaluator_id`, `evaluator_version`, `attempt`                  | One per item processed         |
| `eval.judge.<id>`     | `judge_id`, `judge_version`, `determinism`, `cost_usd` (if reported)       | One per judgment               |
| `tracestore.put`      | `record_type`, `latency_ms`                                                | Each persistence call          |

### Metrics

| Metric name                         | Type      | Unit       | Notes                                                              |
| ----------------------------------- | --------- | ---------- | ------------------------------------------------------------------ |
| `eval_fabric.tasks.completed`       | counter   | task       | Labels: `status` (`ok` / `timeout` / `error` / `skipped`).         |
| `eval_fabric.tasks.duration`        | histogram | ms         | Labels: `evaluator_id`. Excludes judge time.                       |
| `eval_fabric.judges.duration`       | histogram | ms         | Labels: `judge_id`, `determinism`.                                  |
| `eval_fabric.judges.cost`           | counter   | USD        | Labels: `judge_id`. Only emitted by judges that report cost.        |
| `eval_fabric.runner.in_flight`      | gauge     | task       | Current in-flight task count.                                       |
| `eval_fabric.tracestore.errors`     | counter   | error      | Labels: `backend`, `op`.                                            |

### Logs

The framework emits structured logs via the stdlib `logging` module:

- `INFO`: run lifecycle (started, completed, resumed).
- `WARNING`: retryable failures, transient errors.
- `ERROR`: terminal failures.

We **do not** log evaluator inputs or outputs by default.

## Pros and cons of the options

### Option 1 — Custom interfaces with pluggable backends

* ✅ Total control over the API surface.
* ❌ We become responsible for integration quality with every observability vendor.
* ❌ Maintenance burden grows with each new backend.
* ❌ Reinvents what OTel already gives us, badly.

### Option 2 — OpenTelemetry directly (chosen)

* ✅ Industry-standard. Every operator already knows it.
* ✅ Vendors do the integration work for us.
* ✅ Test infrastructure is mature.
* ❌ Larger API surface for plugin authors to learn.
* ❌ Some OTel components are still maturing.

### Option 3 — `structlog` + Prometheus, no tracing

* ✅ Smallest possible footprint.
* ❌ No distributed tracing means we cannot answer "which judge took 9 seconds in this run?" without log gymnastics.
* ❌ Prometheus is push/pull-mismatched with batch eval workloads. OTel handles both natively.

### Option 4 — Vendor-specific SDK

* ✅ Excellent first-class integration with that vendor.
* ❌ Hostile to every team using a different vendor.
* ❌ We do not get to make this choice for our users.

## Implementation notes

- We do not initialize OTel in the framework. We assume the host application has done so (or will), and we use whatever tracer/meter/logger the global registry provides. If OTel is not configured, our calls become no-ops, which is the desired behavior.
- We provide a `eval-fabric otel-init` helper command that sets up a sensible default OTel configuration for local development (console exporter, basic batching).
- `docs/observability.md` documents every span and metric. That doc is the source of truth; we keep it in sync with code via a CI check that diffs the doc against a reflected list of spans/metrics declared in the source.

## Links

* [OpenTelemetry Python documentation](https://opentelemetry-python.readthedocs.io/)
* [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/concepts/semantic-conventions/)
* [`docs/observability.md`](../observability.md)