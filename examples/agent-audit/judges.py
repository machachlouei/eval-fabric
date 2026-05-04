"""Custom Judges for Agentic Auditing.

This module shows how to write a judge that doesn't just look at the 
string output, but inspects the 'tool_calls' in the metadata.
"""

from __future__ import annotations
from typing import Any
from eval_fabric.judges import judge
from eval_fabric.models import EvalItem, EvaluatorOutput, Determinism

@judge(id="examples.tool_use_correctness", version="1.0.0", determinism=Determinism.DETERMINISTIC)
async def tool_use_judge(item: EvalItem, output: EvaluatorOutput) -> dict[str, Any]:
    """
    Checks if the agent called the tool expected by the dataset.
    """
    expected_tool = item.metadata.get("expected_tool")
    actual_tools = [t["tool"] for t in output.metadata.get("tool_calls", [])]
    
    if not expected_tool:
        # If no tool was expected, check that none were called
        success = len(actual_tools) == 0
        return {
            "score": float(success),
            "rationale": "No tool was expected." if success else f"Unexpected tools called: {actual_tools}"
        }
    
    success = expected_tool in actual_tools
    return {
        "score": float(success),
        "rationale": f"Expected tool '{expected_tool}' was called." if success else f"Missing expected tool '{expected_tool}'."
    }
