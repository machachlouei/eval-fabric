"""TraceStore protocol.

A trace store is a write-mostly persistence layer optimized for reproducibility,
not a query engine. The protocol is intentionally tiny — see ADR-0005.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from eval_fabric.models import Judgment, JudgmentId, RunId, RunResult, Trace, TraceId


@runtime_checkable
class TraceStore(Protocol):
    """Persistence interface every backend implements."""

    schema_version: int

    async def open(self) -> None: ...  # pragma: no cover
    async def close(self) -> None: ...  # pragma: no cover

    async def put_run(self, run: RunResult) -> RunId: ...  # pragma: no cover
    async def put_trace(self, trace: Trace) -> TraceId: ...  # pragma: no cover
    async def put_judgment(self, judgment: Judgment) -> JudgmentId: ...  # pragma: no cover

    async def get_run(self, run_id: RunId) -> RunResult: ...  # pragma: no cover
    async def get_trace(self, trace_id: TraceId) -> Trace: ...  # pragma: no cover
    async def query_judgments(  # pragma: no cover
        self, run_id: RunId
    ) -> AsyncIterator[Judgment]: ...
    async def query_traces(  # pragma: no cover
        self, run_id: RunId
    ) -> AsyncIterator[Trace]: ...
