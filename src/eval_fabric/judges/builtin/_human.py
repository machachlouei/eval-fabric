"""Human-in-the-loop judge implementation.

Human judges are inherently stochastic. This implementation supports two modes:
interactive (via CLI prompts) and programmatic (via a provider callback).
"""

from __future__ import annotations

import sys
from typing import Any, Awaitable, Callable

import anyio
import click

from eval_fabric.judges import PENDING_RUN_ID, PENDING_TRACE_ID
from eval_fabric.models import (
    Determinism,
    EvalItem,
    EvaluatorOutput,
    Judgment,
    new_id,
    utcnow,
)

HumanResponse = dict[str, Any]  # Expected keys: score, rationale
HumanProvider = Callable[[str], Awaitable[HumanResponse]]


class HumanJudge:
    """A judge that delegates to a human.

    If no `provider` is supplied, it falls back to an interactive CLI prompt
    if stdout is a TTY. This is useful for manual spot-checking of runs.

    Note: When using interactive mode, set `runtime.max_concurrent=1` in the
    EvalSpec to avoid interleaving prompts in the terminal.
    """

    determinism = Determinism.STOCHASTIC

    def __init__(
        self,
        *,
        id: str = "eval_fabric.human",
        version: str = "1.0.0",
        instructions: str = "Rate the output from 0 to 1 based on correctness.",
        provider: HumanProvider | None = None,
    ) -> None:
        self.id = id
        self.version = version
        self.instructions = instructions
        self._provider = provider

    async def judge(self, item: EvalItem, output: EvaluatorOutput) -> Judgment:
        started = utcnow()
        prompt = self._render_prompt(item, output)

        try:
            if self._provider:
                res = await self._provider(prompt)
            else:
                res = await self._interactive_prompt(prompt)

            score = res.get("score", 0.0)
            rationale = res.get("rationale")
            error = None
        except Exception as exc:  # noqa: BLE001 — surfaced to the judgment record
            score = 0.0
            rationale = None
            error = str(exc)

        finished = utcnow()
        return Judgment(
            id=new_id("jdg"),
            run_id=PENDING_RUN_ID,
            trace_id=PENDING_TRACE_ID,
            judge_id=self.id,
            judge_version=self.version,
            score=score,
            rationale=rationale,
            determinism=self.determinism,
            started_at=started,
            finished_at=finished,
            error=error,
        )

    def _render_prompt(self, item: EvalItem, output: EvaluatorOutput) -> str:
        return (
            f"\n--- Human Evaluation Task ---\n"
            f"Instructions: {self.instructions}\n\n"
            f"Input:\n{item.input}\n\n"
            f"Output:\n{output.output}\n"
            f"-----------------------------\n"
        )

    async def _interactive_prompt(self, prompt: str) -> HumanResponse:
        """Run a blocking CLI prompt in a thread to avoid blocking the event loop."""
        if not sys.stdout.isatty():
            raise RuntimeError(
                "HumanJudge interactive mode requires a TTY. "
                "Supply a 'provider' callback for non-interactive use."
            )

        def _get_input() -> HumanResponse:
            click.echo(prompt)
            score = click.prompt("Score (0.0 - 1.0)", type=float)
            rationale = click.prompt("Rationale", type=str, default="")
            return {"score": score, "rationale": rationale}

        return await anyio.to_thread.run_sync(_get_input)


def human_judge_factory(**config: Any) -> HumanJudge:
    """Factory for HumanJudge used by the registry."""
    return HumanJudge(
        id=config.get("id", "eval_fabric.human"),
        version=config.get("version", "1.0.0"),
        instructions=config.get("instructions", "Rate the output from 0 to 1 based on correctness."),
        provider=config.get("provider"),
    )
