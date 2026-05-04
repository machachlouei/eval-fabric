"""Round-trip and hash-stability tests for the typed records."""

from __future__ import annotations

from eval_fabric.models import (
    Determinism,
    EvalItem,
    EvaluatorOutput,
    Judgment,
    Trace,
    new_id,
    utcnow,
)


def test_eval_item_content_hash_is_stable() -> None:
    a = EvalItem(item_id="x", input={"q": "a?"})
    b = EvalItem(item_id="x", input={"q": "a?"})
    assert a.content_hash() == b.content_hash()


def test_eval_item_content_hash_changes_on_input() -> None:
    a = EvalItem(item_id="x", input="one")
    b = EvalItem(item_id="x", input="two")
    assert a.content_hash() != b.content_hash()


def test_judgment_round_trips_through_json() -> None:
    now = utcnow()
    j = Judgment(
        id=new_id("jdg"),
        run_id="run_a",
        trace_id="trc_a",
        judge_id="judge.x",
        judge_version="1.0.0",
        score=0.5,
        determinism=Determinism.SAMPLING_DETERMINISTIC,
        started_at=now,
        finished_at=now,
        cost_usd=0.0001,
    )
    blob = j.model_dump_json()
    restored = Judgment.model_validate_json(blob)
    assert restored == j


def test_trace_round_trips_through_json() -> None:
    now = utcnow()
    item = EvalItem(item_id="x", input="hi")
    out = EvaluatorOutput(output="hi")
    tr = Trace(
        id="trc_1",
        run_id="run_1",
        item_id="x",
        evaluator_id="team.alpha",
        evaluator_version="1.0.0",
        input=item,
        output=out,
        status="ok",
        started_at=now,
        finished_at=now,
    )
    restored = Trace.model_validate_json(tr.model_dump_json())
    assert restored == tr
