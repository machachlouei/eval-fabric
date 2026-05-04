"""Echo evaluator used by ``ef init --example hello-world``.

Returns the input verbatim. Lets a fresh install run end-to-end without any
network or API keys, which is what the smoke-test in ``docs/setup.md``
recommends.
"""

from __future__ import annotations

from typing import Any

from eval_fabric.evaluators import evaluator
from eval_fabric.models import EvalItem, EvaluatorOutput


@evaluator(id="eval_fabric.examples.echo", version="1.0.0")
async def echo(item: EvalItem) -> EvaluatorOutput:
    """Return the input value unchanged.

    The judge that pairs with this in the example spec is exact-match against
    ``reference_output``, which is identical to the input — so the run always
    passes.
    """

    payload: Any = item.input
    return EvaluatorOutput(output=payload, metadata={"echo": True})
