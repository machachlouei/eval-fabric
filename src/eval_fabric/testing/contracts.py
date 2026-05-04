"""Protocol-conformance test base classes for plugin authors.

Subclass these in your plugin's tests, expose your plugin via the
``evaluator`` / ``judge`` fixture, and pytest collects ~dozens of assertions
that verify your plugin satisfies the contract the runner depends on.

These tests should not depend on any framework-internal behaviour. Anything
that fails here is a discrepancy between the contract published in
``docs/design.md`` and the plugin under test.
"""

from __future__ import annotations

from typing import Any

import pytest

from eval_fabric.judges import Judge
from eval_fabric.models import (
    Determinism,
    EvalItem,
    EvaluatorOutput,
    Judgment,
)


class EvaluatorContractTests:
    """Mixin: assertions every Evaluator implementation must satisfy."""

    @pytest.fixture
    def evaluator(self) -> Any:  # pragma: no cover — overridden
        raise NotImplementedError("provide an `evaluator` fixture")

    @pytest.fixture
    def sample_item(self) -> EvalItem:
        return EvalItem(
            item_id="contract-1",
            input="hello",
            reference_output="hello",
        )

    def test_has_id_and_version(self, evaluator: Any) -> None:
        assert isinstance(evaluator.id, str) and evaluator.id, (
            "evaluator must declare a non-empty `id`"
        )
        assert isinstance(evaluator.version, str) and evaluator.version, (
            "evaluator must declare a non-empty `version`"
        )

    @pytest.mark.anyio
    async def test_returns_evaluator_output(
        self, evaluator: Any, sample_item: EvalItem
    ) -> None:
        result = await evaluator(sample_item)
        assert isinstance(result, EvaluatorOutput), (
            "evaluator must return an EvaluatorOutput; "
            "use the `@evaluator` decorator if you do not already"
        )


class JudgeContractTests:
    """Mixin: assertions every Judge implementation must satisfy."""

    @pytest.fixture
    def judge(self) -> Any:  # pragma: no cover — overridden
        raise NotImplementedError("provide a `judge` fixture")

    @pytest.fixture
    def sample_item(self) -> EvalItem:
        return EvalItem(
            item_id="contract-1",
            input="hello",
            reference_output="hello",
        )

    @pytest.fixture
    def sample_output(self) -> EvaluatorOutput:
        return EvaluatorOutput(output="hello")

    def test_has_id_and_version(self, judge: Judge) -> None:
        assert isinstance(judge.id, str) and judge.id
        assert isinstance(judge.version, str) and judge.version

    def test_declares_determinism(self, judge: Judge) -> None:
        assert isinstance(judge.determinism, Determinism), (
            "judge.determinism must be a Determinism enum value"
        )

    @pytest.mark.anyio
    async def test_returns_judgment(
        self, judge: Judge, sample_item: EvalItem, sample_output: EvaluatorOutput
    ) -> None:
        verdict = await judge.judge(sample_item, sample_output)
        assert isinstance(verdict, Judgment)
        assert verdict.judge_id == judge.id
        assert verdict.judge_version == judge.version
        assert verdict.determinism == judge.determinism

    @pytest.mark.anyio
    async def test_deterministic_judges_are_stable(
        self, judge: Judge, sample_item: EvalItem, sample_output: EvaluatorOutput
    ) -> None:
        if judge.determinism != Determinism.DETERMINISTIC:
            pytest.skip("only DETERMINISTIC judges are required to be byte-stable")
        first = await judge.judge(sample_item, sample_output)
        second = await judge.judge(sample_item, sample_output)
        assert first.score == second.score, (
            f"judge {judge.id} declared DETERMINISTIC but produced different scores "
            f"on identical input: {first.score!r} vs {second.score!r}"
        )
