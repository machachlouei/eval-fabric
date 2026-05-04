"""EvalSpec contract layer.

This package owns the EvalSpec model, validation, the YAML loader and the
migration registry. Loading a spec runs the migration chain so callers always
see the current major version.
"""

from eval_fabric.spec.loader import dump_spec, load_spec, load_spec_dict
from eval_fabric.spec.migrations import current_major, migrate_to_current
from eval_fabric.spec.models import (
    CURRENT_SCHEMA_VERSION,
    EvalSpec,
    EvaluatorRef,
    JudgeRef,
    MetricSpec,
    RuntimeConfig,
    ScoringConfig,
    validate_spec,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "EvalSpec",
    "EvaluatorRef",
    "JudgeRef",
    "MetricSpec",
    "RuntimeConfig",
    "ScoringConfig",
    "current_major",
    "dump_spec",
    "load_spec",
    "load_spec_dict",
    "migrate_to_current",
    "validate_spec",
]
