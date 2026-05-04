"""eval-fabric: a pluggable evaluation orchestration framework.

The public surface lives in submodules; this module re-exports the symbols a
caller is most likely to import directly.
"""

from eval_fabric.errors import (
    DuplicateRegistrationError,
    EvalFabricError,
    PluginContractError,
    SpecValidationError,
    TraceStoreError,
    TransientError,
)
from eval_fabric.models import (
    EvalItem,
    EvaluatorOutput,
    Judgment,
    JudgmentId,
    RunId,
    RunResult,
    Span,
    Trace,
    TraceId,
)
from eval_fabric.run_loader import load_run

__version__ = "0.1.0"

__all__ = [
    "DuplicateRegistrationError",
    "EvalFabricError",
    "EvalItem",
    "EvaluatorOutput",
    "Judgment",
    "JudgmentId",
    "PluginContractError",
    "RunId",
    "RunResult",
    "Span",
    "SpecValidationError",
    "Trace",
    "TraceId",
    "TraceStoreError",
    "TransientError",
    "__version__",
    "load_run",
]
