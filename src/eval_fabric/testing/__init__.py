"""Testing utilities exported for plugin authors and the framework's own tests.

Two things live here today:

- :mod:`eval_fabric.testing.contracts` — protocol-conformance test mixins that
  third-party plugin authors run against their own evaluators and judges.
- :mod:`eval_fabric.testing.fakes` — minimal fakes (in-memory trace store,
  recording exporter) the framework's own tests use.
"""

from eval_fabric.testing.contracts import EvaluatorContractTests, JudgeContractTests
from eval_fabric.testing.fakes import InMemoryTraceStore

__all__ = [
    "EvaluatorContractTests",
    "InMemoryTraceStore",
    "JudgeContractTests",
]
