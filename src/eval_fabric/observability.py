"""OpenTelemetry helpers.

We deliberately do not abstract OTel behind a custom interface (ADR-0006).
This module is a thin convenience layer that:

- exposes the framework's tracer and meter,
- declares the metric instruments documented in ``docs/observability.md``,
- gives the runner a ``record_span`` helper that produces the in-memory
  :class:`Span` objects we persist alongside traces.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from opentelemetry import metrics, trace
from opentelemetry.metrics import Counter, Histogram, Meter, UpDownCounter
from opentelemetry.trace import Tracer

_TRACER_NAME = "eval_fabric"
_METER_NAME = "eval_fabric"


def get_tracer() -> Tracer:
    return trace.get_tracer(_TRACER_NAME)


def get_meter() -> Meter:
    return metrics.get_meter(_METER_NAME)


# ---------------------------------------------------------------------------
# Instrument creation is lazy: callers call ``instruments()`` and reuse the
# returned bundle. The OTel API caches instruments, so repeated calls are
# cheap.
# ---------------------------------------------------------------------------


class _Instruments:
    """Container for the metric instruments the runner emits."""

    def __init__(self) -> None:
        meter = get_meter()
        self.tasks_completed: Counter = meter.create_counter(
            "eval_fabric.tasks.completed",
            unit="task",
            description="Number of evaluator tasks that have reached a terminal state.",
        )
        self.tasks_duration: Histogram = meter.create_histogram(
            "eval_fabric.tasks.duration",
            unit="ms",
            description="Wall-clock duration of an evaluator task, excluding judges.",
        )
        self.judges_duration: Histogram = meter.create_histogram(
            "eval_fabric.judges.duration",
            unit="ms",
            description="Wall-clock duration of a judge call.",
        )
        self.judges_cost: Counter = meter.create_counter(
            "eval_fabric.judges.cost",
            unit="USD",
            description="Reported cost in USD per judge call (when judges report cost).",
        )
        self.runner_in_flight: UpDownCounter = meter.create_up_down_counter(
            "eval_fabric.runner.in_flight",
            unit="task",
            description="Current number of tasks the runner has in flight.",
        )
        self.tracestore_errors: Counter = meter.create_counter(
            "eval_fabric.tracestore.errors",
            unit="error",
            description="Trace-store operations that failed.",
        )


_INSTRUMENTS: _Instruments | None = None


def instruments() -> _Instruments:
    """Return the metric-instrument bundle, initialising it on first call."""

    global _INSTRUMENTS
    if _INSTRUMENTS is None:
        _INSTRUMENTS = _Instruments()
    return _INSTRUMENTS


@contextmanager
def span(name: str, attributes: dict[str, object] | None = None) -> Iterator[trace.Span]:
    """Open an OTel span as a context manager.

    Wraps ``tracer.start_as_current_span``; we use a small helper to keep call
    sites short and to centralise the tracer/meter the framework uses.
    """

    tracer = get_tracer()
    with tracer.start_as_current_span(name, attributes=attributes or {}) as s:
        yield s
