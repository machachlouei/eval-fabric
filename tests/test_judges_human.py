import pytest
from eval_fabric.models import EvalItem, EvaluatorOutput, Determinism
from eval_fabric.judges.builtin import HumanJudge

@pytest.mark.anyio
async def test_human_judge_with_provider():
    async def mock_provider(prompt):
        assert "Human Evaluation Task" in prompt
        return {"score": 0.8, "rationale": "Looks good"}

    judge = HumanJudge(provider=mock_provider)
    item = EvalItem(item_id="1", input="hello")
    output = EvaluatorOutput(output="hi")
    
    judgment = await judge.judge(item, output)
    
    assert judgment.score == 0.8
    assert judgment.rationale == "Looks good"
    assert judgment.judge_id == "eval_fabric.human"
    assert judgment.determinism == Determinism.STOCHASTIC

@pytest.mark.anyio
async def test_human_judge_error_handling():
    async def failing_provider(prompt):
        raise RuntimeError("Human went on strike")

    judge = HumanJudge(provider=failing_provider)
    item = EvalItem(item_id="1", input="hello")
    output = EvaluatorOutput(output="hi")
    
    judgment = await judge.judge(item, output)
    
    assert judgment.score == 0.0
    assert "Human went on strike" in judgment.error

@pytest.mark.anyio
async def test_human_judge_interactive_fails_without_tty(monkeypatch):
    # Ensure stdout.isatty() returns False
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    
    judge = HumanJudge()  # No provider -> interactive
    item = EvalItem(item_id="1", input="hello")
    output = EvaluatorOutput(output="hi")
    
    judgment = await judge.judge(item, output)
    
    assert judgment.score == 0.0
    assert "requires a TTY" in judgment.error
