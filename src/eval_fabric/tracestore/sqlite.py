"""SQLite trace store.

The default in-tree backend. A single file holds three tables — runs, traces,
judgments — and the schema version is checked on every ``open()``. Writes use
a thread executor because SQLite's bindings are blocking; the surface stays
async-compatible without making us juggle a thread-pool everywhere.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, AsyncIterator

import anyio

from eval_fabric.errors import TraceStoreError, TraceStoreSchemaMismatch
from eval_fabric.models import (
    Judgment,
    JudgmentId,
    RunId,
    RunResult,
    Trace,
    TraceId,
)

_SCHEMA_VERSION = 1


class SQLiteTraceStore:
    """SQLite-backed implementation of the TraceStore protocol.

    The store is intentionally not thread-safe across processes — SQLite has
    one writer at a time. For multi-runner deployments, use the Postgres
    contrib backend.
    """

    schema_version = _SCHEMA_VERSION

    def __init__(self, path: str | Path) -> None:
        # An empty path means the canonical default location.
        self._path = str(path) if str(path) else "./runs/runs.db"
        self._conn: sqlite3.Connection | None = None

    # -- Lifecycle ----------------------------------------------------

    async def open(self) -> None:
        """Open (or create) the underlying file and verify the schema."""

        await anyio.to_thread.run_sync(self._open_sync)

    def _open_sync(self) -> None:
        if self._conn is not None:
            return
        path = Path(self._path)
        if path.parent and str(path.parent) not in ("", "."):
            path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema(conn)
        self._conn = conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta ("
            "  schema_version INTEGER NOT NULL"
            ")"
        )
        row = conn.execute("SELECT schema_version FROM schema_meta").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_meta (schema_version) VALUES (?)",
                (_SCHEMA_VERSION,),
            )
        elif int(row["schema_version"]) != _SCHEMA_VERSION:
            raise TraceStoreSchemaMismatch(
                f"schema mismatch (store={row['schema_version']}, framework={_SCHEMA_VERSION}); "
                f"run `ef tracestore migrate sqlite://{self._path} --to {_SCHEMA_VERSION}`"
            )

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                spec_id TEXT NOT NULL,
                spec_version TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS traces (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                evaluator_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_traces_run ON traces(run_id);
            CREATE TABLE IF NOT EXISTS judgments (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                judge_id TEXT NOT NULL,
                determinism TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_judgments_run ON judgments(run_id);
            CREATE INDEX IF NOT EXISTS idx_judgments_trace ON judgments(trace_id);
            """
        )

    async def close(self) -> None:
        if self._conn is None:
            return
        conn = self._conn
        self._conn = None
        await anyio.to_thread.run_sync(conn.close)

    # -- Writes -------------------------------------------------------

    async def put_run(self, run: RunResult) -> RunId:
        await anyio.to_thread.run_sync(self._put_run_sync, run)
        return run.id

    def _put_run_sync(self, run: RunResult) -> None:
        conn = self._require_conn()
        conn.execute(
            "INSERT OR REPLACE INTO runs "
            "(id, spec_id, spec_version, status, started_at, finished_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run.id,
                run.spec_id,
                run.spec_version,
                run.status,
                run.started_at.isoformat(),
                run.finished_at.isoformat() if run.finished_at else None,
                run.model_dump_json(),
            ),
        )

    async def put_trace(self, trace: Trace) -> TraceId:
        await anyio.to_thread.run_sync(self._put_trace_sync, trace)
        return trace.id

    def _put_trace_sync(self, trace: Trace) -> None:
        conn = self._require_conn()
        conn.execute(
            "INSERT OR REPLACE INTO traces "
            "(id, run_id, item_id, evaluator_id, status, started_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                trace.id,
                trace.run_id,
                trace.item_id,
                trace.evaluator_id,
                trace.status,
                trace.started_at.isoformat(),
                trace.model_dump_json(),
            ),
        )

    async def put_judgment(self, judgment: Judgment) -> JudgmentId:
        await anyio.to_thread.run_sync(self._put_judgment_sync, judgment)
        return judgment.id

    def _put_judgment_sync(self, j: Judgment) -> None:
        conn = self._require_conn()
        conn.execute(
            "INSERT OR REPLACE INTO judgments "
            "(id, run_id, trace_id, judge_id, determinism, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                j.id,
                j.run_id,
                j.trace_id,
                j.judge_id,
                j.determinism.value,
                j.model_dump_json(),
            ),
        )

    # -- Reads --------------------------------------------------------

    async def get_run(self, run_id: RunId) -> RunResult:
        row = await anyio.to_thread.run_sync(self._fetch_one, "runs", run_id)
        if row is None:
            raise TraceStoreError(f"no such run: {run_id}")
        return RunResult.model_validate_json(row["payload"])

    async def get_trace(self, trace_id: TraceId) -> Trace:
        row = await anyio.to_thread.run_sync(self._fetch_one, "traces", trace_id)
        if row is None:
            raise TraceStoreError(f"no such trace: {trace_id}")
        return Trace.model_validate_json(row["payload"])

    def _fetch_one(self, table: str, id_value: str) -> Any:
        conn = self._require_conn()
        return conn.execute(
            f"SELECT payload FROM {table} WHERE id = ?",
            (id_value,),
        ).fetchone()

    async def query_judgments(self, run_id: RunId) -> AsyncIterator[Judgment]:
        rows = await anyio.to_thread.run_sync(self._fetch_judgments, run_id)
        for payload in rows:
            yield Judgment.model_validate_json(payload)

    def _fetch_judgments(self, run_id: RunId) -> list[str]:
        conn = self._require_conn()
        cur = conn.execute(
            "SELECT payload FROM judgments WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
        return [row["payload"] for row in cur.fetchall()]

    async def query_traces(self, run_id: RunId) -> AsyncIterator[Trace]:
        rows = await anyio.to_thread.run_sync(self._fetch_traces, run_id)
        for payload in rows:
            yield Trace.model_validate_json(payload)

    def _fetch_traces(self, run_id: RunId) -> list[str]:
        conn = self._require_conn()
        cur = conn.execute(
            "SELECT payload FROM traces WHERE run_id = ? ORDER BY started_at",
            (run_id,),
        )
        return [row["payload"] for row in cur.fetchall()]

    # -- Internal -----------------------------------------------------

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise TraceStoreError("trace store is not open; call await store.open() first")
        return self._conn
