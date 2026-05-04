# Design

This document is the implementation-level companion to [`architecture.md`](architecture.md). Where architecture answers *what shape is the system*, this answers *what does the code look like, what are its public interfaces, and what invariants does it hold*.

If you are reading this to write code against the framework, this is the document to read carefully. If you are reading it to understand the *why*, read architecture.md first.

---

## Component responsibilities

There are seven components. Each owns a narrow responsibility and exposes a small public surface. The rule of thumb: if a component has more than one reason to change, it is two components.

### 1. `eval_fabric.spec` — the contract layer

**Owns:** EvalSpec and friends. Validation. Versioning.

**Public surface:**

```python
from eval_fabric.spec import EvalSpec, load_spec, validate_spec

spec: EvalSpec = load_spec("path/to/spec.yaml")     # may raise SpecValidationError
validate_spec(spec)                                  # explicit validation, no I/O
```

**Invariants:**

- An `EvalSpec` instance is immutable after construction. All mutations produce a new instance.
- Every `EvalSpec` carries a major-version-pinned `version` field. The framework rejects specs whose major version is unsupported.
- Validation is cheap (≤ 1 ms for typical specs) and side-effect-free.

**Not in scope:** loading datasets, instantiating evaluators, calling models.

### 2. `eval_fabric.registry` — plugin discovery

**Owns:** the mapping from string IDs to evaluator and judge factories.

**Public surface:**

```python
from eval_fabric.registry import (
    get_evaluator, get_judge,
    register_evaluator, register_judge,
    list_evaluators, list_judges,
)

evaluator = get_evaluator("my_team.qa_bot", config={...})
```

**Invariants:**

- IDs are namespaced as `<owner>.<name>` and globally unique within a process.
- Registration is idempotent for identical factories; raises `DuplicateRegistrationError` for conflicting registrations.
- Lookup is O(1) and never performs I/O.

**Not in scope:** evaluator or judge implementation. The registry holds factories, not instances.

### 3. `eval_fabric.runner` — orchestration

**Owns:** concurrency, retry, timeout, span emission, persistence sequencing.

**Public surface:**

```python
from eval_fabric.runner import Runner

runner = Runner(spec=spec, dataset=dataset, trace_store=store)
result: RunResult = runner.run()                      # blocking
result: RunResult = await runner.run_async()          # async variant
```

**Invariants:**

- Tasks are dispatched within an anyio task group with a `CapacityLimiter(spec.runtime.max_concurrent)`.
- Every task is wrapped in `move_on_after(spec.runtime.task_timeout_seconds)`.
- Persistence to the TraceStore happens before the task is marked complete in any in-memory state. This is what makes resume safe.
- The runner emits exactly one OTel span per task and one per judge call. No more, no fewer.
- Runner.run() never returns a partial RunResult. Either it succeeds (all items processed or skipped per policy) or it raises.

**Not in scope:** judging logic, evaluator logic, metric computation.

### 4. `eval_fabric.evaluators` — evaluator protocol and helpers

**Owns:** the `Evaluator` Protocol, common base utilities (rate limiters, retry decorators), and a small set of reference implementations under `eval_fabric.evaluators.contrib`.

**Public surface:**

```python
from eval_fabric.evaluators import Evaluator, EvaluatorOutput, evaluator
from eval_fabric.evaluators.contrib import OpenAICompletionEvaluator

@evaluator(id="my_team.qa_bot", version="1.0.0")
async def qa_bot(item: EvalItem) -> EvaluatorOutput:
    ...
```

**Invariants:**

- An evaluator is a callable with signature `(EvalItem) -> Awaitable[EvaluatorOutput]`.
- Evaluators are stateless from the framework's perspective. Per-call state is fine; cross-call state is the evaluator's problem.
- `id` and `version` are required and immutable after registration.

### 5. `eval_fabric.judges` — judge protocol and reference judges

**Owns:** the `Judge` Protocol, the `Determinism` enum, and three reference implementations: `RuleBasedJudge`, `LLMJudge`, `HumanJudge`.

**Public surface:**

```python
from eval_fabric.judges import Judge, Judgment, Determinism, judge
from eval_fabric.judges.builtin import LLMJudge, RuleBasedJudge

@judge(id="my_team.style", version="1.0.0", determinism=Determinism.SAMPLING_DETERMINISTIC)
async def style_judge(item, output) -> Judgment:
    ...
```

**Invariants:**

- A judge declares its `Determinism` and the framework holds it to that contract during replay.
- A `Judgment` is a typed record, not a free-form string. It includes a structured score and optional rationale.
- Judges do not write to the TraceStore. The runner does.

### 6. `eval_fabric.tracestore` — persistence

**Owns:** the `TraceStore` Protocol and the in-tree SQLite implementation.

**Public surface:**

```python
from eval_fabric.tracestore import TraceStore, SQLiteTraceStore
from eval_fabric.contrib.postgres import PostgresTraceStore     # optional dependency
from eval_fabric.contrib.parquet import ParquetTraceStore       # optional dependency

store = SQLiteTraceStore("./runs/runs.db")
```

**Invariants:**

- Writes are durable on return. `await store.put_trace(t)` returning means the data is on disk (or replicated to whatever backend equivalent).
- Reads are consistent with the most recent committed write within a run.
- The schema version is recorded in the store and checked on open. Mismatch is a hard error.

### 7. `eval_fabric.aggregator` — metrics

**Owns:** computing scoring outputs from a stream of judgments.

**Public surface:**

```python
from eval_fabric.aggregator import aggregate

metrics = aggregate(judgments, scoring=spec.scoring, baseline=baseline_run_id)
```

**Invariants:**

- Aggregation is deterministic. Same inputs, same outputs, byte-identical.
- Aggregation is O(n) in the number of judgments and uses streaming where the scoring config permits.
- Confidence intervals use bootstrap resampling with a seeded RNG for replayability.

---

## Public interfaces

### EvalSpec (Pydantic v2)

```python
class EvalSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    id: SpecId                                  # "team/qa-bot"
    version: SemVer                             # "1.2.0"
    description: str = ""
    evaluator: EvaluatorRef
    judges: list[JudgeRef] = Field(min_length=1)
    scoring: ScoringConfig
    runtime: RuntimeConfig = RuntimeConfig()
    metadata: dict[str, str] = Field(default_factory=dict)


class RuntimeConfig(BaseModel):
    max_concurrent: int = 64
    task_timeout_seconds: float = 60.0
    max_retries: int = 2
    on_failure: Literal["skip", "abort"] = "skip"
    trace_store: str = "sqlite:///./runs/runs.db"


class EvaluatorRef(BaseModel):
    id: str
    config: dict[str, Any] = {}


class JudgeRef(BaseModel):
    id: str
    config: dict[str, Any] = {}
    weight: float = 1.0


class ScoringConfig(BaseModel):
    metrics: list[MetricSpec]
    baseline_run_id: RunId | None = None
```

### Evaluator Protocol

```python
class Evaluator(Protocol):
    id: str
    version: str

    async def __call__(self, item: EvalItem) -> EvaluatorOutput: ...
```

### Judge Protocol

```python
class Determinism(Enum):
    DETERMINISTIC = "deterministic"
    SAMPLING_DETERMINISTIC = "sampling_deterministic"
    STOCHASTIC = "stochastic"


class Judge(Protocol):
    id: str
    version: str
    determinism: Determinism

    async def judge(self, item: EvalItem, output: EvaluatorOutput) -> Judgment: ...
```

### TraceStore Protocol

```python
class TraceStore(Protocol):
    schema_version: int

    async def open(self) -> None: ...
    async def close(self) -> None: ...

    async def put_run(self, run: RunResult) -> RunId: ...
    async def put_trace(self, trace: Trace) -> TraceId: ...
    async def put_judgment(self, judgment: Judgment) -> JudgmentId: ...

    async def get_run(self, run_id: RunId) -> RunResult: ...
    async def get_trace(self, trace_id: TraceId) -> Trace: ...
    async def query_judgments(self, run_id: RunId) -> AsyncIterator[Judgment]: ...
    async def query_traces(self, run_id: RunId) -> AsyncIterator[Trace]: ...
```

### Result records

```python
class Trace(BaseModel):
    id: TraceId
    run_id: RunId
    item_id: str
    evaluator_id: str
    evaluator_version: str
    input: EvalItem
    output: EvaluatorOutput
    spans: list[Span]
    status: Literal["ok", "timeout", "error", "skipped"]
    started_at: datetime
    finished_at: datetime
    error: str | None = None


class Judgment(BaseModel):
    id: JudgmentId
    run_id: RunId
    trace_id: TraceId
    judge_id: str
    judge_version: str
    score: float | bool | str | dict[str, Any]
    rationale: str | None = None
    determinism: Determinism
    started_at: datetime
    finished_at: datetime
```

---

## Invariants

These are the properties the system holds at all times. They are testable and tested.

1. **EvalSpec immutability.** No code path mutates an EvalSpec after construction. Tested in `tests/test_spec_immutability.py`.

2. **Persist-before-complete.** A task is not removed from the in-memory pending set until its trace and judgments are durably persisted. Property-tested in `tests/test_runner_resume.py`.

3. **Idempotent registration.** Re-registering the same `(id, factory)` pair is a no-op. Re-registering with a conflicting factory raises. Tested in `tests/test_registry.py`.

4. **Bounded concurrency.** No more than `runtime.max_concurrent` tasks are in flight at any time. Verified by an instrumented `CapacityLimiter` in `tests/test_runner_concurrency.py`.

5. **Deterministic aggregation.** Given the same judgments and scoring config, `aggregate` returns byte-identical metrics. Verified by hashing the JSON output.

6. **OTel span hygiene.** Exactly one `eval.task` span per item; exactly one `eval.judge.<judge_id>` span per judgment. No nesting violations. Verified by an OTel test exporter in `tests/test_observability.py`.

7. **Replay drift bounds.** Replaying a stored run with deterministic judges produces byte-identical judgments; with sampling-deterministic judges, drift is below the configured tolerance. Tested in `tests/test_replay.py`.

8. **No silent partial runs.** A run either completes (all items processed per `on_failure` policy) or raises. There is no path where `runner.run()` returns a partial result.

If any of these invariants is violated, it is a bug, not a configuration issue.

---

## Things that are deliberately not abstracted

Pulling abstractions out before they earn their keep is a common failure mode. Here are things we left concrete on purpose.

### The OTel exporter

We do not wrap OpenTelemetry behind a generic `Tracer` interface. Code calls `opentelemetry.trace.get_tracer(__name__).start_as_current_span(...)` directly. If you want a different observability backend, configure OTel exporters — that is what they are for. Adding our own indirection layer would be a worse interface than the one OTel already provides.

### The CLI

The CLI is a thin Click application that calls the SDK. There is no service-locator, no command dispatcher, no plugin system for CLI commands. If you need different commands, fork or wrap. Most CLI plugin systems we have seen in similar tools have produced more pain than capability.

### Retry policy

Retries are configured by `(max_retries, retry_on)` in `RuntimeConfig`. There is no policy DSL, no exponential-backoff curve configuration, no jittered-backoff-with-circuit-breaker construct. The retry implementation is ~30 lines using `tenacity` defaults that match what 95% of users want. If you need more, write your own runner — they are not large.

### The dataset abstraction

`Dataset` is `AsyncIterator[EvalItem]`. That is the entire interface. We do not have a `Dataset` base class with `__len__`, `shuffle`, `subset`, or `cache`. Anyone who wants those things can wrap their iterator. We tried building a richer abstraction in v0 and threw it away — every team had a different opinion about what dataset semantics should be, and we were converging on a worse re-implementation of `torch.utils.data.Dataset`.

### Cost tracking

Judges that call paid LLM APIs are responsible for emitting cost as a span attribute (`eval.judge.cost.usd`). The framework aggregates that into a per-run total. We do not track tokens, model versions, or per-vendor pricing. That is the judge's job, not the framework's. We made this call after watching a previous attempt grow into a 4000-line cost-modeling subsystem that was always wrong by 30%.

### Configuration loading

YAML files are loaded with `pyyaml`'s safe loader. Environment variables in YAML are resolved by `${VAR_NAME}` substitution. There is no Hydra, no Pydantic-settings, no Jsonnet. Two of those things are great; none of them are necessary here.

---

## Threading model

`eval-fabric` is single-process, async-concurrent, and **not thread-safe across runners**.

- Within one runner instance, you can have N async tasks (concurrency-bounded). Safe.
- Across runner instances in the same process: not supported. Run them in separate processes if you must.
- Calling sync code from an evaluator: use `anyio.to_thread.run_sync` to avoid blocking the event loop.

We considered building a thread-safe runner. We decided against it because (a) the workload is I/O-bound and gains nothing from threads, and (b) thread-safety is an enormous testing burden for a benefit no production user has asked for.

---

## Versioning of the framework itself

The framework follows semver:

- **Major:** breaking changes to the `EvalSpec` schema, the `Evaluator`, `Judge`, or `TraceStore` protocols, or the CLI surface.
- **Minor:** new fields on `EvalSpec` (with defaults), new optional methods on protocols, new CLI commands.
- **Patch:** bug fixes, performance improvements, internal refactors.

The schema version of `EvalSpec` is **decoupled** from the framework version. Both are tracked. See [ADR-0004](decisions/0004-eval-spec-versioning-with-semver-and-codegen.md).