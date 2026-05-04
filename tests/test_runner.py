"""Runner integration tests.

These exercise the runner end-to-end with the in-memory trace store. The
runner is the densest module in the codebase; we over-invest in tests here
relative to other modules (per ``docs/testing.md``).
"""

from __future__ import annotations

import anyio
import pytest

from eval_fabric.errors import RunAborted, TransientError
from eval_fabric.evaluators import evaluator
from eval_fabric.judges import judge
from eval_fabric.models import Determinism, EvalItem, EvaluatorOutput
from eval_fabric.registry import register_evaluator, register_judge
from eval_fabric.runner import Runner
from eval_fabric.spec.models import (
    EvalSpec,
    EvaluatorRef,
    JudgeRef,
    MetricSpec,
    RuntimeConfig,
    ScoringConfig,
)
from eval_fabric.testing.fakes import InMemoryTraceStore


pytestmark = pytest.mark.anyio


def _build_spec(
    *,
    on_failure: str = "skip",
    max_retries: int = 0,
    timeout: float = 5.0,
    max_concurrent: int = 4,
) -> EvalSpec:
    return EvalSpec(
        id="test/integration",
        version="1.0.0",
        evaluator=EvaluatorRef(id="test.evaluator"),
        judges=[JudgeRef(id="test.judge")],
        scoring=ScoringConfig(metrics=[MetricSpec(name="acc", aggregator="mean")]),
        runtime=RuntimeConfig(
            max_concurrent=max_concurrent,
            task_timeout_seconds=timeout,
            max_retries=max_retries,
            on_failure=on_failure,  # type: ignore[arg-type]
        ),
    )


def _items(n: int) -> list[EvalItem]:
    return [
        EvalItem(item_id=f"item-{i}", input=i, reference_output=i)
        for i in range(n)
    ]


async def test_happy_path_runs_to_completion() -> None:
    @evaluator(id="test.evaluator", version="1.0.0")
    async def passthrough(item: EvalItem) -> EvaluatorOutput:
        return EvaluatorOutput(output=item.input)

    @judge(id="test.judge", version="1.0.0", determinism=Determinism.DETERMINISTIC)
    async def equal(item: EvalItem, output: EvaluatorOutput):
        return float(output.output == item.reference_output)

    store = InMemoryTraceStore()
    spec = _build_spec()
    runner = Runner(spec=spec, dataset=_items(5), trace_store=store)
    result = await runner.run_async()
    assert result.status == "completed"
    assert result.dataset_size == 5
    assert result.counts["ok"] == 5
    assert result.metrics[0].value == pytest.approx(1.0)


async def test_bounded_concurrency() -> None:
    in_flight = 0
    peak = 0

    @evaluator(id="test.evaluator", version="1.0.0")
    async def slow(item: EvalItem) -> EvaluatorOutput:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await anyio.sleep(0.01)
        in_flight -= 1
        return EvaluatorOutput(output=item.input)

    @judge(id="test.judge", version="1.0.0", determinism=Determinism.DETERMINISTIC)
    async def true_judge(item: EvalItem, output: EvaluatorOutput):
        return True

    store = InMemoryTraceStore()
    spec = _build_spec(max_concurrent=3)
    runner = Runner(spec=spec, dataset=_items(20), trace_store=store)
    await runner.run_async()
    assert peak <= 3, f"expected peak ≤ 3, observed {peak}"


async def test_retry_on_transient_error() -> None:
    attempts = {"count": 0}

    @evaluator(id="test.evaluator", version="1.0.0")
    async def flaky(item: EvalItem) -> EvaluatorOutput:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TransientError("simulated flake")
        return EvaluatorOutput(output=item.input)

    @judge(id="test.judge", version="1.0.0", determinism=Determinism.DETERMINISTIC)
    async def truthy(item, output):
        return True

    store = InMemoryTraceStore()
    spec = _build_spec(max_retries=3)
    runner = Runner(spec=spec, dataset=_items(1), trace_store=store)
    result = await runner.run_async()
    assert result.counts["ok"] == 1
    assert attempts["count"] == 3


async def test_non_retryable_error_marks_trace_error() -> None:
    @evaluator(id="test.evaluator", version="1.0.0")
    async def broken(item: EvalItem) -> EvaluatorOutput:
        raise RuntimeError("nope")

    @judge(id="test.judge", version="1.0.0", determinism=Determinism.DETERMINISTIC)
    async def truthy(item, output):
        return True

    store = InMemoryTraceStore()
    spec = _build_spec()
    runner = Runner(spec=spec, dataset=_items(2), trace_store=store)
    result = await runner.run_async()
    assert result.counts["error"] == 2
    assert result.counts["ok"] == 0
    assert result.status == "completed"  # on_failure="skip"


async def test_on_failure_abort_raises() -> None:
    @evaluator(id="test.evaluator", version="1.0.0")
    async def broken(item: EvalItem) -> EvaluatorOutput:
        raise RuntimeError("bad")

    @judge(id="test.judge", version="1.0.0", determinism=Determinism.DETERMINISTIC)
    async def truthy(item, output):
        return True

    store = InMemoryTraceStore()
    spec = _build_spec(on_failure="abort")
    runner = Runner(spec=spec, dataset=_items(2), trace_store=store)
    with pytest.raises(RunAborted):
        await runner.run_async()


async def test_persist_before_complete() -> None:
    """Once a task counts as ok, its trace and judgments are durable.

    Stronger statements live in the property tests; this is the smoke check.
    """

    @evaluator(id="test.evaluator", version="1.0.0")
    async def echo(item: EvalItem) -> EvaluatorOutput:
        return EvaluatorOutput(output=item.input)

    @judge(id="test.judge", version="1.0.0", determinism=Determinism.DETERMINISTIC)
    async def truthy(item, output):
        return True

    store = InMemoryTraceStore()
    spec = _build_spec()
    runner = Runner(spec=spec, dataset=_items(3), trace_store=store)
    result = await runner.run_async()
    assert len(store.traces) == 3
    assert len(store.judgments) == 3
    assert all(j.run_id == result.id for j in store.judgments.values())
