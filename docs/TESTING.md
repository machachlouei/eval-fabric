# Testing

This document is our testing philosophy and the strategy that flows from it. It is not a tutorial on `pytest`. It is an explanation of *what we test, what we deliberately don't, and why*.

If you are about to write tests for a contribution, the [Inner-loop checklist](#inner-loop-checklist) at the bottom is the practical entry point.

---

## Philosophy

A test suite is not a measure of how careful the team is. It is a *load-bearing artifact* — code that runs every change and decides whether to ship. Like any load-bearing artifact, it has to be designed, not just accumulated.

Three principles shape everything below.

### 1. We test invariants, not implementation

Tests assert what the code is *supposed to do*, not how it does it. A test that breaks when an internal helper is renamed is a test that costs more than it earns. We refactor often; tests should not punish refactoring.

Concretely: tests live mostly at the public API surface. Internal modules have a few unit tests where the logic is intricate (e.g., span attribute construction), and almost none where the code is trivially-correct glue.

### 2. We test the seams, not every branch

Every component has well-defined seams: inputs, outputs, and the contracts at the boundary. Test those. Branch coverage as a goal is a trap — it produces tests that fire on every implementation tweak and document nothing about correctness.

The exception: code in the `eval_fabric.runner` module is dense with concurrency and persistence ordering. Branch testing is appropriate there. Almost nowhere else.

### 3. We optimize for diagnostic cost, not coverage cost

When a test fails, an engineer reads the failure message. The cost of a test is paid not when it runs but when it fails. A failure message that says "expected `0.873`, got `0.872`" is cheap to write and expensive to diagnose. A failure message that says "the runner persisted a partial result when the trace store raised on the second judgment" is more expensive to write and trivial to diagnose.

We prefer the second.

---

## The pyramid (mostly)

| Tier            | What it is                                                                      | Where it runs                | Speed target |
| --------------- | ------------------------------------------------------------------------------- | ---------------------------- | ------------ |
| **Unit**        | Pure-function tests with no I/O. Fakes for collaborators.                        | Every commit, locally + CI   | < 50 ms each |
| **Integration** | The runner, registry, and trace store wired together with fakes for the network. | Every PR, CI                 | < 5 s each   |
| **Contract**    | Property tests against protocols (Evaluator, Judge, TraceStore).                 | Every PR, CI                 | < 30 s each  |
| **End-to-end**  | Real network calls to model providers.                                           | Nightly + on-demand          | minutes      |
| **Replay drift**| Run a stored corpus and assert determinism contracts hold.                       | Nightly                      | minutes      |

The shape is roughly pyramidal but two corrections matter:

- **The "integration" tier is wider than usual.** This is a framework that orchestrates other components. Most of the value is in the wiring, not in any one component's logic. We over-invest in integration relative to a typical library.
- **Property-based contract tests are a first-class tier.** Because plugins are duck-typed against `Protocol`, the framework guarantees nothing about a plugin author's correctness — but we do guarantee that any plugin satisfying the contract works with the runner. We codify this with `hypothesis`-driven contract tests that any third party can run against their plugin.

---

## Tooling

| Tool             | Purpose                                          | Why this one                                          |
| ---------------- | ------------------------------------------------ | ----------------------------------------------------- |
| `pytest`         | Test runner.                                     | Standard.                                              |
| `pytest-anyio`   | Async test execution and event-loop fixtures.    | Matches the runtime; see [ADR-0003](decisions/0003-anyio-for-structured-concurrency.md). |
| `hypothesis`     | Property-based tests for protocols and aggregator. | Generates inputs we wouldn't think to write.          |
| `freezegun`      | Time-pinning in tests that touch timestamps.      | Reproducible test output.                              |
| `httpx[mock]`    | Mocking outbound HTTP for evaluator/judge tests. | Same client we use in production.                      |
| `coverage`       | Coverage reporting.                              | Used as a *signal*, not a gate. See below.             |

We **do not** use `tox`. Single supported Python version (3.11+) and a single dependency set.

---

## What we test

### Spec layer

- **Round-trip:** YAML/JSON → `EvalSpec` → YAML/JSON is byte-stable.
- **Validation:** every documented constraint has a test that exercises both a valid and an invalid case.
- **Migrations:** every version-N → version-N+1 migration is exercised on a frozen corpus of test specs in `tests/corpora/specs/`.

### Registry

- **Lookup:** registered factories are returned by ID.
- **Idempotent registration:** re-registering an identical factory is a no-op.
- **Conflict detection:** re-registering a different factory under the same ID raises.
- **Lazy entry-point loading:** plugins declared via entry points are not imported until requested.

### Runner

This is the densest area of the codebase and the most tested.

- **Bounded concurrency:** an instrumented `CapacityLimiter` records max in-flight count; tests assert it never exceeds `max_concurrent`.
- **Persist-before-complete:** a faked TraceStore that fails on the Nth write triggers a runner failure; we then assert that the run has exactly N persisted records and zero "lost" records.
- **Resume:** stop a run mid-flight; resume; assert the union of records produced equals the result of running it once.
- **Timeout:** a slow evaluator triggers timeout cancellation; trace status is `timeout`; the runner does not hang.
- **Retry:** a flaky evaluator that fails K times then succeeds produces exactly K+1 attempts. The trace records `attempt=K+1`.
- **Cancellation propagation:** a Ctrl-C during a run cancels all in-flight tasks and persists what was already complete.

### Trace store (SQLite implementation)

- **Schema version check:** opening a store with the wrong major version raises a clear error, not a SQLITE error.
- **Durability:** writes are visible to a second open of the same database file. (The SQL store uses synchronous=NORMAL; we test for our specific use.)
- **Streaming reads:** `query_judgments` is async and does not load the full result set into memory.

### Judges

- **Built-in judges:** for each shipped judge, both happy path and several malformed inputs.
- **Determinism contract:** for each judge declared `DETERMINISTIC`, run 100 times with the same input and assert byte-identical output. (This is the protection against authors who lie about determinism.)
- **Cost reporting:** judges that emit cost include a `cost_usd` span attribute that aggregates correctly.

### Aggregator

- **Determinism:** same judgments + same scoring → byte-identical metrics.
- **Bootstrap stability:** with a fixed seed, bootstrap CIs are byte-stable.
- **Sample size:** N=1 and N=0 edge cases produce sensible results, not divide-by-zero.

### Observability

- **Span tree shape:** for a small run, the in-memory OTel exporter captures exactly the documented spans in the documented nesting.
- **No payload leak:** trace and judgment objects are persisted, but `EvalItem.input` is not in any span attribute or log message at INFO level.
- **Metric emission:** every metric documented in `observability.md` is emitted by at least one code path under test.

---

## What we deliberately do not test

These are not gaps. They are choices.

### We do not test that Pydantic validates Pydantic things

If you pass a string where Pydantic expects an int, Pydantic raises `ValidationError`. Testing that we have *not* monkey-patched Pydantic into not raising is not productive.

We *do* test our own validators (e.g., `SemVer` parser, custom field validators). Just not stock Pydantic behavior.

### We do not test third-party SDKs

`openai.AsyncOpenAI` works. We do not have tests verifying that. We do test our wrappers — particularly that they handle `httpx.RequestError` and `openai.RateLimitError` correctly — but not the SDK itself.

### We do not test that OpenTelemetry exports work over the network

We test that we *call* OTel correctly (via the in-memory exporter). Whether the OTLP HTTP exporter actually reaches a collector is OTel's responsibility and the operator's configuration.

### We do not test the CLI's argparse handling

`Click` parses flags. We test the *commands* (e.g., `ef run` with a spec produces a run), not the parsing layer. If `Click` regresses, we will hear about it from a thousand other projects first.

### We do not chase 100% coverage

Coverage above ~85% has rapidly diminishing value and starts to incentivize tests that exercise lines without testing meaning. The current target is 85% with no per-file gate; CI reports coverage but does not block on it.

The exception is `eval_fabric.runner`, where we hold a ~95% line + branch target. The runner is where bugs hide and where bugs hurt.

### We do not test performance in PR CI

Performance tests are inherently noisy on CI runners. We have a small benchmarks directory (`bench/`) that runs nightly on a stable runner with `pytest-benchmark`. PRs do not gate on benchmark deltas; we review them weekly.

---

## Determinism and flakiness

A flaky test is worse than no test. It trains the team to ignore failures.

Our standing rule: **a test that fails intermittently is reverted within 24 hours of identification**, then either fixed or retired. There is no "we'll fix it later" for flakes.

### How we make tests deterministic

- **Time:** every test that uses `datetime.now()` is wrapped with `freezegun` or passes an explicit clock argument. There are no real clocks in the unit suite.
- **Randomness:** every test that uses `random` or `numpy.random` seeds it. `hypothesis` tests use a global random seed that CI logs.
- **Concurrency ordering:** tests that depend on task scheduling order use `anyio.fail_after` and explicit synchronization, never `asyncio.sleep` for "wait long enough" semantics.
- **External services:** unit and integration tests mock all network. End-to-end tests that hit real services are isolated to the slow tier and gated by an environment variable.

### When flakes do happen

The standard playbook:

1. Reproduce the flake. If we cannot reproduce in 100 runs, mark the test `@pytest.mark.flaky_under_investigation` (skipped in CI) and file an issue.
2. Identify the source: bad time mock? unsynchronized concurrency? real network call?
3. Fix or rewrite. Do not add `@pytest.mark.flaky` and ship.

We do not have a `flaky` marker in production. The discipline is "fix or remove."

---

## Property-based tests

Property tests live alongside example-based tests. They are most useful for:

- **Aggregator math:** for any list of judgments, `aggregate` is order-invariant and idempotent.
- **Spec round-trips:** for any well-typed `EvalSpec`, `EvalSpec(**spec.model_dump()) == spec`.
- **Migrations:** for any v1 spec generated by Hypothesis, `migrate_v1_to_v2(spec)` produces a valid v2 spec.

Hypothesis is configured with `derandomize=True` in CI: same input set every run, so flakes are reproducible. Locally, you get a fresh seed each time.

---

## Contract test suite for plugin authors

We export a public contract test suite that third-party plugin authors can run against their evaluator or judge:

```python
# In your plugin's tests/
from eval_fabric.testing.contracts import EvaluatorContractTests

class TestMyEvaluator(EvaluatorContractTests):
    @pytest.fixture
    def evaluator(self):
        return MyEvaluator()
```

This runs ~40 assertions about Protocol conformance, async behavior, error handling, and observability. If your plugin passes, it works with the runner. We treat any divergence between the contract suite and runner behavior as a bug — the runner should never depend on something not in the contract.

---

## Inner-loop checklist

When you are writing or modifying tests:

- [ ] Does this test assert an invariant from `design.md` or a behavior from a docstring? (If not, it might be testing implementation.)
- [ ] Will this test fail clearly? (Read the failure message you would see.)
- [ ] Is the test deterministic? (Time mocked? Random seeded? No real network?)
- [ ] Is the test fast? (< 50 ms for unit, < 5 s for integration.)
- [ ] If the test is `@pytest.mark.slow`, is it gated behind `EVAL_FABRIC_RUN_SLOW=1`?
- [ ] If you mocked a third-party SDK, do you have a real-call test in the slow tier that exercises the same path?

---

## Anti-patterns we have tried and abandoned

A short tour of what we used to do and stopped doing.

### `time.sleep` in async tests

We had several "wait for the runner to drain" tests using `await asyncio.sleep(0.5)`. They were flaky on slow CI runners. Replaced with explicit `anyio.Event` synchronization.

### Mocking `eval_fabric` internals

We had tests that mocked `runner._dispatch` and asserted it was called with specific arguments. They broke on every internal refactor without catching real bugs. Removed.

### A single `tests/conftest.py` with 800 lines of fixtures

Centralized fixtures became a coupling layer where everything depended on everything. We split fixtures by module (`tests/runner/conftest.py`, etc.) and limited the top-level conftest to truly cross-cutting fixtures (the OTel exporter, the in-memory trace store).

### Snapshot testing

We tried snapshot testing for the aggregator's metric output. The snapshots became a dumping ground for "looks right to me" without anyone asserting *why* the output was right. Replaced with explicit assertions.

---

## CI configuration

CI runs three tiers on every PR:

1. **Lint and typecheck** (`ruff`, `mypy --strict`) — must pass.
2. **Fast suite** (`pytest -m "not slow"`) — must pass.
3. **Slow suite** (`pytest -m slow`) — runs on a label or on `main`-bound branches; informational on PR.

Nightly:

- Full slow suite against real LLM providers.
- Replay drift suite: run the corpus, compare against the previous night's output, alert on drift exceeding tolerance.
- Benchmark suite: track p95 task latency and runner throughput.

Failures in nightly do not block deploys but page the on-call channel.