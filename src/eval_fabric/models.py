"""Typed records that flow between components.

Every public data structure that crosses a component boundary lives here.
They are Pydantic v2 models; serialization, validation, and JSON Schema come
along for free. EvalSpec lives in :mod:`eval_fabric.spec` because its lifecycle
(versioning, migrations) is meaningfully different from the rest.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# ---------------------------------------------------------------------------
# Identifier types. Aliases for readability; not validated beyond `str`.
# ---------------------------------------------------------------------------

RunId = Annotated[str, StringConstraints(min_length=1, max_length=200)]
TraceId = Annotated[str, StringConstraints(min_length=1, max_length=200)]
JudgmentId = Annotated[str, StringConstraints(min_length=1, max_length=200)]


def new_id(prefix: str) -> str:
    """Generate a fresh opaque identifier.

    Identifiers are not URL-safe by accident; they are short uuid4 strings with
    a human-readable prefix so a record's type is visible in logs.
    """

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    """Return a timezone-aware current UTC timestamp.

    All persisted timestamps are aware. We never emit naive datetimes.
    """

    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Determinism enum lives here so it can be referenced by both Judge and the
# Judgment record without an import cycle.
# ---------------------------------------------------------------------------


class Determinism(str, Enum):
    """Replay contract a judge declares.

    See ADR-0008. The framework uses this to decide what guarantees replay
    tooling enforces and whether a judgment is cacheable across runs.
    """

    DETERMINISTIC = "deterministic"
    SAMPLING_DETERMINISTIC = "sampling_deterministic"
    STOCHASTIC = "stochastic"


# ---------------------------------------------------------------------------
# Item / output records.
# ---------------------------------------------------------------------------


class EvalItem(BaseModel):
    """One row from the dataset.

    `input` is the payload handed to the evaluator. `reference_output` is the
    optional gold label visible to judges. `metadata` is opaque to the
    framework.
    """

    model_config = ConfigDict(extra="allow")

    item_id: str
    input: Any
    reference_output: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        """Stable hash of the item's identity-defining fields.

        Used to build cache keys for deterministic judges.
        """

        payload = self.model_dump_json(include={"item_id", "input", "reference_output"})
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class EvaluatorOutput(BaseModel):
    """What an evaluator produced for an item.

    `output` is the payload a judge consumes. Anything the evaluator wants to
    surface for diagnosis (model name, usage tokens, latency) goes in
    `metadata`.
    """

    model_config = ConfigDict(extra="allow")

    output: Any
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        payload = self.model_dump_json(include={"output"})
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Span/trace records. These are persisted, not OTel spans (which are exported
# to the OTel pipeline). We keep an in-band copy so a stored Trace can be
# reasoned about without round-tripping through a tracing backend.
# ---------------------------------------------------------------------------


class Span(BaseModel):
    """A captured OTel-style span recorded in the trace store.

    Persisted alongside the Trace so that "open the trace" works without an
    external tracing backend. We do not duplicate every OTel field — only what
    a human reading a stored run typically needs.
    """

    name: str
    started_at: datetime
    finished_at: datetime
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)


TraceStatus = Literal["ok", "timeout", "error", "skipped"]


class Trace(BaseModel):
    """The record of one evaluator call on one item."""

    model_config = ConfigDict(extra="forbid")

    id: TraceId
    run_id: RunId
    item_id: str
    evaluator_id: str
    evaluator_version: str
    input: EvalItem
    output: EvaluatorOutput | None
    spans: list[Span] = Field(default_factory=list)
    status: TraceStatus
    started_at: datetime
    finished_at: datetime
    attempt: int = 1
    error: str | None = None


class Judgment(BaseModel):
    """The record of one judge call on one trace."""

    model_config = ConfigDict(extra="forbid")

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
    cost_usd: float | None = None
    cache_key: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Run-level records.
# ---------------------------------------------------------------------------


RunStatus = Literal["pending", "running", "completed", "aborted", "failed"]


class RunMetric(BaseModel):
    """One aggregated metric value computed by the aggregator."""

    name: str
    value: float | int | bool | str | dict[str, Any]
    unit: str | None = None
    n: int | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunResult(BaseModel):
    """The persisted outcome of a run.

    Embeds the full EvalSpec snapshot so old runs remain interpretable even if
    the corresponding spec file in the repo has changed.
    """

    model_config = ConfigDict(extra="forbid")

    id: RunId
    spec_id: str
    spec_version: str
    spec: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus = "pending"
    dataset_size: int | None = None
    metrics: list[RunMetric] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    total_cost_usd: float = 0.0
    error: str | None = None
