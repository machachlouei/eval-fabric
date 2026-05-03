# eval-fabric

> A pluggable evaluation orchestration framework for LLM and agentic systems.
> One contract, many evaluators, async by default.

[![CI](https://img.shields.io/badge/ci-pending-lightgrey)]()
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![Status](https://img.shields.io/badge/status-alpha-orange)]()

---

## The problem

When an organization runs more than one AI product, evaluation fragments. Each team builds its own harness, writes its own LLM-as-judge prompts, and stores results in its own format. Within twelve months you have:

- Five different definitions of "accuracy."
- No way to compare a regression in Product A against a baseline in Product B.
- Every team rewriting the same retry, concurrency, and tracing code.
- Eval results that are not reproducible because the evaluator's version is implicit.
- CI/CD that cannot gate on quality because there is no canonical "did this pass" signal.

The cost is not just duplicated work. It is **trust**. Leadership cannot answer "is the system getting better?" because no two teams are measuring the same thing.

`eval-fabric` exists to make eval a **platform concern**, not a per-team concern. It defines a single set of contracts — what an eval is, what an evaluator is, what a judgment is — and provides a runtime that any team can plug their evaluators and judges into.

It is opinionated about **structure** (versioned contracts, async-first, OpenTelemetry-instrumented) and unopinionated about **choices** (which judge model, which storage backend, which CI system).

## Target user

`eval-fabric` is for the engineer or team responsible for **eval infrastructure across multiple AI products**. Specifically:

- Platform / eval-infra engineers at organizations with 2+ AI products and 50+ engineers.
- Tech leads consolidating fragmented per-team eval tools onto a shared substrate.
- ML / LLM engineers who want to ship a reproducible eval pipeline without rebuilding orchestration.
- Anyone wiring eval into CI/CD and needing a stable machine-readable result format.

It is **not** a good fit for a single notebook, a one-off benchmark run, or a team that wants a UI out of the box. See [Non-goals](#non-goals).

## Goals

1. **One contract.** A single versioned schema for what an evaluation *is*. Inputs, outputs, judgments, and traces are all typed and persistable.
2. **Pluggable evaluators and judges.** A registry that discovers implementations via Python entry points or explicit registration. No inheritance hierarchies.
3. **Async-first orchestration.** Concurrency, retries, timeouts, and resource budgets are framework concerns, not per-evaluator concerns.
4. **Reproducibility by default.** Given a pinned `(EvalSpec, Dataset, Evaluator, Judge)`, the system records enough state to replay the run.
5. **Observable.** OpenTelemetry traces, metrics, and logs are emitted by the runner; every framework deployment ships with a baseline SLO dashboard.
6. **Machine-readable results.** Judgments are first-class typed objects, not free-form strings, so CI gates and dashboards work without parsing.

## Non-goals

These are deliberately out of scope. The framework is more useful for being narrower.

- **Not a model serving platform.** Evaluators call models; the framework does not host them.
- **Not a dataset versioning system.** We integrate with DVC / lakeFS / Hugging Face Datasets; we do not replace them.
- **Not a UI or dashboard product.** We expose stable result schemas and OTel signals; visualization is a separate concern with many good tools.
- **Not a benchmark registry.** No curated datasets ship with the framework. Teams own their datasets.
- **Not opinionated about which judge model to use.** GPT-4-class, Claude, fine-tuned local — all are first-class plugins.
- **Not a workflow engine.** For multi-stage agentic *production* pipelines, use Airflow / Temporal / LangGraph. eval-fabric orchestrates *evaluation* workflows.

## High-level architecture

```
                ┌──────────────────────────────────────────┐
                │              EvalSpec (v1.x)             │
                │  inputs · evaluators · judges · scoring  │
                └────────────────────┬─────────────────────┘
                                     │
                       ┌─────────────▼─────────────┐
                       │           Runner          │
                       │  (anyio · concurrency ·   │
                       │   retries · OTel spans)   │
                       └──┬───────────────────┬────┘
                          │                   │
              ┌───────────▼─────┐    ┌────────▼────────┐
              │  Evaluator(s)   │    │     Judge(s)    │
              │ system-under-   │    │  LLM · rule ·   │
              │     test        │    │     human       │
              └───────────┬─────┘    └────────┬────────┘
                          │                   │
                          └─────────┬─────────┘
                                    │
                       ┌────────────▼────────────┐
                       │       TraceStore        │
                       │ SQLite · Postgres · S3  │
                       └────────────┬────────────┘
                                    │
                          ┌─────────▼─────────┐
                          │     Aggregator    │
                          │  metrics · deltas │
                          └───────────────────┘
```

A run is `(EvalSpec, Dataset) → Runner → JudgmentSet`. Evaluators produce outputs. Judges score outputs. The Runner orchestrates both with a fixed set of operational guarantees (concurrency, retry, timeout, observability). The TraceStore persists everything by content-hash for replay.

For the full diagram, component contracts, and data flow, see [`docs/architecture.md`](docs/architecture.md).

## Key technical decisions

These shape what the framework does and does not do. Each links to its full ADR.

- **Pydantic v2 for all eval contracts.** Single source of truth, automatic JSON Schema, and strong runtime validation. Protobuf was considered and rejected for ergonomic reasons. → [ADR-0001](docs/decisions/0001-use-pydantic-for-eval-contracts.md)
- **Plugin discovery via Python entry points.** Evaluators and judges are registered the same way `pytest` plugins are. No base classes, no inheritance. → [ADR-0002](docs/decisions/0002-evaluator-plugin-via-entry-points.md)
- **Structured concurrency with `anyio`.** Backend-agnostic (asyncio or trio), task groups, cancellation scopes. Avoids the foot-guns of raw `asyncio.gather`. → [ADR-0003](docs/decisions/0003-anyio-for-structured-concurrency.md)
- **EvalSpec is semver-versioned with codegen migrations.** Breaking schema changes go through a migration script; consumers pin a major version. → [ADR-0004](docs/decisions/0004-eval-spec-versioning-with-semver-and-codegen.md)
- **TraceStore is a `Protocol`, not a base class.** Backends are duck-typed. SQLite ships in-tree; Postgres and S3-Parquet are reference adapters. → [ADR-0005](docs/decisions/0005-trace-store-as-protocol.md)
- **OpenTelemetry is the only observability primitive.** No custom logger, no custom metrics interface. → [ADR-0006](docs/decisions/0006-opentelemetry-for-observability.md)
- **Evaluator and Judge are separate roles.** An evaluator produces an output (it is the system under test, or a wrapper). A judge scores it. Conflating them, as some frameworks do, makes auto-evaluator drift impossible to reason about. → [ADR-0007](docs/decisions/0007-separate-evaluator-and-judge.md)
- **Judges declare a determinism contract.** Each judge declares whether it is deterministic, sampling-deterministic (seed-pinned), or stochastic — so replay knows what guarantees to expect. → [ADR-0008](docs/decisions/0008-judge-determinism-contract.md)

## Quick start

```bash
# Install
pip install eval-fabric

# Scaffold a new eval
ef init my-eval --evaluator=my_team.qa_bot --judge=eval_fabric.judges.exact_match

# Run it
ef run ./my-eval/spec.yaml --dataset ./my-eval/data.jsonl --concurrency 16

# Inspect results
ef show ./runs/2026-05-03T18-42-11Z --metric accuracy
```

A 30-second tour of the result object:

```python
from eval_fabric import load_run

run = load_run("./runs/2026-05-03T18-42-11Z")
print(run.eval_spec.id, run.eval_spec.version)   # qa-bot/v1.2.0
print(run.metrics.aggregate("accuracy"))          # 0.873 ± 0.012 (n=2400)
print(run.judgments[0].judge_id, run.judgments[0].score)
```

For the full setup including dev environment, OTel collector wiring, and CI integration, see [`docs/setup.md`](docs/setup.md).

## Success criteria

The framework is meant to be load-bearing. Concretely:

| Dimension       | Target                                                                                              |
| --------------- | --------------------------------------------------------------------------------------------------- |
| **Throughput**  | 10k judgments/minute on a single 8-core node with a remote LLM judge (network-bound).               |
| **Concurrency** | 256 in-flight tasks per runner instance with bounded memory (no unbounded queue growth).            |
| **Latency**     | Runner overhead per task ≤ 10 ms p95 (excluding evaluator and judge time).                          |
| **Correctness** | Replaying a stored run produces byte-identical judgments for deterministic judges; ≤ 1% drift for sampling-deterministic judges with the same seed. |
| **Schema**      | Zero breaking changes within a major version. Migrations are tested round-trip on every PR.         |
| **Adoption**    | A new team can run their first eval through the framework in ≤ 30 minutes following the quickstart. |
| **Operability** | Default OTel dashboard surfaces success rate, p95 latency, judge cost, and queue depth.             |

These are the numbers we hold ourselves to. When they slip, that is a P1.

## Documentation map

| Document                                                                       | Purpose                                                       |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------- |
| [`docs/architecture.md`](docs/architecture.md)                                 | System design: components, data flow, tradeoffs, failure modes |
| [`docs/design.md`](docs/design.md)                                             | Implementation-level interfaces and invariants                |
| [`docs/concepts.md`](docs/concepts.md)                                         | Core domain concepts and mental models                        |
| [`docs/setup.md`](docs/setup.md)                                               | Local development environment                                 |
| [`docs/testing.md`](docs/testing.md)                                           | Quality strategy and testing philosophy                       |
| [`docs/observability.md`](docs/observability.md)                               | Logging, metrics, SLOs, incident workflow                     |
| [`docs/decisions/`](docs/decisions/)                                           | Architecture Decision Records (MADR format)                   |
| [`SECURITY.md`](SECURITY.md)                                                   | Threat model and vulnerability reporting                      |
| [`CONTRIBUTING.md`](CONTRIBUTING.md)                                           | Branching, PRs, review philosophy, coding standards           |
| [`ROADMAP.md`](ROADMAP.md)                                                     | Near-term, long-term, and known limitations                   |

## License

Apache 2.0. See [`LICENSE`](LICENSE).