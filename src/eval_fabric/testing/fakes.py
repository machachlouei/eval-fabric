"""In-memory test doubles.

The fake trace store is used by both framework-internal tests and downstream
plugin authors to verify their plugin works against the runner. It does not
persist anything; clearing the instance resets state.
"""

from __future__ import annotations

from typing import AsyncIterator

from eval_fabric.errors import TraceStoreError
from eval_fabric.models import Judgment, JudgmentId, RunId, RunResult, Trace, TraceId


class InMemoryTraceStore:
    """Minimal :class:`TraceStore` implementation that lives in process memory.

    Implements the full protocol surface; the durability and migration
    concerns the SQLite store handles do not apply here.
    """

    schema_version = 1

    def __init__(self) -> None:
        self.runs: dict[str, RunResult] = {}
        self.traces: dict[str, Trace] = {}
        self.judgments: dict[str, Judgment] = {}
        self._opened = False

    async def open(self) -> None:
        self._opened = True

    async def close(self) -> None:
        self._opened = False

    async def put_run(self, run: RunResult) -> RunId:
        self._require_open()
        self.runs[run.id] = run
        return run.id

    async def put_trace(self, trace: Trace) -> TraceId:
        self._require_open()
        self.traces[trace.id] = trace
        return trace.id

    async def put_judgment(self, judgment: Judgment) -> JudgmentId:
        self._require_open()
        self.judgments[judgment.id] = judgment
        return judgment.id

    async def get_run(self, run_id: RunId) -> RunResult:
        self._require_open()
        run = self.runs.get(run_id)
        if run is None:
            raise TraceStoreError(f"no such run: {run_id}")
        return run

    async def get_trace(self, trace_id: TraceId) -> Trace:
        self._require_open()
        tr = self.traces.get(trace_id)
        if tr is None:
            raise TraceStoreError(f"no such trace: {trace_id}")
        return tr

    async def query_judgments(self, run_id: RunId) -> AsyncIterator[Judgment]:
        self._require_open()
        for j in self.judgments.values():
            if j.run_id == run_id:
                yield j

    async def query_traces(self, run_id: RunId) -> AsyncIterator[Trace]:
        self._require_open()
        for tr in self.traces.values():
            if tr.run_id == run_id:
                yield tr

    def _require_open(self) -> None:
        if not self._opened:
            raise TraceStoreError("InMemoryTraceStore is not open")
