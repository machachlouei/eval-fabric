"""Migration chain for EvalSpec across major schema versions.

There is currently one major version. Each future migration is a hand-written
function `migrate_vN_to_v(N+1)`. We do not generate migrations automatically;
the semantics are not always mechanical (ADR-0004).
"""

from __future__ import annotations

from typing import Any, Callable

from eval_fabric.errors import SpecValidationError
from eval_fabric.spec.models import CURRENT_SCHEMA_VERSION

_Migration = Callable[[dict[str, Any]], dict[str, Any]]

# Map from "<from>:<to>" to a migration function. Every migration is
# pure: it takes a dict and returns a new dict.
_MIGRATIONS: dict[str, _Migration] = {}


def current_major() -> str:
    """The current EvalSpec major version, as a string."""

    return CURRENT_SCHEMA_VERSION


def register_migration(from_v: str, to_v: str, fn: _Migration) -> None:
    """Register a migration in the chain. Idempotent for the same callable."""

    key = f"{from_v}:{to_v}"
    existing = _MIGRATIONS.get(key)
    if existing is not None and existing is not fn:
        raise SpecValidationError(f"conflicting migration registered for {key}")
    _MIGRATIONS[key] = fn


def migrate_to_current(data: dict[str, Any]) -> dict[str, Any]:
    """Walk the migration chain until `schema_version == current_major()`.

    Raises :class:`SpecValidationError` if a step is missing.
    """

    current = current_major()
    version = str(data.get("schema_version", "1"))
    if version == current:
        return data

    seen: set[str] = set()
    while version != current:
        if version in seen:
            raise SpecValidationError(f"migration loop detected at schema_version={version}")
        seen.add(version)
        try:
            next_v = str(int(version) + 1)
        except ValueError as exc:
            raise SpecValidationError(
                f"schema_version={version!r} is not an integer-valued major"
            ) from exc
        key = f"{version}:{next_v}"
        fn = _MIGRATIONS.get(key)
        if fn is None:
            raise SpecValidationError(
                f"no migration registered for {key}; "
                f"run `ef migrate` or upgrade the framework"
            )
        data = fn(data)
        version = str(data.get("schema_version", next_v))
    return data


__all__ = [
    "current_major",
    "migrate_to_current",
    "register_migration",
]
