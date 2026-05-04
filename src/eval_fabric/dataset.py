"""Tiny dataset utilities.

`Dataset` is intentionally just ``AsyncIterator[EvalItem]``; this module
provides helpers for the two formats we ship out of the box (JSONL on disk and
in-memory iterables) without forcing a class hierarchy on users.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterable, AsyncIterator, Iterable

import anyio

from eval_fabric.models import EvalItem


async def as_async_iter(
    source: Iterable[EvalItem] | AsyncIterable[EvalItem],
) -> AsyncIterator[EvalItem]:
    """Coerce any iterable of items into an async iterator.

    The runner accepts both sync and async dataset adapters. Internally it
    funnels everything through this helper so the dispatch loop is one shape.
    """

    if hasattr(source, "__aiter__"):
        async for item in source:  # type: ignore[union-attr]
            yield item
        return
    for item in source:  # type: ignore[union-attr]
        yield item


def load_jsonl(path: str | Path) -> list[EvalItem]:
    """Load a dataset from a JSONL file synchronously.

    Each line is parsed as JSON and validated against :class:`EvalItem`. Loose
    schemas are common in early-stage evals; this loader tolerates the
    well-known shape ``{"item_id": ..., "input": ..., "reference_output": ...}``
    plus arbitrary extra fields.
    """

    items: list[EvalItem] = []
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: not valid JSON: {exc}") from exc
        if "item_id" not in data:
            data["item_id"] = f"{p.stem}:{lineno}"
        items.append(EvalItem.model_validate(data))
    return items


async def load_jsonl_async(path: str | Path) -> list[EvalItem]:
    """Async wrapper around :func:`load_jsonl` for use in async contexts."""

    return await anyio.to_thread.run_sync(load_jsonl, path)
