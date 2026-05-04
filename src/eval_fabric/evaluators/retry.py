"""Retry utilities for evaluators.

Evaluators often call external APIs that fail transiently. This module
provides a standardized retry decorator built on `tenacity` that matches
the framework's error model.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, TypeVar

from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from eval_fabric.errors import TransientError

T = TypeVar("T")
log = logging.getLogger(__name__)


def retry(
    *,
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (TransientError,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator to retry an async function with exponential backoff and jitter.

    Defaults to retrying `TransientError` up to 3 times.

    Example:
        @retry(max_attempts=5)
        async def call_api(item):
            ...
    """

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        # We use AsyncRetrying directly so we can wrap the function cleanly.
        retrier = AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_random_exponential(min=min_wait, max=max_wait),
            retry=retry_if_exception_type(exceptions),
            before_sleep=before_sleep_log(log, logging.WARNING),
            reraise=True,
        )

        async def wrapped(*args: Any, **kwargs: Any) -> T:
            async for attempt in retrier:
                with attempt:
                    return await fn(*args, **kwargs)
            raise RuntimeError("unreachable")

        return wrapped

    return decorator
