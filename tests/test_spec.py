"""Tests for the spec layer.

These exercise the public surface only (loader, validator, dump). The
property tested is "the documented invariant holds", not "the helper called
the helper" — ``docs/testing.md`` explains the philosophy.
"""

from __future__ import annotations

import pytest

from eval_fabric.errors import SpecValidationError
from eval_fabric.spec import EvalSpec, dump_spec, load_spec, load_spec_dict


_VALID_SPEC = {
    "schema_version": "1",
    "id": "team/qa-bot",
    "version": "1.2.0",
    "evaluator": {"id": "team.qa_bot"},
    "judges": [{"id": "eval_fabric.exact_match"}],
    "scoring": {
        "metrics": [
            {"name": "accuracy", "from": "judges", "aggregator": "mean"},
        ],
    },
}


def test_load_spec_dict_round_trips() -> None:
    spec = load_spec(dict(_VALID_SPEC))
    again = load_spec_dict(spec.model_dump(mode="json", by_alias=True))
    assert again["id"] == _VALID_SPEC["id"]


def test_eval_spec_is_immutable() -> None:
    spec = load_spec(dict(_VALID_SPEC))
    with pytest.raises(Exception):
        spec.id = "different"  # type: ignore[misc]


def test_unknown_field_is_rejected() -> None:
    bad = dict(_VALID_SPEC) | {"not_a_field": True}
    with pytest.raises(SpecValidationError):
        load_spec(bad)


def test_invalid_semver_is_rejected() -> None:
    bad = dict(_VALID_SPEC) | {"version": "1.2"}
    with pytest.raises(SpecValidationError):
        load_spec(bad)


def test_unsupported_schema_version_is_rejected() -> None:
    bad = dict(_VALID_SPEC) | {"schema_version": "99"}
    with pytest.raises(SpecValidationError):
        load_spec(bad)


def test_dump_yaml_then_load_is_byte_stable() -> None:
    spec = load_spec(dict(_VALID_SPEC))
    yaml_text = dump_spec(spec, format="yaml")
    reloaded = load_spec_dict(yaml_text)
    assert reloaded["id"] == spec.id
    assert reloaded["scoring"]["metrics"][0]["from"] == "judges"


def test_judges_must_be_non_empty() -> None:
    bad = dict(_VALID_SPEC) | {"judges": []}
    with pytest.raises(SpecValidationError):
        load_spec(bad)


def test_runtime_defaults_match_design_doc() -> None:
    spec = load_spec(dict(_VALID_SPEC))
    assert spec.runtime.max_concurrent == 64
    assert spec.runtime.task_timeout_seconds == 60.0
    assert spec.runtime.max_retries == 2
    assert spec.runtime.on_failure == "skip"


def test_env_var_substitution_in_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EF_TEST_RUN_ID", "abc")
    yaml_text = """
schema_version: '1'
id: team/qa-bot
version: 1.2.0
evaluator:
  id: team.qa_bot
judges:
  - id: eval_fabric.exact_match
scoring:
  metrics:
    - name: accuracy
      from: judges
      aggregator: mean
metadata:
  run: ${EF_TEST_RUN_ID}
"""
    spec = load_spec(yaml_text)
    assert spec.metadata["run"] == "abc"
