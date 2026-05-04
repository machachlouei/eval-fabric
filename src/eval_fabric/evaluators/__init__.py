"""Evaluator protocol and helpers.

An evaluator is the system under test (or a wrapper around it). It is a
callable that takes an :class:`EvalItem` and returns an
:class:`EvaluatorOutput`. See ADR-0007 for why this is separate from `Judge`.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from eval_fabric.models import EvalItem, EvaluatorOutput
from eval_fabric.registry import register_evaluator
from eval_fabric.evaluators.retry import retry
from eval_fabric.evaluators.rate_limit import RateLimiter


@runtime_checkable
class Evaluator(Protocol):
    """Structural protocol every evaluator satisfies.

    Plugins do not need to subclass anything; supplying ``id``, ``version``,
    and an async ``__call__`` is enough.
    """

    id: str
    version: str

    async def __call__(self, item: EvalItem) -> EvaluatorOutput: ...  # pragma: no cover


def evaluator(
    *,
    id: str,
    version: str,
) -> Callable[[Callable[[EvalItem], Awaitable[Any]]], Evaluator]:
    """Decorator: turn an async function into a registered evaluator.

    The decorated function must be async and accept a single :class:`EvalItem`.
    Its return value is normalized to :class:`EvaluatorOutput`: anything that
    isn't already one is wrapped as ``EvaluatorOutput(output=value)``.
    """

    def decorator(fn: Callable[[EvalItem], Awaitable[Any]]) -> Evaluator:
        wrapped = _FunctionEvaluator(id=id, version=version, fn=fn)
        register_evaluator(id, lambda **_: wrapped)
        return wrapped

    return decorator


class _FunctionEvaluator:
    """Adapter wrapping a plain async function as an Evaluator."""

    def __init__(
        self,
        *,
        id: str,
        version: str,
        fn: Callable[[EvalItem], Awaitable[Any]],
    ) -> None:
        self.id = id
        self.version = version
        self._fn = fn

    async def __call__(self, item: EvalItem) -> EvaluatorOutput:
        result = await self._fn(item)
        if isinstance(result, EvaluatorOutput):
            return result
        return EvaluatorOutput(output=result)


__all__ = [
    "Evaluator",
    "EvaluatorOutput",
    "evaluator",
    "retry",
    "RateLimiter",
]
