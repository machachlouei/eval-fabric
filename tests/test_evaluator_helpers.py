import anyio
import pytest
from eval_fabric.errors import TransientError
from eval_fabric.evaluators import retry, RateLimiter

@pytest.mark.anyio
async def test_retry_success():
    attempts = 0

    @retry(max_attempts=3, min_wait=0.01)
    async def fast_retry():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise TransientError("failure")
        return "ok"

    result = await fast_retry()
    assert result == "ok"
    assert attempts == 2

@pytest.mark.anyio
async def test_retry_exhausted():
    attempts = 0

    @retry(max_attempts=3, min_wait=0.01)
    async def always_fails():
        nonlocal attempts
        attempts += 1
        raise TransientError("failure")

    with pytest.raises(TransientError):
        await always_fails()
    assert attempts == 3

@pytest.mark.anyio
async def test_rate_limiter_basic():
    # 10 QPS, burst 1. 5 calls should take ~0.4 seconds (0, 0.1, 0.2, 0.3, 0.4)
    limiter = RateLimiter(qps=10, burst=1)
    
    start = anyio.current_time()
    for _ in range(5):
        async with limiter:
            pass
    end = anyio.current_time()
    
    duration = end - start
    # Expect ~0.4s. Use a loose bound for CI.
    assert 0.35 <= duration <= 0.6

@pytest.mark.anyio
async def test_rate_limiter_burst():
    # 10 QPS, burst 5. 5 calls should be immediate.
    limiter = RateLimiter(qps=10, burst=5)
    
    start = anyio.current_time()
    for _ in range(5):
        async with limiter:
            pass
    end = anyio.current_time()
    
    duration = end - start
    assert duration < 0.05

@pytest.mark.anyio
async def test_rate_limiter_decorator():
    limiter = RateLimiter(qps=100)
    
    @limiter.wrap
    async def limited_fn():
        return "ok"
        
    assert await limited_fn() == "ok"
