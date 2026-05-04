"""Tests for the built-in deterministic judges."""

from __future__ import annotations

import pytest

from eval_fabric.judges.builtin import (
    exact_match_judge,
    json_schema_judge,
    regex_judge,
)
from eval_fabric.models import Determinism, EvalItem, EvaluatorOutput


pytestmark = pytest.mark.anyio


async def test_exact_match_passes_when_equal() -> None:
    judge = exact_match_judge()
    item = EvalItem(item_id="x", input="hello", reference_output="hello")
    out = EvaluatorOutput(output="hello")
    verdict = await judge.judge(item, out)
    assert verdict.score is True
    assert verdict.determinism == Determinism.DETERMINISTIC


async def test_exact_match_fails_when_different() -> None:
    judge = exact_match_judge()
    item = EvalItem(item_id="x", input="hello", reference_output="hello")
    out = EvaluatorOutput(output="goodbye")
    verdict = await judge.judge(item, out)
    assert verdict.score is False


async def test_regex_judge_matches_pattern() -> None:
    judge = regex_judge(pattern=r"hello, [A-Z][a-z]+!")
    item = EvalItem(item_id="x", input="greet")
    out = EvaluatorOutput(output="hello, World!")
    verdict = await judge.judge(item, out)
    assert verdict.score is True


async def test_json_schema_judge_validates_object() -> None:
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer", "minimum": 0},
        },
    }
    judge = json_schema_judge(schema=schema)
    out = EvaluatorOutput(output={"name": "Ada", "age": 36})
    item = EvalItem(item_id="x", input={})
    verdict = await judge.judge(item, out)
    assert verdict.score is True

    bad = EvaluatorOutput(output={"age": -1})
    verdict = await judge.judge(item, bad)
    assert verdict.score is False


async def test_deterministic_judge_is_byte_stable() -> None:
    judge = exact_match_judge()
    item = EvalItem(item_id="x", input="hello", reference_output="hello")
    out = EvaluatorOutput(output="hello")
    first = await judge.judge(item, out)
    second = await judge.judge(item, out)
    assert first.score == second.score
    assert first.determinism == second.determinism
