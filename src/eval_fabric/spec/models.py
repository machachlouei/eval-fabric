"""EvalSpec and its sub-models.

`EvalSpec` is frozen and rejects unknown fields. Every field has a defaulted
counterpart documented in `docs/design.md`. Behaviour-affecting changes here
must update the migration chain — see ADR-0004.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from eval_fabric.errors import SpecValidationError

# The current EvalSpec major version. Bump this when adding a new migration.
CURRENT_SCHEMA_VERSION: Literal["1"] = "1"

_SEMVER_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
_ID_RE = re.compile(r"^[a-zA-Z0-9_]+(?:[./-][a-zA-Z0-9_]+)*$")


SpecId = Annotated[str, StringConstraints(min_length=1, max_length=200)]
SemVer = Annotated[str, StringConstraints(min_length=5, max_length=64)]


class RuntimeConfig(BaseModel):
    """Operational knobs for the runner.

    Defaults are the numbers `architecture.md` documents. Plugin authors do
    not see this directly; the runner consumes it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_concurrent: int = Field(default=64, gt=0, le=4096)
    task_timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=20)
    on_failure: Literal["skip", "abort"] = "skip"
    trace_store: str = "sqlite:///./runs/runs.db"


class EvaluatorRef(BaseModel):
    """A pointer from a spec to a registered evaluator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(
                f"evaluator id={v!r} is not a valid identifier "
                "(allowed: alphanumerics, underscores, '.', '/', '-')"
            )
        return v


class JudgeRef(BaseModel):
    """A pointer from a spec to a registered judge.

    `weight` is consumed by aggregators that compute weighted means; judges
    that aren't aggregated by weight ignore it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    config: dict[str, Any] = Field(default_factory=dict)
    weight: float = Field(default=1.0, ge=0.0)

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(
                f"judge id={v!r} is not a valid identifier "
                "(allowed: alphanumerics, underscores, '.', '/', '-')"
            )
        return v


class MetricSpec(BaseModel):
    """A single metric the aggregator should compute.

    `from` selects the source ('judges' or a judge id). `aggregator` selects
    the function: mean, median, count, rate_above, weighted_mean, ks_test.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    name: str
    aggregator: Literal[
        "mean",
        "median",
        "count",
        "rate_above",
        "weighted_mean",
        "ks_test",
    ] = "mean"
    source: str = Field(default="judges", alias="from")
    threshold: float | None = None
    bootstrap: bool = False
    bootstrap_samples: int = Field(default=1000, ge=10, le=100_000)
    seed: int = 42


class ScoringConfig(BaseModel):
    """Scoring configuration: which metrics to compute and what to compare to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metrics: list[MetricSpec]
    baseline_run_id: str | None = None


class EvalSpec(BaseModel):
    """The declarative recipe for an evaluation. See `docs/concepts.md`.

    A `EvalSpec` is immutable after construction. Mutations produce a new
    instance via `model_copy(update=...)`. The framework rejects any spec whose
    `schema_version` is not the current major.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    id: SpecId
    version: SemVer
    description: str = ""
    evaluator: EvaluatorRef
    judges: list[JudgeRef] = Field(min_length=1)
    scoring: ScoringConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def _check_semver(cls, v: str) -> str:
        if not _SEMVER_RE.match(v):
            raise ValueError(f"version={v!r} is not a valid semver MAJOR.MINOR.PATCH")
        return v

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(
                f"spec id={v!r} is not a valid identifier (use 'team/name' or 'team.name' form)"
            )
        return v


def validate_spec(data: dict[str, Any]) -> EvalSpec:
    """Validate a dict against EvalSpec, raising :class:`SpecValidationError`.

    This is the boundary called by the loader and by anyone constructing a
    spec from in-memory data. Pydantic's own ValidationError is wrapped so
    callers have one type to catch.
    """

    try:
        return EvalSpec.model_validate(data)
    except Exception as exc:  # ValidationError or pydantic-internal subclass
        raise SpecValidationError(f"EvalSpec is invalid: {exc}") from exc
