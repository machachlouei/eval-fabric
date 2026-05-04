"""SQLite trace store: schema check, persist + read, durability across opens."""

from __future__ import annotations

from pathlib import Path

import anyio
import pytest

from eval_fabric.errors import TraceStoreError
from eval_fabric.models import (
    Determinism,
    EvalItem,
    EvaluatorOutput,
    Judgment,
    RunResult,
    Trace,
    new_id,
    utcnow,
)
from eval_fabric.tracestore.sqlite import SQLiteTraceStore


pytestmark = pytest.mark.anyio


def _trace(run_id: str, item_id: str = "item-1") -> Trace:
    now = utcnow()
    return Trace(
        id=new_id("trc"),
        run_id=run_id,
        item_id=item_id,
        evaluator_id="team.alpha",
        evaluator_version="1.0.0",
        input=EvalItem(item_id=item_id, input="hello"),
        output=EvaluatorOutput(output="hello"),
        status="ok",
        started_at=now,
        finished_at=now,
    )


def _judgment(run_id: str, trace_id: str) -> Judgment:
    now = utcnow()
    return Judgment(
        id=new_id("jdg"),
        run_id=run_id,
        trace_id=trace_id,
        judge_id="eval_fabric.exact_match",
        judge_version="1.0.0",
        score=True,
        determinism=Determinism.DETERMINISTIC,
        started_at=now,
        finished_at=now,
    )


def _run(run_id: str) -> RunResult:
    return RunResult(
        id=run_id,
        spec_id="team/qa-bot",
        spec_version="1.0.0",
        spec={"id": "team/qa-bot", "version": "1.0.0"},
        started_at=utcnow(),
        status="completed",
    )


async def test_persist_and_query(tmp_path: Path) -> None:
    store = SQLiteTraceStore(tmp_path / "store.db")
    await store.open()
    run = _run("run_a")
    await store.put_run(run)
    trace = _trace("run_a")
    await store.put_trace(trace)
    await store.put_judgment(_judgment("run_a", trace.id))

    fetched_run = await store.get_run("run_a")
    assert fetched_run.id == "run_a"

    fetched_trace = await store.get_trace(trace.id)
    assert fetched_trace.input.input == "hello"

    judgments: list[Judgment] = []
    async for j in store.query_judgments("run_a"):
        judgments.append(j)
    assert len(judgments) == 1
    assert judgments[0].judge_id == "eval_fabric.exact_match"
    await store.close()


async def test_durability_across_opens(tmp_path: Path) -> None:
    store = SQLiteTraceStore(tmp_path / "persist.db")
    await store.open()
    await store.put_run(_run("run_b"))
    await store.close()

    store2 = SQLiteTraceStore(tmp_path / "persist.db")
    await store2.open()
    fetched = await store2.get_run("run_b")
    assert fetched.id == "run_b"
    await store2.close()


async def test_concurrent_writes_are_serialized(tmp_path: Path) -> None:
    store = SQLiteTraceStore(tmp_path / "concurrent.db")
    await store.open()
    await store.put_run(_run("run_concurrent"))

    async def write_item(i: int) -> None:
        trace = _trace("run_concurrent", item_id=f"item-{i}")
        await store.put_trace(trace)
        await store.put_judgment(_judgment("run_concurrent", trace.id))

    async with anyio.create_task_group() as tg:
        for i in range(50):
            tg.start_soon(write_item, i)

    traces: list[Trace] = []
    async for trace in store.query_traces("run_concurrent"):
        traces.append(trace)

    judgments: list[Judgment] = []
    async for judgment in store.query_judgments("run_concurrent"):
        judgments.append(judgment)

    assert len(traces) == 50
    assert len(judgments) == 50
    await store.close()


async def test_get_unknown_raises(tmp_path: Path) -> None:
    store = SQLiteTraceStore(tmp_path / "x.db")
    await store.open()
    with pytest.raises(TraceStoreError):
        await store.get_run("does-not-exist")
    await store.close()
