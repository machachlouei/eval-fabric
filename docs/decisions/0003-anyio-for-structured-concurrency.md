# 0003. Use `anyio` for structured concurrency in the runner

* **Status:** Accepted
* **Date:** 2026-01-19
* **Deciders:** Eval-fabric core team
* **Tags:** runtime, concurrency

## Context and problem statement

The runner is the only component in `eval-fabric` that owns concurrency. It must dispatch up to 256 in-flight tasks, each calling out to network services (the system under test, the LLM judge, the trace store), with bounded resource usage and clean shutdown semantics.

Concurrency is where async Python codebases routinely go wrong. The `asyncio.gather(*tasks)` pattern is convenient and lethal — one task raising while siblings are mid-flight produces orphaned coroutines, half-written data, and exceptions that swallow other exceptions. Every team that has shipped an LLM eval pipeline has rediscovered this in production.

We need a concurrency primitive that:

- Cancels sibling tasks cleanly when one fails.
- Bounds in-flight work without manually juggling semaphores.
- Surfaces all exceptions, not just the first.
- Has a sane timeout model.
- Is testable without spinning up a real event loop for every test.

## Decision drivers

* Cancellation must be deterministic. A failed task should not leave others orphaned.
* The runner must support both `asyncio` and `trio` for users with different backend preferences (uncommon but real in some research environments).
* Tests must not be flaky. Async test infrastructure has to be solid.
* Code must read like normal control flow, not like a callback maze.

## Considered options

1. **Raw `asyncio` (gather, semaphores, wait_for).** Stdlib only.
2. **`anyio` task groups and capacity limiters.** Backend-agnostic structured concurrency.
3. **`trio` directly.** The original structured-concurrency Python library.
4. **Process pool with synchronous workers (`concurrent.futures`).** Forget async entirely.

## Decision

We chose **`anyio`** as the concurrency primitive in the runner.

Tasks are dispatched within an `anyio.create_task_group()` block, with a `CapacityLimiter(spec.runtime.max_concurrent)` controlling concurrency and `move_on_after(timeout)` for per-task timeouts.

```python
async with anyio.create_task_group() as tg:
    limiter = anyio.CapacityLimiter(spec.runtime.max_concurrent)
    for item in dataset:
        tg.start_soon(_run_one, item, limiter)
```

## Consequences

### Positive

- **Cancellation is correct by construction.** If any task in the group raises, the task group cancels the rest and re-raises. There are no orphans.
- **Exception groups, not exception suppression.** Multiple failures surface as `ExceptionGroup`, not first-write-wins.
- **Backend agnostic.** Users can run on `asyncio` or `trio`. We default to `asyncio`.
- **Timeouts are scoped.** `move_on_after` is composable and does not interact pathologically with cancellation.
- **The code reads top-to-bottom.** No `gather` patterns, no manual `Semaphore.acquire/release`.

### Negative

- **One more dependency.** `anyio` is mature and stable, but it is still a third-party package on the critical path.
- **Slightly steeper learning curve for asyncio veterans.** Engineers who know `asyncio.gather` cold need to learn the `task_group` mental model. Worth the up-front cost.
- **Some libraries we depend on do not understand structured cancellation.** Rare, but when it happens (e.g., a synchronous SDK that ignores `CancelledError`), it requires wrapping with `anyio.to_thread.run_sync` and accepting that cancellation may not be immediate.

### Neutral

- We ship a small pytest fixture (`anyio_backend`) so tests run on `asyncio` by default and on `trio` for compatibility runs in CI.

## Pros and cons of the options

### Option 1 — Raw `asyncio`

* ✅ No new dependency.
* ✅ Universally known.
* ❌ `gather` cancellation semantics are notoriously broken. Fixing them requires `gather(..., return_exceptions=True)`, manual exception-group construction, and careful semaphore work — i.e., reimplementing what `anyio` provides.
* ❌ `asyncio.timeout` (3.11+) is closer to what we want, but the rest of the gather/semaphore composition is still on us.
* ❌ Encourages copy-paste of subtly-wrong concurrency code by every plugin author who tries.

### Option 2 — `anyio` (chosen)

* ✅ Structured concurrency with backend portability.
* ✅ Battle-tested in HTTPX, Starlette, FastAPI ecosystem.
* ✅ Test ergonomics are good (`pytest-anyio`, fixtures, etc.).
* ✅ Documentation and community are healthy.
* ❌ One additional dependency.

### Option 3 — `trio` directly

* ✅ Cleanest structured-concurrency story in Python.
* ✅ Excellent design.
* ❌ Smaller ecosystem. Many third-party HTTP clients and SDKs are asyncio-only or asyncio-first.
* ❌ Forces our users onto `trio`, which is a much smaller community than `asyncio`.

### Option 4 — Process pool with sync workers

* ✅ Trivial to reason about.
* ❌ Process startup overhead is real for short-lived eval tasks.
* ❌ Inter-process communication overhead.
* ❌ Most LLM SDKs have async paths that we would not be using.
* ❌ Memory cost: each worker process has a Python interpreter and library footprint.

## Implementation notes

- Default `max_concurrent` is 64. Raising above 256 typically does not improve throughput because of GIL contention and connection-pool limits in HTTP clients.
- `runtime.task_timeout_seconds` is a per-task ceiling, applied with `move_on_after`. There is no global runner timeout; long runs are normal.
- Retries are layered *outside* the timeout: a retry creates a fresh `move_on_after` scope. A task that times out three times consumes ≤ `3 × task_timeout_seconds`.
- Trace and judgment persistence happens in the same task scope, after the evaluator and judge calls. If persistence fails, the task fails and is subject to the retry policy.

## Links

* [PEP 654 — Exception Groups and `except*`](https://peps.python.org/pep-0654/)
* [`anyio` documentation](https://anyio.readthedocs.io/)
* [Notes on structured concurrency, or: Go statement considered harmful](https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/) — Nathaniel Smith