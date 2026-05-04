"""Deterministic rule-based judges.

These are intentionally tiny: each compares the evaluator's output against a
declared expectation drawn from either the EvalItem or the judge config. They
are the right choice when you can express correctness as code.
"""

from __future__ import annotations

import json
import re
from typing import Any, Pattern

from eval_fabric.judges import PENDING_RUN_ID, PENDING_TRACE_ID, _coerce_judgment
from eval_fabric.models import (
    Determinism,
    EvalItem,
    EvaluatorOutput,
    Judgment,
    new_id,
    utcnow,
)


class RuleBasedJudge:
    """A configurable rule-based judge.

    Three modes are supported:

    - ``mode="exact_match"`` — the evaluator output must equal
      ``item.reference_output`` (or ``config["expected"]``).
    - ``mode="regex"``      — the output (str-coerced) must match
      ``config["pattern"]``.
    - ``mode="json_schema"``— the output must validate against
      ``config["schema"]`` (a small ad-hoc schema; we deliberately avoid a
      full jsonschema dependency).
    """

    determinism = Determinism.DETERMINISTIC

    def __init__(
        self,
        *,
        id: str = "eval_fabric.rule",
        version: str = "1.0.0",
        mode: str = "exact_match",
        expected: Any = None,
        pattern: str | None = None,
        schema: dict[str, Any] | None = None,
    ) -> None:
        self.id = id
        self.version = version
        self.mode = mode
        self.expected = expected
        self._pattern: Pattern[str] | None = re.compile(pattern) if pattern else None
        self.schema = schema

    async def judge(self, item: EvalItem, output: EvaluatorOutput) -> Judgment:
        started = utcnow()
        score, rationale = self._score(item, output)
        finished = utcnow()
        return Judgment(
            id=new_id("jdg"),
            run_id=PENDING_RUN_ID,
            trace_id=PENDING_TRACE_ID,
            judge_id=self.id,
            judge_version=self.version,
            score=score,
            rationale=rationale,
            determinism=self.determinism,
            started_at=started,
            finished_at=finished,
        )

    def _score(self, item: EvalItem, output: EvaluatorOutput) -> tuple[bool, str]:
        if self.mode == "exact_match":
            expected = self.expected if self.expected is not None else item.reference_output
            ok = output.output == expected
            return ok, f"expected={expected!r}, got={output.output!r}"
        if self.mode == "regex":
            if self._pattern is None:
                raise ValueError("regex mode requires a pattern")
            target = output.output if isinstance(output.output, str) else json.dumps(output.output)
            ok = self._pattern.search(target) is not None
            return ok, f"pattern={self._pattern.pattern!r}, target={target!r}"
        if self.mode == "json_schema":
            if self.schema is None:
                raise ValueError("json_schema mode requires a schema")
            ok, err = _validate_simple_schema(output.output, self.schema)
            return ok, err if err else "schema-valid"
        raise ValueError(f"unknown rule mode: {self.mode!r}")


def _validate_simple_schema(value: Any, schema: dict[str, Any]) -> tuple[bool, str | None]:
    """Tiny subset of JSON-Schema validation.

    Supports ``type``, ``required`` (object), ``enum``, ``minimum``/``maximum``
    on numbers, and recursive ``properties`` on objects. This is a local
    helper; users who need full JSON Schema should bring their own.
    """

    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            return False, f"expected object, got {type(value).__name__}"
        for k in schema.get("required", []):
            if k not in value:
                return False, f"missing required field {k!r}"
        for k, sub in (schema.get("properties") or {}).items():
            if k in value:
                ok, err = _validate_simple_schema(value[k], sub)
                if not ok:
                    return False, f".{k}: {err}"
        return True, None
    if expected_type == "array":
        if not isinstance(value, list):
            return False, f"expected array, got {type(value).__name__}"
        items_schema = schema.get("items")
        if items_schema:
            for i, v in enumerate(value):
                ok, err = _validate_simple_schema(v, items_schema)
                if not ok:
                    return False, f"[{i}]: {err}"
        return True, None
    if expected_type == "string" and not isinstance(value, str):
        return False, f"expected string, got {type(value).__name__}"
    if expected_type == "number" and not isinstance(value, (int, float)):
        return False, f"expected number, got {type(value).__name__}"
    if expected_type == "integer" and not isinstance(value, int):
        return False, f"expected integer, got {type(value).__name__}"
    if expected_type == "boolean" and not isinstance(value, bool):
        return False, f"expected boolean, got {type(value).__name__}"

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        return False, f"value {value!r} not in enum {enum!r}"
    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        return False, f"value {value} < minimum {schema['minimum']}"
    if "maximum" in schema and isinstance(value, (int, float)) and value > schema["maximum"]:
        return False, f"value {value} > maximum {schema['maximum']}"
    return True, None


# ---------------------------------------------------------------------------
# Entry-point factories. These match the registrations in pyproject.toml.
# ---------------------------------------------------------------------------


def exact_match_judge(**config: Any) -> RuleBasedJudge:
    """Factory: an exact-match judge.

    Compares evaluator output against ``item.reference_output`` (or the
    ``expected`` config field if supplied).
    """

    return RuleBasedJudge(
        id="eval_fabric.exact_match",
        version="1.0.0",
        mode="exact_match",
        expected=config.get("expected"),
    )


def regex_judge(**config: Any) -> RuleBasedJudge:
    """Factory: a regex-match judge configured by ``pattern``."""

    pattern = config.get("pattern")
    if not pattern:
        raise ValueError("regex_judge requires a 'pattern' config field")
    return RuleBasedJudge(
        id="eval_fabric.regex",
        version="1.0.0",
        mode="regex",
        pattern=pattern,
    )


def json_schema_judge(**config: Any) -> RuleBasedJudge:
    """Factory: a structural-validity judge configured by ``schema``."""

    schema = config.get("schema")
    if not schema:
        raise ValueError("json_schema_judge requires a 'schema' config field")
    return RuleBasedJudge(
        id="eval_fabric.json_schema",
        version="1.0.0",
        mode="json_schema",
        schema=schema,
    )


class _IdentityJudge:
    """Pass-through judge that adopts the evaluator's output as the score.

    Useful when the evaluator already returns a structured score. See ADR-0007.
    """

    id = "eval_fabric.identity"
    version = "1.0.0"
    determinism = Determinism.DETERMINISTIC

    async def judge(self, item: EvalItem, output: EvaluatorOutput) -> Judgment:
        started = utcnow()
        finished = utcnow()
        return _coerce_judgment(
            output.output,
            judge_id=self.id,
            judge_version=self.version,
            determinism=self.determinism,
            started_at=started,
            finished_at=finished,
        )


def identity_judge(**_config: Any) -> _IdentityJudge:
    return _IdentityJudge()
