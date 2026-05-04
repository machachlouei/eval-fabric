"""Agentic Support Evaluator.

This module simulates an agentic support bot that can 'call tools'. 
The framework's value here is orchestrating the evaluation of both the 
final answer AND the tool-use trace.
"""

from __future__ import annotations
import random
from eval_fabric.evaluators import evaluator
from eval_fabric.models import EvalItem, EvaluatorOutput

@evaluator(id="examples.support_agent", version="1.0.0")
async def support_agent(item: EvalItem) -> EvaluatorOutput:
    """
    A mock agent that parses a user query and decides whether to 'call a tool'.
    """
    query = item.input.lower()
    tool_calls = []
    
    # Simulate agentic reasoning
    if "order" in query or "status" in query:
        # Simulate calling a 'get_order_status' tool
        tool_calls.append({
            "tool": "get_order_status",
            "args": {"order_id": "ORD-123"},
            "output": {"status": "shipped", "delivery_date": "2024-05-10"}
        })
        response = "Your order ORD-123 has been shipped and will arrive on May 10th."
    elif "refund" in query:
        # Simulate calling a 'process_refund' tool
        tool_calls.append({
            "tool": "check_eligibility",
            "args": {"user_id": "USR-456"},
            "output": {"eligible": True}
        })
        response = "I've checked your account, and you are eligible for a refund. I'll start that for you."
    else:
        response = "I'm sorry, I can only help with orders and refunds. How can I assist you?"

    # The EvaluatorOutput carries the final answer AND the tool trace in metadata
    return EvaluatorOutput(
        output=response,
        metadata={
            "tool_calls": tool_calls,
            "model": "gpt-4o-mock",
            "latency_ms": random.randint(500, 1500)
        }
    )
