"""Shared fixtures kept tiny on purpose.

Per ``docs/testing.md``: a top-level conftest is reserved for cross-cutting
fixtures only. Module-specific fixtures live alongside their tests.
"""

from __future__ import annotations

import pytest

from eval_fabric.registry import reset_registry


@pytest.fixture
def anyio_backend() -> str:
    """Run anyio tests on asyncio. trio is supported but not the default."""

    return "asyncio"


@pytest.fixture(autouse=True)
def _isolate_registry() -> None:
    """Reset the plugin registry between tests so registrations do not leak."""

    yield
    reset_registry()
