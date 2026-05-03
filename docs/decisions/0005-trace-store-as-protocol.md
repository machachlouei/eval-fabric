# 0005. TraceStore as a Protocol, not a base class

* **Status:** Accepted
* **Date:** 2026-01-26
* **Deciders:** Eval-fabric core team
* **Tags:** plugins, persistence, contracts

## Context and problem statement

Persisted traces and judgments are how the framework delivers reproducibility. Every run of eval-fabric writes to *some* trace store. We need to support different backends — SQLite for local development and small deployments, Postgres for shared multi-team deployments, S3-Parquet for archival — without forcing every backend through one inheritance tree or one set of opinions about transactions.

We also need teams to be able to ship their own backend (e.g., an internal data platform) without modifying the framework.

## Decision drivers

* Backends differ substantially: SQLite has a single writer; Postgres has connection pools; S3 has eventual consistency. A common interface should not paper over these differences.
* The framework calls a small, stable set of methods on the trace store. We do not need a sprawling interface.
* External backends should be easy to write — ideally a single class with five methods.
* Testing should be ergonomic: mocks and fakes should not inherit from a heavyweight base class.

## Considered options

1. **Abstract base class.** `class TraceStore(ABC): @abstractmethod ...`
2. **`Protocol`.** Structural typing — any class with the right methods is a `TraceStore`.
3. **Plugin via entry point only.** No type system constraint; we trust the configured backend at runtime.
4. **Service interface in protobuf.** The trace store is a network service.

## Decision

We chose **`Protocol` typing** for the `TraceStore` interface.

```python
@runtime_checkable
class TraceStore(Protocol):
    schema_version: int

    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def put_run(self, run: RunResult) -> RunId: ...
    async def put_trace(self, trace: Trace) -> TraceId: ...
    async def put_judgment(self, judgment: Judgment) -> JudgmentId: ...
    async def get_trace(self, trace_id: TraceId) -> Trace: ...
    async def query_judgments(self, run_id: RunId) -> AsyncIterator[Judgment]: ...
```

The framework ships `SQLiteTraceStore` in-tree. `PostgresTraceStore` and `ParquetTraceStore` are reference implementations under `eval_fabric.contrib`, distributed in the same package but with optional dependencies.

## Consequences

### Positive

- **No inheritance coupling.** A team's internal trace store can be a class in their own codebase that does not import anything from `eval_fabric`. As long as it has the right methods, it is a `TraceStore`.
- **Test fakes are trivial.** A 30-line in-memory fake is enough for most tests.
- **Backend implementations are honest about their differences.** A backend does not have to satisfy a base-class contract that does not match its semantics. SQLite and Postgres can each implement transactions in the way that fits their model.
- **Type checkers (mypy, pyright) verify shape.** `runtime_checkable` lets us also assert it at runtime, which catches gross mismatches early.

### Negative

- **No shared implementation.** A common ABC could provide a shared `put_judgment_batch` default. With Protocols, every implementer writes their own batching. We mitigate by providing helper functions in `eval_fabric.tracestore.helpers` that any implementer can compose.
- **`runtime_checkable` is not deep.** It checks attribute presence, not signatures. We rely on type checking in CI to catch shape mismatches. Most teams run mypy already.
- **Discoverability is slightly worse.** A newcomer cannot read a base class to see what methods to implement. We address this with a clear interface page in the design doc and a worked example.

### Neutral

- The protocol is intentionally small. We resisted adding methods like `delete_trace` or `update_judgment` because those operations break reproducibility — once a judgment is written, it does not change. Mutable trace stores are a design smell.

## Pros and cons of the options

### Option 1 — Abstract base class

* ✅ Familiar to most Python developers.
* ✅ Can provide concrete default methods.
* ❌ Couples backends to the framework's class hierarchy.
* ❌ Tests must construct subclasses, even for trivial fakes.
* ❌ Backend-specific concerns (transactions, connection pools) get ugly when forced into a common shape.

### Option 2 — `Protocol` (chosen)

* ✅ Decouples backends from the framework.
* ✅ Trivial test doubles.
* ✅ Static checking via mypy/pyright.
* ❌ No shared implementation; some duplication across backends.
* ❌ `runtime_checkable` is shallow.

### Option 3 — Plugin via entry point only, no type contract

* ✅ Maximum flexibility.
* ❌ Errors surface at runtime in the middle of a long eval run, not at registration. Unacceptable.

### Option 4 — Trace store as a network service (e.g., gRPC)

* ✅ Cleanest for multi-tenant deployments.
* ❌ Way too heavy for the local-SQLite case, which is 90% of use.
* ❌ Forces every team to operate a service to run a single eval.

## Implementation notes

- The framework instantiates the trace store from the spec's `runtime.trace_store` URI: `sqlite:///./runs/runs.db`, `postgres://...`, `s3://bucket/path?format=parquet`.
- The URI scheme is dispatched through a small registry inside `eval_fabric.tracestore`. New backends register a factory under `eval_fabric.tracestore.backends` entry point — same pattern as evaluators and judges.
- Trace store schema version is checked on `open()`. Mismatch is a hard error with a migration command suggested in the message.
- Bulk writes are not in the protocol but are encouraged. Implementations should batch internally; the runner streams writes and the backend coalesces.

## What is intentionally not in the protocol

Some operations look like they belong but do not, for design reasons:

- **`delete_trace` / `delete_run`.** Reproducibility requires that runs are immutable once persisted. Deletion is a data-platform concern, not a framework concern. Operators handle retention via backend-native tooling (e.g., S3 lifecycle policies).
- **`update_judgment`.** Same reason. A judge that needs to revise its score should produce a new judgment in a new run, not mutate the old one.
- **Search / query.** Free-form query is a UI concern. The protocol provides `query_judgments(run_id)` because that is what the aggregator needs. Anything richer is the user's responsibility against the backend's native query layer.

## Links

* [PEP 544 — Protocols](https://peps.python.org/pep-0544/)
* [ADR-0002 — Plugins via entry points](0002-evaluator-plugin-via-entry-points.md)
* [ADR-0008 — Determinism contract](0008-judge-determinism-contract.md)