"""Metric aggregation.

The aggregator is intentionally dumb: it reads judgments and computes the
metrics declared in the spec. There is no metrics DSL, no plugin point. If
you need more, write a function and call it after the run completes.

Determinism: same inputs, same outputs, byte-identical. Bootstrap CIs use a
seeded RNG so replay is byte-stable.
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Iterable, Sequence

from eval_fabric.models import Judgment, RunMetric
from eval_fabric.spec.models import MetricSpec, ScoringConfig


def aggregate(
    judgments: Iterable[Judgment],
    scoring: ScoringConfig,
) -> list[RunMetric]:
    """Compute every metric declared in `scoring` against `judgments`.

    Judgments whose score is not numeric are filtered out for numeric
    aggregators; counting aggregators ignore the filter.
    """

    js = list(judgments)
    metrics: list[RunMetric] = []
    for metric in scoring.metrics:
        metrics.append(_compute(metric, js))
    return metrics


def _compute(metric: MetricSpec, judgments: list[Judgment]) -> RunMetric:
    relevant = _filter_judgments(judgments, metric.source)
    numeric = [_to_float(j.score) for j in relevant if _to_float(j.score) is not None]
    weights = [_judge_weight(j) for j in relevant if _to_float(j.score) is not None]

    match metric.aggregator:
        case "count":
            return RunMetric(name=metric.name, value=len(relevant), n=len(relevant))
        case "mean":
            value = statistics.fmean(numeric) if numeric else 0.0
            ci_low, ci_high = _bootstrap_ci(numeric, metric) if metric.bootstrap else (None, None)
            return RunMetric(
                name=metric.name,
                value=value,
                n=len(numeric),
                ci_low=ci_low,
                ci_high=ci_high,
            )
        case "median":
            value = statistics.median(numeric) if numeric else 0.0
            return RunMetric(name=metric.name, value=value, n=len(numeric))
        case "rate_above":
            threshold = metric.threshold if metric.threshold is not None else 0.5
            if not numeric:
                return RunMetric(name=metric.name, value=0.0, n=0)
            rate = sum(1 for v in numeric if v >= threshold) / len(numeric)
            return RunMetric(name=metric.name, value=rate, n=len(numeric))
        case "weighted_mean":
            if not numeric:
                return RunMetric(name=metric.name, value=0.0, n=0)
            total_weight = sum(weights) or 1.0
            value = sum(v * w for v, w in zip(numeric, weights)) / total_weight
            return RunMetric(name=metric.name, value=value, n=len(numeric))
        case "ks_test":
            # Single-sample KS comparing the score distribution against the
            # uniform [0, 1]. We use this as a coarse "is the distribution
            # different from uniform" check; full statistical work belongs in
            # downstream tools (ADR not in scope of this metric).
            stat = _ks_uniform(numeric)
            return RunMetric(
                name=metric.name,
                value=stat,
                n=len(numeric),
                metadata={"reference": "uniform"},
            )
        case unknown:  # pragma: no cover — Pydantic constrains this set
            raise ValueError(f"unknown aggregator: {unknown!r}")


def _filter_judgments(judgments: list[Judgment], source: str) -> list[Judgment]:
    if source == "judges":
        return judgments
    return [j for j in judgments if j.judge_id == source]


def _judge_weight(j: Judgment) -> float:
    """Best-effort weight extraction.

    The aggregator does not see :class:`JudgeRef` directly; weights live on
    spec.judges. For simplicity, weighted_mean treats every judgment as
    weight 1.0 unless the judgment carries a ``weight`` field in its score
    dict (an extension some custom judges use).
    """

    if isinstance(j.score, dict) and "weight" in j.score:
        try:
            return float(j.score["weight"])
        except (TypeError, ValueError):
            return 1.0
    return 1.0


def _to_float(score: object) -> float | None:
    if isinstance(score, bool):
        return 1.0 if score else 0.0
    if isinstance(score, (int, float)):
        return float(score)
    if isinstance(score, dict) and "value" in score:
        try:
            return float(score["value"])
        except (TypeError, ValueError):
            return None
    return None


def _bootstrap_ci(values: Sequence[float], metric: MetricSpec) -> tuple[float, float]:
    """Bootstrap a 95% CI for the mean of `values`.

    Uses a seeded ``random.Random`` so the result is reproducible. Returns
    (low, high). For empty inputs both are 0.0.
    """

    if not values:
        return 0.0, 0.0
    rng = random.Random(metric.seed)
    n = len(values)
    means: list[float] = []
    for _ in range(metric.bootstrap_samples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[min(int(0.975 * len(means)), len(means) - 1)]
    return lo, hi


def _ks_uniform(values: Sequence[float]) -> float:
    """One-sample Kolmogorov-Smirnov statistic vs. Uniform(0, 1)."""

    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    d = 0.0
    for i, v in enumerate(sorted_vals, start=1):
        d_plus = i / n - v
        d_minus = v - (i - 1) / n
        d = max(d, d_plus, d_minus)
    return d if not math.isnan(d) else 0.0
