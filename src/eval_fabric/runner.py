"""The runner: orchestration, concurrency, retries, persistence, telemetry.

This is the densest module in the codebase. The invariants the rest of the
framework relies on are enforced here, not at call sites:

- Bounded concurrency via ``anyio.CapacityLimiter``.
- Per-task timeout via ``anyio.move_on_after``.
- Retry on declared transient errors with bounded attempts.
- Persist before complete: the trace and its judgments are durable before the
  runner considers the task finished.
- Exactly one ``eval.task`` span per item; one ``eval.judge.<id>`` per judge.

See ADR-0003 for the concurrency choice and ``docs/design.md`` for the public
surface.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, AsyncIterable, Iterable, cast

import anyio

from eval_fabric.aggregator import aggregate
from eval_fabric.dataset import as_async_iter
from eval_fabric.errors import RunAborted, TransientError
from eval_fabric.judges import Judge
from eval_fabric.models import (
    Determinism,
    EvalItem,
    EvaluatorOutput,
    Judgment,
    RunResult,
    Span,
    Trace,
    TraceStatus,
    new_id,
    utcnow,
)
from eval_fabric.observability import instruments, span as otel_span
from eval_fabric.registry import get_evaluator, get_judge
from eval_fabric.spec import EvalSpec
from eval_fabric.tracestore import TraceStore, open_trace_store

log = logging.getLogger(__name__)


class Runner:
    """Synchronous public face of the orchestration layer.

    The implementation is async; ``run()`` is a thin ``anyio.run`` wrapper for
    callers that are not in an event loop. Async-native callers use
    ``run_async()``.
    """

    def __init__(
        self,
        *,
        spec: EvalSpec,
        dataset: Iterable[EvalItem] | AsyncIterable[EvalItem],
        trace_store: TraceStore | str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.spec = spec
        self.dataset = dataset
        self.run_id = run_id or new_id("run")
        if trace_store is None:
            trace_store = open_trace_store(spec.runtime.trace_store)
        elif isinstance(trace_store, str):
            trace_store = open_trace_store(trace_store)
        self.trace_store: TraceStore = trace_store

    # -- Public API ---------------------------------------------------

    def run(self) -> RunResult:
        """Execute the spec to completion. Synchronous from the caller's POV."""

        return anyio.run(self.run_async)

    async def run_async(self) -> RunResult:
        """Execute the spec to completion asynchronously."""

        await self.trace_store.open()
        try:
            return await self._run_inner()
        finally:
            await self.trace_store.close()

    # -- Internal -----------------------------------------------------

    async def _run_inner(self) -> RunResult:
        evaluator = get_evaluator(self.spec.evaluator.id, config=self.spec.evaluator.config)
        judges: list[Judge] = [
            get_judge(j.id, config=j.config) for j in self.spec.judges
        ]

        run = RunResult(
            id=self.run_id,
            spec_id=self.spec.id,
            spec_version=self.spec.version,
            spec=self.spec.model_dump(mode="json", by_alias=True),
            started_at=utcnow(),
            status="running",
        )
        await self.trace_store.put_run(run)

        with otel_span(
            "eval.run",
            attributes={
                "run_id": run.id,
                "spec_id": self.spec.id,
                "spec_version": self.spec.version,
            },
        ):
            counts: dict[str, int] = {"ok": 0, "timeout": 0, "error": 0, "skipped": 0}
            judgments: list[Judgment] = []
            limiter = anyio.CapacityLimiter(self.spec.runtime.max_concurrent)
            cost_total = 0.0
            failure_reasons: list[str] = []

            async def worker(item: EvalItem) -> None:
                nonlocal cost_total
                trace, item_judgments = await self._run_one_task(
                    item=item,
                    evaluator=evaluator,
                    judges=judges,
                    limiter=limiter,
                )
                counts[trace.status] = counts.get(trace.status, 0) + 1
                if trace.status in ("error", "timeout") and trace.error:
                    failure_reasons.append(f"{item.item_id}: {trace.error}")
                judgments.extend(item_judgments)
                for j in item_judgments:
                    if j.cost_usd is not None:
                        cost_total += j.cost_usd

            async with anyio.create_task_group() as tg:
                async for item in as_async_iter(self.dataset):
                    tg.start_soon(worker, item)

            terminal_failures = counts["error"] + counts["timeout"]
            should_abort = (
                terminal_failures > 0 and self.spec.runtime.on_failure == "abort"
            )

            run = run.model_copy(
                update={
                    "finished_at": utcnow(),
                    "counts": counts,
                    "total_cost_usd": cost_total,
                    "status": "aborted" if should_abort else "completed",
                    "metrics": aggregate(judgments, self.spec.scoring),
                    "dataset_size": sum(counts.values()),
                    "error": "; ".join(failure_reasons) if should_abort else None,
                }
            )
            await self.trace_store.put_run(run)

            if should_abort:
                raise RunAborted(
                    f"run {run.id} aborted: {terminal_failures} terminal failure(s); "
                    f"first: {failure_reasons[0] if failure_reasons else '(no reason)'}"
                )
            return run

    async def _run_one_task(
        self,
        *,
        item: EvalItem,
        evaluator: Any,
        judges: list[Judge],
        limiter: anyio.CapacityLimiter,
    ) -> tuple[Trace, list[Judgment]]:
        """Run one item: evaluator + every judge, with retries and persistence."""

        async with limiter:
            inst = instruments()
            inst.runner_in_flight.add(1)
            try:
                trace, judgments = await self._dispatch_item(
                    item=item,
                    evaluator=evaluator,
                    judges=judges,
                    inst=inst,
                )
            finally:
                inst.runner_in_flight.add(-1)

        # Persist trace and judgments. Order matters: trace first so a judgment
        # never references a non-existent trace_id.
        await self._persist_trace(trace)
        for j in judgments:
            await self._persist_judgment(j)
        return trace, judgments

    async def _dispatch_item(
        self,
        *,
        item: EvalItem,
        evaluator: Any,
        judges: list[Judge],
        inst: Any,
    ) -> tuple[Trace, list[Judgment]]:
        trace_id = new_id("trc")
        attempt = 0
        last_error: str | None = None
        output: EvaluatorOutput | None = None
        status: str = "error"
        spans: list[Span] = []
        evaluator_started = utcnow()
        evaluator_finished = evaluator_started

        with otel_span(
            "eval.task",
            attributes={
                "run_id": self.run_id,
                "item_id": item.item_id,
                "evaluator_id": getattr(evaluator, "id", "<unknown>"),
                "evaluator_version": getattr(evaluator, "version", "<unknown>"),
            },
        ) as task_span:
            while attempt <= self.spec.runtime.max_retries:
                attempt += 1
                evaluator_started = utcnow()
                timed_out = False
                try:
                    with anyio.move_on_after(
                        self.spec.runtime.task_timeout_seconds
                    ) as cancel_scope:
                        output = await evaluator(item)
                    if cancel_scope.cancel_called:
                        timed_out = True
                        last_error = (
                            f"task exceeded timeout of "
                            f"{self.spec.runtime.task_timeout_seconds}s"
                        )
                        status = "timeout"
                    else:
                        status = "ok"
                        last_error = None
                        break
                except TransientError as exc:
                    last_error = str(exc)
                    status = "error"
                    task_span.add_event(
                        "task.retry",
                        {"attempt": attempt, "error.type": type(exc).__name__},
                    )
                    continue
                except Exception as exc:  # noqa: BLE001 — non-retryable terminal
                    last_error = str(exc)
                    status = "error"
                    break
                finally:
                    evaluator_finished = utcnow()

                if timed_out and attempt <= self.spec.runtime.max_retries:
                    # Retries are layered outside the timeout (ADR-0003).
                    task_span.add_event("task.retry", {"attempt": attempt})
                    continue
                if timed_out:
                    break

            duration_ms = (evaluator_finished - evaluator_started).total_seconds() * 1000
            task_span.set_attribute("attempt", attempt)
            inst.tasks_duration.record(
                duration_ms,
                attributes={"evaluator_id": getattr(evaluator, "id", "<unknown>")},
            )
            trace = Trace(
                id=trace_id,
                run_id=self.run_id,
                item_id=item.item_id,
                evaluator_id=getattr(evaluator, "id", "<unknown>"),
                evaluator_version=getattr(evaluator, "version", "<unknown>"),
                input=item,
                output=output,
                spans=spans,
                status=status,  # type: ignore[arg-type]
                started_at=evaluator_started,
                finished_at=evaluator_finished,
                attempt=attempt,
                error=last_error,
            )

            if status != "ok" or output is None:
                # Failed evaluator calls do not produce judgments; the trace's
                # own status carries the diagnosis. The runner consults
                # `on_failure` after the whole task group finishes.
                _record_task_completed(inst, trace)
                return trace, []

            judgments = await self._run_judges(
                item=item,
                output=output,
                trace=trace,
                judges=judges,
                inst=inst,
            )
            judge_errors = [j for j in judgments if j.error]
            if judge_errors:
                error_summary = "; ".join(
                    f"{j.judge_id}: {j.error}" for j in judge_errors
                )
                trace = trace.model_copy(
                    update={
                        "status": cast(TraceStatus, "error"),
                        "error": f"judge failure(s): {error_summary}",
                    }
                )
            _record_task_completed(inst, trace)
            return trace, judgments

    async def _run_judges(
        self,
        *,
        item: EvalItem,
        output: EvaluatorOutput,
        trace: Trace,
        judges: list[Judge],
        inst: Any,
    ) -> list[Judgment]:
        judgments: list[Judgment] = []
        for judge in judges:
            with otel_span(
                f"eval.judge.{judge.id}",
                attributes={
                    "run_id": self.run_id,
                    "trace_id": trace.id,
                    "judge_id": judge.id,
                    "judge_version": judge.version,
                    "determinism": judge.determinism.value,
                },
            ) as jspan:
                started = utcnow()
                try:
                    raw = await self._call_judge_with_retry(judge, item, output)
                    error: str | None = None
                except Exception as exc:  # noqa: BLE001
                    raw = None
                    error = str(exc)
                finished = utcnow()
                duration_ms = (finished - started).total_seconds() * 1000
                inst.judges_duration.record(
                    duration_ms,
                    attributes={
                        "judge_id": judge.id,
                        "determinism": judge.determinism.value,
                    },
                )

            judgment = self._finalize_judgment(
                raw=raw,
                judge=judge,
                trace=trace,
                started=started,
                finished=finished,
                error=error,
            )
            if judgment.cost_usd is not None:
                inst.judges_cost.add(
                    judgment.cost_usd,
                    attributes={"judge_id": judge.id},
                )
                jspan.set_attribute("cost_usd", judgment.cost_usd)
            judgments.append(judgment)
        return judgments

    async def _call_judge_with_retry(
        self,
        judge: Judge,
        item: EvalItem,
        output: EvaluatorOutput,
    ) -> Judgment:
        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self.spec.runtime.max_retries:
            attempt += 1
            try:
                with anyio.move_on_after(
                    self.spec.runtime.task_timeout_seconds
                ) as scope:
                    res = await judge.judge(item, output)
                if scope.cancel_called:
                    raise TransientError(
                        f"judge {judge.id} timed out after "
                        f"{self.spec.runtime.task_timeout_seconds}s"
                    )
                return res
            except TransientError as exc:
                last_exc = exc
                continue
            except Exception:  # noqa: BLE001 — non-retryable
                raise
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("unreachable")

    def _finalize_judgment(
        self,
        *,
        raw: Judgment | None,
        judge: Judge,
        trace: Trace,
        started: datetime,
        finished: datetime,
        error: str | None,
    ) -> Judgment:
        if raw is None:
            return Judgment(
                id=new_id("jdg"),
                run_id=self.run_id,
                trace_id=trace.id,
                judge_id=judge.id,
                judge_version=judge.version,
                score={"error": error or "judge failed"},
                rationale=error,
                determinism=judge.determinism,
                started_at=started,
                finished_at=finished,
                error=error,
            )
        score: float | bool | str | dict[str, Any] = raw.score
        rationale = raw.rationale
        if raw.error:
            score = {"error": raw.error}
            rationale = rationale or raw.error

        # Re-stamp run_id and trace_id; leave successful score/cost intact.
        return raw.model_copy(
            update={
                "run_id": self.run_id,
                "trace_id": trace.id,
                "score": score,
                "rationale": rationale,
                "cache_key": _cache_key(judge, trace, raw, item_hash=trace.input.content_hash()),
            }
        )

    # -- Persistence --------------------------------------------------

    async def _persist_trace(self, trace: Trace) -> None:
        try:
            await self.trace_store.put_trace(trace)
        except Exception as exc:  # noqa: BLE001
            instruments().tracestore_errors.add(
                1, attributes={"backend": type(self.trace_store).__name__, "op": "put_trace"}
            )
            raise exc

    async def _persist_judgment(self, judgment: Judgment) -> None:
        try:
            await self.trace_store.put_judgment(judgment)
        except Exception as exc:  # noqa: BLE001
            instruments().tracestore_errors.add(
                1,
                attributes={
                    "backend": type(self.trace_store).__name__,
                    "op": "put_judgment",
                },
            )
            raise exc


def _cache_key(judge: Judge, trace: Trace, judgment: Judgment, *, item_hash: str) -> str | None:
    """Build a cache key used by replay tooling.

    Stochastic judges are not cached; we still record the key so the trace
    store keeps schema-uniform rows.
    """

    if judge.determinism == Determinism.STOCHASTIC:
        return None
    output_hash = trace.output.content_hash() if trace.output is not None else "no-output"
    return f"{judge.id}@{judge.version}|item={item_hash}|out={output_hash}"


def _record_task_completed(inst: Any, trace: Trace) -> None:
    inst.tasks_completed.add(
        1,
        attributes={
            "status": trace.status,
            "evaluator_id": trace.evaluator_id,
        },
    )
