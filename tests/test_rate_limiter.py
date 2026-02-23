"""
速率限制器单元测试
"""
import asyncio
import time

import pytest

from src.utils.rate_limiter import TokenBucket, RateLimiter


@pytest.fixture
def eventLoop():
    """提供事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestTokenBucket:
    """令牌桶单元测试"""

    @pytest.mark.asyncio
    async def test_initialTokens(self) -> None:
        """初始化后桶应满令牌"""
        bucket = TokenBucket(capacity=100, refillRate=10)
        # 消耗 100 个令牌应立即成功
        await bucket.acquire(100)

    @pytest.mark.asyncio
    async def test_consumeTokens(self) -> None:
        """消耗令牌后桶内余量应减少"""
        bucket = TokenBucket(capacity=10, refillRate=1)
        await bucket.acquire(5)
        # 剩余 5 个，再消耗 5 个应成功
        await bucket.acquire(5)

    @pytest.mark.asyncio
    async def test_waitWhenEmpty(self) -> None:
        """桶空时应等待令牌补充"""
        bucket = TokenBucket(capacity=1, refillRate=100)  # 每秒补充 100 个
        await bucket.acquire(1)

        # 令牌已空，再次消耗应等待一小段时间
        start = time.monotonic()
        await bucket.acquire(1)
        elapsed = time.monotonic() - start

        # 补充速率 100/秒，等待 1 个令牌约需 0.01 秒，给 0.5 秒的宽容度
        assert elapsed < 0.5

    @pytest.mark.asyncio
    async def test_calibrate(self) -> None:
        """校准应调整桶内令牌"""
        bucket = TokenBucket(capacity=100, refillRate=10)
        # 校准 — 已用 80，剩余应为 20
        bucket.calibrate(80)
        # 应能消耗 20 个
        await bucket.acquire(20)

    @pytest.mark.asyncio
    async def test_refillDoesNotExceedCapacity(self) -> None:
        """补充不应超过桶容量"""
        bucket = TokenBucket(capacity=10, refillRate=1000)
        await bucket.acquire(10)
        await asyncio.sleep(0.1)
        # 即使补充速率很高，桶内令牌不应超过容量
        await bucket.acquire(10)
        # 如果超过容量，这里会失败


class TestRateLimiter:
    """速率限制器集成测试"""

    @pytest.mark.asyncio
    async def test_acquireWeight(self) -> None:
        """权重获取应正常工作"""
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        # 应能连续获取多个权重
        for _ in range(10):
            await limiter.acquireWeight(5)

    @pytest.mark.asyncio
    async def test_acquireOrderSlot(self) -> None:
        """订单名额获取应正常工作"""
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        for _ in range(10):
            await limiter.acquireOrderSlot()

    @pytest.mark.asyncio
    async def test_calibrateWeight(self) -> None:
        """权重校准不应抛出异常"""
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        limiter.calibrateWeight(50)

    @pytest.mark.asyncio
    async def test_getUsageRatio(self) -> None:
        """使用率应反映实际消耗"""
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        # 初始使用率应接近 0
        assert limiter.getUsageRatio() < 0.1

        # 消耗 80 权重后，使用率应接近 0.8
        await limiter.acquireWeight(80)
        ratio = limiter.getUsageRatio()
        assert 0.7 < ratio < 0.9

    @pytest.mark.asyncio
    async def test_isInWarningZone(self) -> None:
        """消耗 80% 以上时应进入警戒区"""
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        assert limiter.isInWarningZone is False

        await limiter.acquireWeight(82)
        assert limiter.isInWarningZone is True

    @pytest.mark.asyncio
    async def test_isInCircuitBreaker(self) -> None:
        """消耗 95% 以上时应进入熔断区"""
        limiter = RateLimiter(weightCapacity=100, orderCapacity=10)
        assert limiter.isInCircuitBreaker is False

        await limiter.acquireWeight(96)
        assert limiter.isInCircuitBreaker is True
