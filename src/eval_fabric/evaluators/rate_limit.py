"""Rate limiting for evaluators.

Evaluators often need to stay within QPS limits of external APIs. This
module provides a simple token-bucket rate limiter that works with AnyIO.
"""

from __future__ import annotations

import anyio
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


class RateLimiter:
    """A token-bucket rate limiter.

    Can be used as an async context manager or to wrap an async function.

    Example:
        limiter = RateLimiter(qps=10)
        async with limiter:
            await call_api()

        @limiter.wrap
        async def call_api(item):
            ...
    """

    def __init__(self, qps: float, burst: int = 1) -> None:
        if qps <= 0:
            raise ValueError("qps must be positive")
        self.qps = qps
        self.burst = max(1, burst)
        self._tokens = float(self.burst)
        self._last_update = anyio.current_time()
        self._lock = anyio.Lock()

    async def __aenter__(self) -> None:
        await self.acquire()

    async def __aexit__(self, *_: Any) -> None:
        pass

    async def acquire(self) -> None:
        """Acquire a token, potentially sleeping until one is available."""
        while True:
            async with self._lock:
                now = anyio.current_time()
                elapsed = now - self._last_update
                self._tokens = min(self.burst, self._tokens + elapsed * self.qps)
                self._last_update = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                wait_time = (1.0 - self._tokens) / self.qps

            await anyio.sleep(wait_time)

    def wrap(
        self, fn: Callable[..., Awaitable[T]]
    ) -> Callable[..., Awaitable[T]]:
        """Decorator to rate-limit an async function."""

        async def wrapped(*args: Any, **kwargs: Any) -> T:
            async with self:
                return await fn(*args, **kwargs)

        return wrapped
