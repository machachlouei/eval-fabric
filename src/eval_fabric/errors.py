"""Custom error types.

Errors are part of the public API. Users catch them; CI hooks alert on them.
Keep them stable and informative.
"""

from __future__ import annotations


class EvalFabricError(Exception):
    """Base class for every error this framework raises."""


class SpecValidationError(EvalFabricError):
    """An EvalSpec failed to validate or load."""


class DuplicateRegistrationError(EvalFabricError):
    """Two distinct factories were registered under the same plugin id."""


class PluginContractError(EvalFabricError):
    """A loaded plugin does not satisfy the Evaluator or Judge protocol."""


class TraceStoreError(EvalFabricError):
    """A trace-store operation failed (connectivity, schema mismatch, write error)."""


class TraceStoreSchemaMismatch(TraceStoreError):
    """Opened a trace store whose schema version is not what the framework expects."""


class TransientError(EvalFabricError):
    """A retryable failure.

    Plugins should raise this (or a subclass) for errors the runner is allowed
    to retry. Anything else is treated as terminal and counts against the
    `on_failure` policy.
    """


class RunAborted(EvalFabricError):
    """A run terminated because `on_failure=abort` and an item failed."""


class JudgeContractViolation(EvalFabricError):
    """A judge declared a determinism class but observed behaviour disagrees."""
