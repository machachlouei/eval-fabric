"""Aggregator math: determinism, edge cases, weighted means."""

from __future__ import annotations

import pytest

from eval_fabric.aggregator import aggregate
from eval_fabric.models import Determinism, Judgment, utcnow
from eval_fabric.spec.models import MetricSpec, ScoringConfig


def _judgment(score: float | bool, judge_id: str = "j") -> Judgment:
    now = utcnow()
    return Judgment(
        id=f"jdg_{score}_{judge_id}",
        run_id="run_test",
        trace_id="trc_test",
        judge_id=judge_id,
        judge_version="1.0.0",
        score=score,
        determinism=Determinism.DETERMINISTIC,
        started_at=now,
        finished_at=now,
    )


def test_mean_of_empty_is_zero() -> None:
    cfg = ScoringConfig(metrics=[MetricSpec(name="x", aggregator="mean")])
    out = aggregate([], cfg)
    assert out[0].value == 0.0
    assert out[0].n == 0


def test_mean_with_booleans() -> None:
    cfg = ScoringConfig(metrics=[MetricSpec(name="acc", aggregator="mean")])
    js = [_judgment(True), _judgment(True), _judgment(False), _judgment(True)]
    out = aggregate(js, cfg)
    assert out[0].value == pytest.approx(0.75)
    assert out[0].n == 4


def test_rate_above_threshold() -> None:
    cfg = ScoringConfig(
        metrics=[MetricSpec(name="passing", aggregator="rate_above", threshold=0.5)]
    )
    js = [_judgment(0.4), _judgment(0.6), _judgment(0.9)]
    out = aggregate(js, cfg)
    assert out[0].value == pytest.approx(2 / 3)


def test_aggregator_is_deterministic() -> None:
    cfg = ScoringConfig(
        metrics=[MetricSpec(name="acc", aggregator="mean", bootstrap=True)]
    )
    js = [_judgment(v) for v in [0.1, 0.5, 0.9, 0.7, 0.3]]
    a = aggregate(js, cfg)
    b = aggregate(js, cfg)
    assert a[0].value == b[0].value
    assert a[0].ci_low == b[0].ci_low
    assert a[0].ci_high == b[0].ci_high


def test_filter_by_judge_id() -> None:
    cfg = ScoringConfig(
        metrics=[MetricSpec(name="style", aggregator="mean", **{"from": "j2"})]
    )
    js = [
        _judgment(1.0, judge_id="j1"),
        _judgment(0.0, judge_id="j2"),
        _judgment(1.0, judge_id="j2"),
    ]
    out = aggregate(js, cfg)
    assert out[0].n == 2
    assert out[0].value == pytest.approx(0.5)


def test_count_includes_non_numeric_judgments() -> None:
    cfg = ScoringConfig(metrics=[MetricSpec(name="n", aggregator="count")])
    js = [_judgment(True), _judgment(False)]
    out = aggregate(js, cfg)
    assert out[0].value == 2
