"""LLM-as-judge reference implementation.

The framework does not ship a hard dependency on any LLM SDK. Instead, this
module provides a Judge whose ``__init__`` accepts an arbitrary async
``call_model`` callable — anyone wiring up OpenAI, Anthropic, or a local model
just supplies a callable that takes a prompt and returns a string.

The judge is :class:`Determinism.SAMPLING_DETERMINISTIC` by default; users who
sample at temperature > 0 should declare ``Determinism.STOCHASTIC`` when
constructing.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

from eval_fabric.judges import PENDING_RUN_ID, PENDING_TRACE_ID
from eval_fabric.models import (
    Determinism,
    EvalItem,
    EvaluatorOutput,
    Judgment,
    new_id,
    utcnow,
)

CallModel = Callable[[str], Awaitable[str]]


_SCORE_LINE = re.compile(r"score\s*[:=]\s*([0-9]*\.?[0-9]+)", re.IGNORECASE)


class LLMJudge:
    """A general-purpose LLM-as-judge.

    Given a ``criterion`` (the rubric), an item, and the evaluator's output,
    the judge formats a prompt, calls the supplied ``call_model``, and parses
    a numeric score from the response. ``rationale`` captures the full
    response for inspection.
    """

    def __init__(
        self,
        *,
        id: str,
        version: str,
        criterion: str,
        call_model: CallModel,
        determinism: Determinism = Determinism.SAMPLING_DETERMINISTIC,
        prompt_template: str | None = None,
    ) -> None:
        self.id = id
        self.version = version
        self.determinism = determinism
        self.criterion = criterion
        self._call_model = call_model
        self._prompt_template = prompt_template or _DEFAULT_TEMPLATE

    async def judge(self, item: EvalItem, output: EvaluatorOutput) -> Judgment:
        started = utcnow()
        prompt = self._render_prompt(item, output)
        try:
            response = await self._call_model(prompt)
            score = _parse_score(response)
            error: str | None = None
        except Exception as exc:  # noqa: BLE001 — judge failures are surfaced
            response = ""
            score = 0.0
            error = str(exc)
        finished = utcnow()
        return Judgment(
            id=new_id("jdg"),
            run_id=PENDING_RUN_ID,
            trace_id=PENDING_TRACE_ID,
            judge_id=self.id,
            judge_version=self.version,
            score=score,
            rationale=response or None,
            determinism=self.determinism,
            started_at=started,
            finished_at=finished,
            error=error,
        )

    def _render_prompt(self, item: EvalItem, output: EvaluatorOutput) -> str:
        return self._prompt_template.format(
            criterion=self.criterion,
            input=_to_text(item.input),
            output=_to_text(output.output),
            reference=_to_text(item.reference_output) if item.reference_output is not None else "",
        )


_DEFAULT_TEMPLATE = """\
You are evaluating a system's output against a criterion.

Criterion: {criterion}

Input:
{input}

System output:
{output}

Reference (may be empty):
{reference}

Respond with a single line beginning with `score: ` followed by a number
between 0 and 1, then a brief rationale on the next line.
"""


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _parse_score(response: str) -> float:
    """Extract the score number out of an LLM response.

    Falls back to 0.0 if no parseable score is present, on the principle that
    "the judge couldn't decide" should not silently look like full marks.
    """

    match = _SCORE_LINE.search(response)
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def llm_judge_factory(**config: Any) -> LLMJudge:
    """Factory used by tests and documentation examples.

    Real deployments will register their own factory via entry points — this
    one requires the caller to pass a ``call_model`` callable in the config,
    which is fine for tests but not for general use.
    """

    call_model = config.get("call_model")
    if call_model is None:
        raise ValueError(
            "llm_judge_factory requires a 'call_model' callable; "
            "wire your own factory for production use"
        )
    return LLMJudge(
        id=config.get("id", "eval_fabric.llm_judge"),
        version=config.get("version", "1.0.0"),
        criterion=config.get("criterion", "Is the output correct?"),
        call_model=call_model,
        determinism=Determinism(config.get("determinism", "sampling_deterministic")),
        prompt_template=config.get("prompt_template"),
    )
