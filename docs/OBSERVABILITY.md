# Observability

This document is the operator's manual for `eval-fabric` in production. It covers what the framework emits, what to alert on, and how to investigate failures when something goes wrong at 2 AM.

It assumes you have read [`setup.md`](setup.md) (specifically the OTel environment variables) and [ADR-0006](decisions/0006-opentelemetry-for-observability.md) on why observability is OTel-only with no abstraction layer.

---

## What we believe about observability

Three operating principles. Everything below is downstream of these.

**1. Logs are for humans. Metrics are for SLOs. Traces are for debugging.**
We do not page on logs. We do not write dashboards from log strings. Logs document interesting events for humans reading them after the fact. Metrics drive SLOs and pages. Traces answer "where did this run spend its time."

**2. Telemetry is best-effort. Eval is not.**
A run never fails because telemetry failed. The OTel exporter is unreachable? The run completes; spans drop. The metrics endpoint is rate-limited? The run completes; the counter increment is lost. We never compromise the eval to deliver the telemetry.

**3. Alert on symptoms, not causes.**
We do not alert on "judge LLM API returned 429." We alert on "the run-success-rate SLO is burning faster than budget." Causes are for the on-call's investigation, not for the pager.

---

## Logging strategy

The framework uses the stdlib `logging` module configured to flow through the OTel logging bridge. There is no custom logger, no structured-log library, no JSON formatter we ship. Operators configure logging the way they configure logging for any other Python service.

### Levels and what each is for

| Level     | What we log here                                                                              |
| --------- | --------------------------------------------------------------------------------------------- |
| `DEBUG`   | Per-task lifecycle events (dispatch, retry-attempt, persist). Disabled by default.            |
| `INFO`    | Run lifecycle: started, resumed, completed. Plugin discovery results. Trace-store version.    |
| `WARNING` | Retryable failures (transient errors, rate limits). Plugin import failures (skipped, not fatal). |
| `ERROR`   | Terminal failures: trace store down, plugin contract violation, run aborted by `on_failure=abort`. |
| `CRITICAL`| Reserved for "the runner cannot make progress and is exiting." Rare.                          |

`DEBUG` is genuinely verbose: at concurrency=64, a 10k-item run produces ~50k debug records. Operators turn it on for one minute during an incident, then back off.

### What we deliberately do not log

- **Evaluator inputs.** `EvalItem.input` may contain customer data, PII, or proprietary content. It is in the trace store (encrypted at rest where the backend supports it); it is not in logs.
- **Evaluator outputs.** Same reason.
- **Judge rationales.** May contain rephrasings of the input or output. Not in logs.
- **Secrets.** API keys are read from the environment by evaluators and judges; the framework does not see them. If a third-party SDK logs an Authorization header at DEBUG, that is the SDK's problem to fix; we do not redact log records we did not produce.

If you genuinely need full payload logs for an investigation, use `eval_fabric.tracestore.export` to dump traces from the trace store with appropriate access controls. Do not turn on a verbose log mode in production.

### Recommended formatter

For local development:

```python
logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
)
```

For production, your platform's structured-log handler (Datadog Agent, OTel Collector with the logging bridge, Vector, etc.) configured to forward over OTLP. The framework emits standard `LogRecord` objects with the run ID and item ID attached as extras, which any structured handler will surface as fields.

---

## Metrics and SLOs

### What we emit

These are emitted by the framework. Plugin authors may add their own; we recommend they do.

| Metric                              | Type      | Unit       | Labels                                    |
| ----------------------------------- | --------- | ---------- | ----------------------------------------- |
| `eval_fabric.tasks.completed`       | counter   | task       | `status`, `evaluator_id`                  |
| `eval_fabric.tasks.duration`        | histogram | ms         | `evaluator_id`                            |
| `eval_fabric.judges.duration`       | histogram | ms         | `judge_id`, `determinism`                 |
| `eval_fabric.judges.cost`           | counter   | USD        | `judge_id`                                |
| `eval_fabric.runner.in_flight`      | gauge     | task       | (none)                                    |
| `eval_fabric.tracestore.errors`     | counter   | error      | `backend`, `op`                           |

`status` on `tasks.completed` is one of `ok` / `timeout` / `error` / `skipped`. The cardinality is bounded.

`determinism` on `judges.duration` is one of `deterministic` / `sampling_deterministic` / `stochastic` per [ADR-0008](decisions/0008-judge-determinism-contract.md). Useful because the latency profile of stochastic judges (which often involve longer rationales) differs meaningfully from rule-based ones.

### Cardinality budget

`evaluator_id` and `judge_id` are user-defined strings. We assume a typical deployment has fewer than 200 distinct evaluator IDs and 100 distinct judge IDs across all teams. If your deployment exceeds this, your metrics backend may complain — but more importantly, you have a naming-discipline problem upstream.

We do **not** include `run_id`, `item_id`, or any per-item identifier as a metric label. Those are span attributes, not metric dimensions. This is the most common source of metric-cardinality blowups in eval pipelines and we hold a hard line.

### SLOs

The framework ships with default SLOs in `bench/slo.yaml` that operators can adopt or override.

| SLO                              | Target                            | Window  | Notes                                                   |
| -------------------------------- | --------------------------------- | ------- | ------------------------------------------------------- |
| Task success rate                | ≥ 99% (over completed tasks)      | 1 hour  | Excludes `skipped`. Skips are policy, not failure.      |
| Runner overhead                  | p95 ≤ 10 ms per task              | 1 hour  | `tasks.duration` minus the evaluator's own latency.     |
| Judge availability               | ≥ 99% non-error per judge         | 1 hour  | Tracked per `judge_id`. A failing judge is not the framework's failure. |
| Trace-store write latency        | p99 ≤ 100 ms                      | 1 hour  | Backend-dependent. SQLite locally is < 10 ms.            |
| Run completion                   | ≥ 99.5% of runs complete or resume cleanly | 7 days | "Clean" = no orphaned tasks, no corrupted traces.       |

These are the numbers we hold ourselves to. Your team may run looser or tighter; the SLO file is configuration.

### Alerts

We define four standard alerts. They are **the only alerts the framework recommends paging on**.

| Alert                              | Condition                                              | Severity |
| ---------------------------------- | ------------------------------------------------------ | -------- |
| **Task success burn**              | Burn rate > 14.4× for 1h on the success-rate SLO       | Page     |
| **Trace store unavailable**        | `tracestore.errors{op="put_*"}` > 0 sustained 5 min    | Page     |
| **Runner stuck**                   | `runner.in_flight` > 0 with no `tasks.completed` change for 10 min | Page     |
| **Judge cost anomaly**             | `judges.cost` rate > 3× rolling 7d baseline            | Ticket   |

Things we deliberately do **not** alert on:

- 429 from the judge LLM API. That is a rate-limit; the runner backs off and retries. Page on the *symptom* (success-rate burn) if it actually causes a problem.
- Plugin import failure. The framework continues; the plugin is not used by anything until it is, at which point it raises a config error visible to the user.
- High latency on a single judge. Latency by itself is not a problem; SLO violations are.

---

## Traces

The runner emits a structured span tree that any OTel-compatible viewer (Jaeger, Tempo, Datadog APM, Honeycomb) renders cleanly.

### Span hierarchy

```
eval.run                           [run_id, spec_id, spec_version, dataset_size]
├── eval.task                       [item_id, evaluator_id, evaluator_version, attempt]
│   ├── (evaluator-internal spans, if the evaluator emits them)
│   ├── eval.judge.exact_match      [judge_id, judge_version, determinism]
│   ├── eval.judge.llm_factuality   [judge_id, judge_version, determinism, cost_usd]
│   └── tracestore.put              [record_type=trace, latency_ms]
├── eval.task                       ...
├── eval.task                       ...
└── tracestore.put                  [record_type=run, latency_ms]
```

### Span attributes

Every span carries the run ID. Every task span carries the item ID and evaluator ID. Every judge span carries the judge ID and the determinism class.

Rules we hold to:

- **One `eval.task` span per item.** Retries do not produce new spans; they update the `attempt` attribute.
- **One `eval.judge.<id>` span per judgment.** Multiple judges → multiple sibling spans under the task.
- **Span events** for retries: `event.name="task.retry"` with `attempt` and `error.type` attributes. This way you can see retries on a single span instead of multiplying spans.

### What to do with traces

Three queries that are useful in practice. Adapt to your trace UI of choice:

- **Slow tasks for a run:** filter by `run_id`, sort `eval.task` spans by duration descending. Top-1% are the items to look at.
- **Judge cost attribution:** sum `cost_usd` attribute on `eval.judge.*` spans grouped by `judge_id`. Where is the money going.
- **Retry rate by evaluator:** count `task.retry` events grouped by `evaluator_id`. High retry rate = upstream flake.

### Sampling

The framework does **not** sample its own spans. Eval workloads are not high-volume relative to production request traffic — a 10k-item run generates 30k–50k spans, well within the budget of any modern tracing backend. If you need to sample (e.g., 1M-item runs), configure OTel's `TraceIdRatioBased` sampler in your application bootstrap. We do not paper over sampling decisions in framework code.

---

## Failure investigation workflow

When something goes wrong, the order of operations matters. This is the playbook we follow.

### Step 1: classify the symptom

What is the user-visible symptom?

- **A run completed but metrics look wrong.** → Skip to "Investigating bad metrics."
- **A run did not complete.** → Continue to step 2.
- **CI gate failed unexpectedly.** → Compare against baseline run; almost always a real signal, not infrastructure.
- **Telemetry stopped flowing.** → Check OTel collector health first. Don't blame the framework before you've confirmed the pipeline.

### Step 2: locate the run

Every framework log line carries the `run_id`. Every span carries the `run_id`. Find it from the user report or the failing CI job.

```bash
ef show <run_id>
```

This prints the run summary, including which item it stopped on (if it stopped) and the most recent error.

### Step 3: determine where it stopped

```bash
ef show <run_id> --traces --status error,timeout
```

Returns the traces in non-OK status. From here you can tell:

- All errors clustered on one evaluator/judge → the evaluator/judge is broken.
- Errors spread evenly across evaluators → the trace store or the runner is broken.
- One error, then everything → the runner aborted; check `on_failure` policy.

### Step 4: read the spans

Open the trace in your OTel viewer. The span structure is documented above; you should see the run span and child task spans. If you do not, telemetry is broken — investigate that separately.

A pattern to look for: a task span that opened but never closed. This is almost always a process kill mid-task. The trace store will have the trace because we persist before completing; you can resume the run.

### Step 5: resume or replay

```bash
ef resume <run_id>          # continue from the last persisted item
ef replay <run_id>          # re-run every item, asserting determinism contracts
```

`resume` is for runs killed by infrastructure. `replay` is for confirming reproducibility or for diagnosing whether a recent change shifted results.

### Step 6: investigating bad metrics

If metrics look wrong but the run technically completed:

1. **Did the judge change?** `ef diff <run_id> <baseline_run_id> --by judge_version` shows whether you are comparing apples to apples.
2. **Did the evaluator change?** Same with `--by evaluator_version`.
3. **Is one judge dominating?** Look at the per-judge metrics breakdown. A flaky LLM judge can drag a metric without changing the system.
4. **Sample size?** A 0.02 delta on N=100 is noise. The framework's bootstrap CI tells you whether the delta is meaningful.

### Common patterns we have seen and what they mean

| Pattern                                                              | Likely cause                                              | Fix                                                       |
| -------------------------------------------------------------------- | --------------------------------------------------------- | --------------------------------------------------------- |
| 429 storm in `tracestore.errors` for `op=put_*`                       | A scheduled task at the same time is hammering Postgres.  | Lower judge concurrency; stagger schedules.               |
| `runner.in_flight` plateaus below `max_concurrent`                    | Evaluator or judge has its own concurrency limit.         | Look at evaluator/judge logs for explicit throttling.     |
| `tasks.duration` p95 doubles overnight                                | Provider-side change (model rolled out, region shifted).  | Compare span attributes for `model` between runs.         |
| Replay drift > tolerance for a `DETERMINISTIC` judge                  | Judge author lied about determinism.                      | `ef judge verify <id>` to measure observed variance.      |
| `tasks.completed{status=skipped}` > 0 unexpectedly                    | An evaluator raised a non-retryable exception.            | Check the trace's `error` field; usually a config issue.  |
| Run completes in 30s with `dataset_size=10000`                        | Dataset adapter returned an empty iterator.               | Look at the dataset URI; permissions, path, or filter.    |

---

## What we deliberately did not build

A few observability features we have considered and rejected. Including them here so future contributors do not relitigate.

### A built-in dashboard

The framework does not ship a UI. Operators have Datadog, Grafana, Honeycomb, or internal tools — they do not need another one. We provide a Grafana JSON template (`contrib/grafana/eval-fabric.json`) that uses our standard metrics and spans, but we do not run a service.

### A custom alerting DSL

`bench/slo.yaml` is just a documentation artifact and an export to your alerting system. We do not interpret it at runtime. Alerting belongs in your alerting system, configured the way you configure everything else.

### Anomaly detection on judge scores

A "your judgment scores look weird this week" feature was discussed and rejected. It is a model-monitoring concern, served better by purpose-built tools (Arize, Fiddler, internal). We export judgments cleanly enough that you can wire them into those tools.

### Per-team dashboards

Multi-tenant slicing is a reporting layer concern, not a framework concern. The framework attaches the spec ID and team metadata as standard attributes; your dashboards filter by those attributes.

---

## Calibration with operators

Once a quarter, the team running this framework should walk through this document with the platform team running the observability stack and confirm:

- The metrics we emit are the metrics they want to see.
- The cardinality is acceptable to the metrics backend.
- The alerts we recommend match what the on-call expects to be paged on.
- The trace volume is sustainable on the current sampling configuration.

This is not optional ceremony. It is how observability stays useful instead of becoming background noise nobody trusts.