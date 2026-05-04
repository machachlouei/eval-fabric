"""Registry behaviour: lookups, idempotency, conflict detection."""

from __future__ import annotations

import pytest

from eval_fabric.errors import DuplicateRegistrationError, PluginContractError
from eval_fabric.registry import (
    get_evaluator,
    get_judge,
    list_evaluators,
    register_evaluator,
    register_judge,
)


def _make_factory(name: str):
    def factory(**_config):
        class _Plugin:
            id = name
            version = "1.0.0"

        return _Plugin()

    return factory


def test_register_and_get_evaluator() -> None:
    register_evaluator("team.alpha", _make_factory("team.alpha"))
    plug = get_evaluator("team.alpha")
    assert plug.id == "team.alpha"


def test_register_idempotent_for_same_factory() -> None:
    factory = _make_factory("team.beta")
    register_evaluator("team.beta", factory)
    register_evaluator("team.beta", factory)  # no error
    plug = get_evaluator("team.beta")
    assert plug.id == "team.beta"


def test_register_conflicting_factory_raises() -> None:
    register_evaluator("team.gamma", _make_factory("team.gamma"))
    with pytest.raises(DuplicateRegistrationError):
        register_evaluator("team.gamma", _make_factory("team.gamma"))


def test_unknown_id_raises_with_known_ids_listed() -> None:
    register_evaluator("team.delta", _make_factory("team.delta"))
    with pytest.raises(PluginContractError) as exc_info:
        get_evaluator("team.unknown")
    assert "team.delta" in str(exc_info.value)


def test_judge_path_is_separate_from_evaluator_path() -> None:
    register_judge("team.judge_one", _make_factory("team.judge_one"))
    judge = get_judge("team.judge_one")
    assert judge.id == "team.judge_one"
    with pytest.raises(PluginContractError):
        get_evaluator("team.judge_one")


def test_listing_returns_sorted_records() -> None:
    register_evaluator("team.zzz", _make_factory("team.zzz"))
    register_evaluator("team.aaa", _make_factory("team.aaa"))
    ids = [r.id for r in list_evaluators()]
    assert ids == sorted(ids)
