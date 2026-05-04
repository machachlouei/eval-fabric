"""Built-in reference judges shipped with the framework.

These are deterministic by design and do not call out to LLMs. They cover the
"sanity check" tier of evaluations and are what the example specs reference.
"""

from eval_fabric.judges.builtin._llm import LLMJudge, llm_judge_factory
from eval_fabric.judges.builtin._rule import (
    RuleBasedJudge,
    exact_match_judge,
    identity_judge,
    json_schema_judge,
    regex_judge,
)

__all__ = [
    "LLMJudge",
    "RuleBasedJudge",
    "exact_match_judge",
    "identity_judge",
    "json_schema_judge",
    "llm_judge_factory",
    "regex_judge",
]
