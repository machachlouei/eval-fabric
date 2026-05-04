"""URI dispatch for trace-store backends.

The runner is given a URI such as ``sqlite:///./runs/runs.db``. We split on
``://``, look up the scheme in a small registry, and hand the path/query to
the matching backend factory. New backends register themselves either
explicitly or through the ``eval_fabric.tracestore.backends`` entry point.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import logging
from typing import Callable

from eval_fabric.errors import TraceStoreError
from eval_fabric.tracestore.protocol import TraceStore

log = logging.getLogger(__name__)

BackendFactory = Callable[[str], TraceStore]


_BACKENDS: dict[str, BackendFactory] = {}
_LOADED_FROM_ENTRY_POINTS = False


def register_backend(scheme: str, factory: BackendFactory) -> None:
    """Register a trace-store backend factory under a URI scheme."""

    _BACKENDS[scheme] = factory


def _ensure_entry_points_loaded() -> None:
    global _LOADED_FROM_ENTRY_POINTS
    if _LOADED_FROM_ENTRY_POINTS:
        return
    _LOADED_FROM_ENTRY_POINTS = True
    try:
        eps = importlib_metadata.entry_points(group="eval_fabric.tracestore.backends")
    except TypeError:  # pragma: no cover — older metadata API
        eps = importlib_metadata.entry_points().get(  # type: ignore[assignment]
            "eval_fabric.tracestore.backends", []
        )
    for ep in eps:
        try:
            cls = ep.load()
        except Exception as exc:  # noqa: BLE001
            log.warning("trace-store backend %s failed to load: %s", ep.name, exc)
            continue
        register_backend(ep.name, cls)


def open_trace_store(uri: str) -> TraceStore:
    """Resolve a URI to a trace-store instance.

    Does not call ``open()``; the caller is responsible for the lifecycle so
    we can reuse a single instance across resume / replay invocations without
    surprising open/close semantics.
    """

    _ensure_entry_points_loaded()
    if "://" not in uri:
        raise TraceStoreError(f"trace-store URI {uri!r} is missing a scheme")
    scheme, rest = uri.split("://", 1)
    factory = _BACKENDS.get(scheme)
    if factory is None:
        # Fallback: built-in sqlite is always available even if entry points
        # discovery failed for some reason.
        if scheme == "sqlite":
            from eval_fabric.tracestore.sqlite import SQLiteTraceStore

            return SQLiteTraceStore(rest)
        raise TraceStoreError(
            f"no trace-store backend registered for scheme {scheme!r}; "
            f"known schemes: {sorted(_BACKENDS) or '(none)'}"
        )
    return factory(rest)
