"""Public ``load_run`` helper used by the SDK quickstart in README.md.

The "give me a run from disk" path needs to handle two shapes:

- A path to a trace store URI (e.g. ``sqlite:///./runs/runs.db``). In this
  case we resolve a run by id (last segment of the path) and stream it.
- A path to a run-specific directory (legacy / contrib backends export this
  shape). In this case we read ``result.json`` and bring its judgments lazily.

This is a small convenience wrapper; the SDK contract is documented in
``docs/concepts.md``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio

from eval_fabric.aggregator import aggregate
from eval_fabric.errors import EvalFabricError
from eval_fabric.models import Judgment, RunResult
from eval_fabric.spec import EvalSpec, validate_spec
from eval_fabric.spec.models import MetricSpec, ScoringConfig
from eval_fabric.tracestore import open_trace_store


class LoadedRun:
    """Lazily-materialized view of a stored run.

    The aggregate view (``run.metrics``) is held on the embedded
    :class:`RunResult`. Streamed access to per-trace and per-judgment records
    goes through the trace store.
    """

    def __init__(
        self,
        *,
        run: RunResult,
        eval_spec: EvalSpec,
        judgments: list[Judgment],
    ) -> None:
        self.run = run
        self.eval_spec = eval_spec
        self.judgments = judgments

    @property
    def metrics(self) -> "_MetricsView":
        return _MetricsView(self.run, self.eval_spec, self.judgments)


class _MetricsView:
    """Convenience view exposing ``aggregate(metric_name)`` ergonomics."""

    def __init__(
        self,
        run: RunResult,
        spec: EvalSpec,
        judgments: list[Judgment],
    ) -> None:
        self._run = run
        self._spec = spec
        self._judgments = judgments

    def aggregate(self, metric_name: str) -> str:
        """Recompute one metric and format it as a short string.

        Matches the README quickstart: ``run.metrics.aggregate("accuracy")``.
        """

        for metric in self._run.metrics:
            if metric.name == metric_name:
                return _format_metric(metric)
        # Spec did not record this metric. Recompute it ad-hoc with sensible
        # defaults so the SDK is forgiving.
        spec_metric = MetricSpec(name=metric_name, aggregator="mean")
        result = aggregate(
            self._judgments, ScoringConfig(metrics=[spec_metric])
        )[0]
        return _format_metric(result)


def _format_metric(metric: Any) -> str:
    if metric.ci_low is not None and metric.ci_high is not None and metric.n is not None:
        delta = (metric.ci_high - metric.ci_low) / 2 if metric.ci_high > metric.ci_low else 0.0
        return f"{metric.value:.3f} ± {delta:.3f} (n={metric.n})"
    if metric.n is not None:
        return f"{metric.value} (n={metric.n})"
    return f"{metric.value}"


def load_run(source: str | Path) -> LoadedRun:
    """Load a stored run.

    `source` is either a trace-store URI plus run id (e.g.
    ``sqlite:///./runs/runs.db#run_abc12345``) or a path to a directory
    containing a ``result.json`` file.
    """

    if isinstance(source, str) and "://" in source:
        return anyio.run(_load_from_uri, source)
    return _load_from_path(Path(source))


def _load_from_path(path: Path) -> LoadedRun:
    if path.is_dir():
        result_path = path / "result.json"
    else:
        result_path = path
    if not result_path.exists():
        raise EvalFabricError(f"no run found at {path}")
    data = json.loads(result_path.read_text(encoding="utf-8"))
    run = RunResult.model_validate(data["run"]) if "run" in data else RunResult.model_validate(data)
    spec = validate_spec(run.spec)
    judgments = [Judgment.model_validate(j) for j in data.get("judgments", [])]
    return LoadedRun(run=run, eval_spec=spec, judgments=judgments)


async def _load_from_uri(source: str) -> LoadedRun:
    if "#" not in source:
        raise EvalFabricError(
            "trace-store URI must include a fragment naming the run "
            "(e.g. sqlite:///./runs/runs.db#run_abc12345)"
        )
    uri, run_id = source.rsplit("#", 1)
    store = open_trace_store(uri)
    await store.open()
    try:
        run = await store.get_run(run_id)
        spec = validate_spec(run.spec)
        judgments: list[Judgment] = []
        async for j in store.query_judgments(run_id):
            judgments.append(j)
        return LoadedRun(run=run, eval_spec=spec, judgments=judgments)
    finally:
        await store.close()
