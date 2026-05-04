"""Judge protocol and decorator.

A judge scores an :class:`EvaluatorOutput` against an :class:`EvalItem` and
returns a :class:`Judgment`. Each judge declares its
:class:`~eval_fabric.models.Determinism`. See ADR-0007 and ADR-0008.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from eval_fabric.models import (
    Determinism,
    EvalItem,
    EvaluatorOutput,
    Judgment,
    JudgmentId,
    RunId,
    TraceId,
    new_id,
    utcnow,
)
from eval_fabric.registry import register_judge


@runtime_checkable
class Judge(Protocol):
    """Structural protocol every judge satisfies."""

    id: str
    version: str
    determinism: Determinism

    async def judge(
        self, item: EvalItem, output: EvaluatorOutput
    ) -> Judgment: ...  # pragma: no cover


def judge(
    *,
    id: str,
    version: str,
    determinism: Determinism = Determinism.DETERMINISTIC,
) -> Callable[[Callable[[EvalItem, EvaluatorOutput], Awaitable[Any]]], Judge]:
    """Decorator: turn an async function into a registered judge.

    The function may return a fully-formed :class:`Judgment`, or any of:

    - a number / bool / string  (becomes ``Judgment.score``);
    - a tuple ``(score, rationale)``;
    - a dict containing ``score`` (and optionally ``rationale``, ``cost_usd``).

    The decorator fills in identifiers and timestamps so plugin code can stay
    short.
    """

    def decorator(
        fn: Callable[[EvalItem, EvaluatorOutput], Awaitable[Any]],
    ) -> Judge:
        wrapped = _FunctionJudge(
            id=id,
            version=version,
            determinism=determinism,
            fn=fn,
        )
        register_judge(id, lambda **_: wrapped)
        return wrapped

    return decorator


class _FunctionJudge:
    """Adapter wrapping a plain async function as a Judge."""

    def __init__(
        self,
        *,
        id: str,
        version: str,
        determinism: Determinism,
        fn: Callable[[EvalItem, EvaluatorOutput], Awaitable[Any]],
    ) -> None:
        self.id = id
        self.version = version
        self.determinism = determinism
        self._fn = fn

    async def judge(self, item: EvalItem, output: EvaluatorOutput) -> Judgment:
        started = utcnow()
        raw = await self._fn(item, output)
        finished = utcnow()
        return _coerce_judgment(
            raw,
            judge_id=self.id,
            judge_version=self.version,
            determinism=self.determinism,
            started_at=started,
            finished_at=finished,
        )


def _coerce_judgment(
    raw: Any,
    *,
    judge_id: str,
    judge_version: str,
    determinism: Determinism,
    started_at: Any,
    finished_at: Any,
    run_id: RunId = "",
    trace_id: TraceId = "",
) -> Judgment:
    """Coerce a judge function's return value into a Judgment.

    The runner re-stamps `run_id` and `trace_id` after the call, so we leave
    them blank here unless the judge author supplied them explicitly.
    """

    if isinstance(raw, Judgment):
        return raw

    score: Any
    rationale: str | None = None
    cost_usd: float | None = None

    if isinstance(raw, tuple) and len(raw) == 2:
        score, rationale = raw
    elif isinstance(raw, dict) and "score" in raw:
        score = raw["score"]
        rationale = raw.get("rationale")
        cost_usd = raw.get("cost_usd")
    else:
        score = raw

    return Judgment(
        id=new_id("jdg"),
        run_id=run_id,
        trace_id=trace_id,
        judge_id=judge_id,
        judge_version=judge_version,
        score=score,
        rationale=rationale,
        determinism=determinism,
        started_at=started_at,
        finished_at=finished_at,
        cost_usd=cost_usd,
    )


__all__ = [
    "Determinism",
    "Judge",
    "Judgment",
    "JudgmentId",
    "judge",
]
