"""
速率限制器单元测试
"""
import asyncio
import time

import pytest

from src.utils.error_handler import ApiError
from src.utils.rate_limiter import RateLimiter, TokenBucket, get_shared_rate_limiter


class TestTokenBucket:
    """令牌桶单元测试"""

    @pytest.mark.asyncio
    async def test_initial_tokens(self) -> None:
        """初始化后桶应满令牌"""
        bucket = TokenBucket(capacity=100, refillRate=10)
        await bucket.acquire(100)

    @pytest.mark.asyncio
    async def test_consume_tokens(self) -> None:
        """消耗令牌后桶内余量应减少"""
        bucket = TokenBucket(capacity=10, refillRate=1)
        await bucket.acquire(5)
        await bucket.acquire(5)

    @pytest.mark.asyncio
    async def test_wait_when_empty(self) -> None:
        """桶空时应等待令牌补充"""
        bucket = TokenBucket(capacity=1, refillRate=100)
        await bucket.acquire(1)

        start = time.monotonic()
        await bucket.acquire(1)
        elapsed = time.monotonic() - start

        assert elapsed < 0.5

    @pytest.mark.asyncio
    async def test_calibrate(self) -> None:
        """校准应调整桶内令牌"""
        bucket = TokenBucket(capacity=100, refillRate=10)
        bucket.calibrate(80)
        await bucket.acquire(20)

    @pytest.mark.asyncio
    async def test_refill_does_not_exceed_capacity(self) -> None:
        """补充不应超过桶容量"""
        bucket = TokenBucket(capacity=10, refillRate=1000)
        await bucket.acquire(10)
        await asyncio.sleep(0.1)
        await bucket.acquire(10)

    def test_invalid_capacity_raises(self) -> None:
        with pytest.raises(ValueError, match="capacity"):
            TokenBucket(capacity=0, refillRate=1)

    def test_invalid_refill_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="refillRate"):
            TokenBucket(capacity=1, refillRate=0)


class TestRateLimiter:
    """速率限制器集成测试"""

    @pytest.mark.asyncio
    async def test_acquire_weight(self) -> None:
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        for _ in range(10):
            await limiter.acquireWeight(5)

    @pytest.mark.asyncio
    async def test_acquire_order_slot(self) -> None:
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        for _ in range(10):
            await limiter.acquireOrderSlot()

    @pytest.mark.asyncio
    async def test_calibrate_weight(self) -> None:
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        limiter.calibrateWeight(50)

    @pytest.mark.asyncio
    async def test_get_usage_ratio(self) -> None:
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        assert limiter.getUsageRatio() < 0.1

        await limiter.acquireWeight(80)
        ratio = limiter.getUsageRatio()
        assert 0.7 < ratio < 0.9

    @pytest.mark.asyncio
    async def test_is_in_warning_zone(self) -> None:
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        assert limiter.isInWarningZone is False

        await limiter.acquireWeight(82)
        assert limiter.isInWarningZone is True

    @pytest.mark.asyncio
    async def test_is_in_circuit_breaker(self) -> None:
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        assert limiter.isInCircuitBreaker is False

        await limiter.acquireWeight(96)
        assert limiter.isInCircuitBreaker is True

    @pytest.mark.asyncio
    async def test_hard_circuit_breaker_blocks_acquire_weight(self) -> None:
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        limiter.triggerHardCircuitBreaker(duration=60)

        assert limiter.isHardCircuitBroken is True
        assert limiter.isInCircuitBreaker is True

        with pytest.raises(ApiError) as exc_info:
            await limiter.acquireWeight(1)

        assert exc_info.value.code == -1003

    @pytest.mark.asyncio
    async def test_acquire_weight_with_protection_returns_circuit_breaker(self) -> None:
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        limiter.triggerHardCircuitBreaker(duration=60)

        status = await limiter.acquireWeightWithProtection(1)
        assert status == "circuit_breaker"


class TestSharedRateLimiter:
    """共享限流器测试"""

    def test_same_scope_returns_same_instance(self) -> None:
        limiter_a = get_shared_rate_limiter("scope-a")
        limiter_b = get_shared_rate_limiter("scope-a")
        assert limiter_a is limiter_b

    def test_different_scope_returns_different_instance(self) -> None:
        limiter_a = get_shared_rate_limiter("scope-a-1")
        limiter_b = get_shared_rate_limiter("scope-b-1")
        assert limiter_a is not limiter_b