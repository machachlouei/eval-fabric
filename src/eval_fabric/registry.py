"""Plugin registry for evaluators and judges.

Two paths converge on the same registry: explicit registration in user code,
and Python entry points discovered via ``importlib.metadata``. See ADR-0002.

The registry holds *factories*. A factory is either:

- a zero-argument callable returning the plugin instance, or
- the plugin instance itself (callable / object with ``__call__``).

This lets a plugin author write either ``@evaluator(id=...)`` on an async
function (instance form) or a class whose ``__init__`` takes config kwargs
(factory form, by registering ``MyPlugin`` directly).
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import logging
from dataclasses import dataclass
from typing import Any, Callable

from eval_fabric.errors import (
    DuplicateRegistrationError,
    PluginContractError,
)

log = logging.getLogger(__name__)

_EVALUATOR_GROUP = "eval_fabric.evaluators"
_JUDGE_GROUP = "eval_fabric.judges"


# A factory may be the plugin itself (callable) or a builder accepting config.
Factory = Callable[..., Any]


@dataclass
class PluginRecord:
    """Bookkeeping for a registered plugin."""

    id: str
    factory: Factory
    source: str  # "explicit" | "entry_point" | "builtin"
    healthy: bool = True
    load_error: str | None = None


class _Registry:
    """Process-global registry. Module-level instance is the singleton.

    Methods are intentionally not async; registration is in-memory only.
    """

    def __init__(self) -> None:
        self._evaluators: dict[str, PluginRecord] = {}
        self._judges: dict[str, PluginRecord] = {}
        self._entry_points_loaded = False

    # -- Registration -------------------------------------------------

    def register_evaluator(
        self,
        id: str,
        factory: Factory,
        *,
        source: str = "explicit",
    ) -> None:
        self._register(self._evaluators, id, factory, source=source, kind="evaluator")

    def register_judge(
        self,
        id: str,
        factory: Factory,
        *,
        source: str = "explicit",
    ) -> None:
        self._register(self._judges, id, factory, source=source, kind="judge")

    def _register(
        self,
        bucket: dict[str, PluginRecord],
        id: str,
        factory: Factory,
        *,
        source: str,
        kind: str,
    ) -> None:
        existing = bucket.get(id)
        if existing is not None:
            if existing.factory is factory:
                # Idempotent.
                return
            raise DuplicateRegistrationError(
                f"{kind} id={id!r} is already registered by another factory; "
                "registration ids must be globally unique"
            )
        bucket[id] = PluginRecord(id=id, factory=factory, source=source)

    # -- Lookup -------------------------------------------------------

    def get_evaluator(self, id: str, *, config: dict[str, Any] | None = None) -> Any:
        return self._get(self._evaluators, id, config=config, kind="evaluator")

    def get_judge(self, id: str, *, config: dict[str, Any] | None = None) -> Any:
        return self._get(self._judges, id, config=config, kind="judge")

    def _get(
        self,
        bucket: dict[str, PluginRecord],
        id: str,
        *,
        config: dict[str, Any] | None,
        kind: str,
    ) -> Any:
        self._ensure_entry_points_loaded()
        record = bucket.get(id)
        if record is None:
            available = sorted(bucket)
            raise PluginContractError(
                f"{kind} id={id!r} is not registered. "
                f"Known {kind}s: {available or '(none)'}"
            )
        if not record.healthy:
            raise PluginContractError(
                f"{kind} id={id!r} failed to load: {record.load_error}"
            )
        instance = self._instantiate(record.factory, config or {})
        if instance is None:
            raise PluginContractError(f"{kind} factory for {id!r} returned None")
        return instance

    @staticmethod
    def _instantiate(factory: Factory, config: dict[str, Any]) -> Any:
        """Best-effort factory invocation.

        Tries `factory(**config)` first; falls back to `factory()` and finally
        to returning the factory itself if it appears to be a configured
        plugin instance already.
        """

        if not callable(factory):
            return factory
        try:
            return factory(**config)
        except TypeError:
            try:
                return factory()
            except TypeError:
                return factory

    # -- Listing ------------------------------------------------------

    def list_evaluators(self) -> list[PluginRecord]:
        self._ensure_entry_points_loaded()
        return sorted(self._evaluators.values(), key=lambda r: r.id)

    def list_judges(self) -> list[PluginRecord]:
        self._ensure_entry_points_loaded()
        return sorted(self._judges.values(), key=lambda r: r.id)

    # -- Entry-point loading -----------------------------------------

    def _ensure_entry_points_loaded(self) -> None:
        if self._entry_points_loaded:
            return
        self._entry_points_loaded = True
        self._load_entry_points(_EVALUATOR_GROUP, self.register_evaluator)
        self._load_entry_points(_JUDGE_GROUP, self.register_judge)

    def _load_entry_points(
        self,
        group: str,
        register: Callable[..., None],
    ) -> None:
        try:
            eps = importlib_metadata.entry_points(group=group)
        except TypeError:  # py<3.10 compat shim, harmless on 3.11+
            eps = importlib_metadata.entry_points().get(group, [])  # type: ignore[assignment]
        for ep in eps:
            try:
                obj = ep.load()
            except Exception as exc:  # noqa: BLE001 — plugin import failure isolation
                log.warning("plugin %s failed to load: %s", ep.name, exc)
                # Record a stub so `ef plugins list --health` can surface it.
                bucket = (
                    self._evaluators if group == _EVALUATOR_GROUP else self._judges
                )
                bucket[ep.name] = PluginRecord(
                    id=ep.name,
                    factory=lambda *a, **k: None,
                    source="entry_point",
                    healthy=False,
                    load_error=str(exc),
                )
                continue
            try:
                register(ep.name, obj, source="entry_point")
            except DuplicateRegistrationError:
                # Two packages provide the same id — first wins, log the conflict.
                log.warning(
                    "plugin id=%s from entry point %s clashes with an existing registration",
                    ep.name,
                    ep,
                )

    # -- Test helper --------------------------------------------------

    def reset(self) -> None:
        """Clear the registry. Primarily for tests."""

        self._evaluators.clear()
        self._judges.clear()
        self._entry_points_loaded = False


_registry = _Registry()


# Public API ---------------------------------------------------------------


def register_evaluator(id: str, factory: Factory) -> Factory:
    """Register an evaluator factory under `id`.

    Returns the factory unchanged so this can be used as a decorator.
    """

    _registry.register_evaluator(id, factory)
    return factory


def register_judge(id: str, factory: Factory) -> Factory:
    """Register a judge factory under `id`. Returns it unchanged."""

    _registry.register_judge(id, factory)
    return factory


def get_evaluator(id: str, config: dict[str, Any] | None = None) -> Any:
    return _registry.get_evaluator(id, config=config)


def get_judge(id: str, config: dict[str, Any] | None = None) -> Any:
    return _registry.get_judge(id, config=config)


def list_evaluators() -> list[PluginRecord]:
    return _registry.list_evaluators()


def list_judges() -> list[PluginRecord]:
    return _registry.list_judges()


def reset_registry() -> None:
    """Clear the registry. Tests use this to keep state from leaking."""

    _registry.reset()
