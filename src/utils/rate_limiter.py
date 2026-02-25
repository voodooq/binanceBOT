"""
币安交易机器人 — 异步速率限制器

基于令牌桶算法，确保 API 请求频率严格在币安限制之内。
超出限制时自动等待令牌补充，而非直接拒绝请求。
"""
import asyncio
import time
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# NOTE: 双阶段权重保护阈值
WARNING_THRESHOLD = 0.80    # 80% 以上进入警戒区，非紧急操作 sleep 500ms
CIRCUIT_BREAKER_THRESHOLD = 0.95  # 95% 以上进入熔断区，停止非卖单请求


@dataclass
class TokenBucket:
    """
    令牌桶：以固定速率补充令牌，消耗时若不足则等待。

    @param capacity 桶容量（最大令牌数）
    @param refillRate 每秒补充的令牌数
    """

    capacity: float
    refillRate: float
    _tokens: float = field(init=False)
    _lastRefill: float = field(init=False)
    _lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._lastRefill = time.monotonic()

    def _refill(self) -> None:
        """根据距上次补充的时间差，按速率补充令牌"""
        now = time.monotonic()
        elapsed = now - self._lastRefill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refillRate)
        self._lastRefill = now

    async def acquire(self, cost: float = 1.0) -> None:
        """
        消耗指定数量的令牌。如果桶内令牌不足，自动等待到足够为止。

        @param cost 本次请求消耗的令牌数（对应 API 权重）
        """
        async with self._lock:
            self._refill()

            if self._tokens >= cost:
                self._tokens -= cost
                return

            # NOTE: 计算需要等待的时间，让令牌补充到足够
            deficit = cost - self._tokens
            waitTime = deficit / self.refillRate
            logger.warning(
                "⏳ 速率限制：令牌不足 (需要 %.1f, 剩余 %.1f)，等待 %.2f 秒",
                cost, self._tokens, waitTime,
            )
            await asyncio.sleep(waitTime)

            self._refill()
            self._tokens -= cost

    @property
    def currentUsageRatio(self) -> float:
        """返回当前令牌桶使用率 (0.0 ~ 1.0)，1.0 表示已全部消耗"""
        self._refill()
        return 1.0 - (self._tokens / self.capacity) if self.capacity > 0 else 0.0

    def calibrate(self, usedWeight: int) -> None:
        """
        根据响应头中的实际消耗值校准桶内令牌。
        币安在响应头 X-MBX-USED-WEIGHT-1M 中返回当前分钟已用权重。

        @param usedWeight 当前分钟已消耗的权重值
        """
        remaining = self.capacity - usedWeight
        if remaining >= 0:
            self._tokens = min(self._tokens, remaining)
            logger.debug("🔄 校准令牌桶: 已用权重=%d, 剩余令牌=%.1f", usedWeight, self._tokens)


class RateLimiter:
    """
    币安 API 速率限制器。

    维护两个令牌桶，分别控制：
    1. 请求权重：每分钟最多 6,000（保守使用 5,000）
    2. 订单速率：每 10 秒最多 100 单（保守使用 80）
    """

    # NOTE: 使用保守值，给其他可能的 API 消耗留出缓冲
    DEFAULT_WEIGHT_CAPACITY = 5000   # 官方限制 6,000/分钟
    DEFAULT_ORDER_CAPACITY = 80      # 官方限制 100/10秒

    def __init__(
        self,
        weightCapacity: int = DEFAULT_WEIGHT_CAPACITY,
        orderCapacity: int = DEFAULT_ORDER_CAPACITY,
    ) -> None:
        # 请求权重桶：容量/分钟 → 每秒补充 capacity/60
        self.weightBucket = TokenBucket(
            capacity=weightCapacity,
            refillRate=weightCapacity / 60.0,
        )
        # 订单速率桶：容量/10秒 → 每秒补充 capacity/10
        self.orderBucket = TokenBucket(
            capacity=orderCapacity,
            refillRate=orderCapacity / 10.0,
        )

        # [P3] 异常触发的硬熔断：记录熔断结束的时间戳 (0 表示正常)
        self._hardCircuitBreakerUntil: float = 0.0

        logger.info(
            "🚦 速率限制器初始化: 权重=%d/分钟, 订单=%d/10秒",
            weightCapacity, orderCapacity,
        )

    def triggerHardCircuitBreaker(self, duration: int = 60):
        """
        触发硬熔断，由外部 (如 BinanceClient 捕获 429) 调用。
        @param duration 熔断持续时间 (秒)，默认 60 秒
        """
        self._hardCircuitBreakerUntil = time.time() + duration
        logger.critical("🚨 [RateLimiter] 硬熔断已激活! 预计在 %d 秒后尝试恢复", duration)

    @property
    def isHardCircuitBroken(self) -> bool:
        """检查当前是否处于硬熔断期内"""
        if self._hardCircuitBreakerUntil == 0:
            return False
        
        if time.time() < self._hardCircuitBreakerUntil:
            return True
        
        # 熔断时间已过，自动恢复
        self._hardCircuitBreakerUntil = 0
        logger.info("🟢 [RateLimiter] 硬熔断冷却结束，系统尝试恢复运行")
        return False

    async def acquireWeight(self, weight: int = 1) -> None:
        """
        请求消耗 API 权重。

        @param weight 该请求的权重值（不同 endpoint 权重不同）
        """
        if self.isHardCircuitBroken:
            # 如果处于硬熔断期，直接抛出频率限制异常，强制外部重试器检测到并进行长等待
            raise ApiError(code=-1003, message="Rate limit exceeded (Hard Circuit Breaker active)")
            
        await self.weightBucket.acquire(weight)

    async def acquireOrderSlot(self) -> None:
        """请求消耗一个订单操作名额"""
        await self.orderBucket.acquire(1)

    def calibrateWeight(self, usedWeight: int) -> None:
        """
        用响应头的实际消耗值校准权重桶。

        @param usedWeight 响应头 X-MBX-USED-WEIGHT-1M 的值
        """
        self.weightBucket.calibrate(usedWeight)

    def getUsageRatio(self) -> float:
        """
        获取当前权重桶使用率。

        @returns 0.0 ~ 1.0 的使用率，1.0 表示已满载
        """
        return self.weightBucket.currentUsageRatio

    @property
    def isInWarningZone(self) -> bool:
        """权重使用率 >= 80%，进入警戒区"""
        ratio = self.getUsageRatio()
        return ratio >= WARNING_THRESHOLD

    @property
    def isInCircuitBreaker(self) -> bool:
        """权重使用率 >= 95%，进入熔断区，停止所有非卖单/非止损请求"""
        ratio = self.getUsageRatio()
        return ratio >= CIRCUIT_BREAKER_THRESHOLD

    async def acquireWeightWithProtection(self, weight: int = 1) -> str:
        """
        带双阶段保护的权重获取。

        @param weight 权重值
        @returns 状态字符串: 'ok' / 'warning' / 'circuit_breaker'
        """
        ratio = self.getUsageRatio()

        if ratio >= CIRCUIT_BREAKER_THRESHOLD:
            logger.critical(
                "\ud83d\udea8 权重熔断! 使用率 %.1f%% >= %.0f%%，拒绝非紧急请求",
                ratio * 100, CIRCUIT_BREAKER_THRESHOLD * 100,
            )
            return "circuit_breaker"

        if ratio >= WARNING_THRESHOLD:
            logger.warning(
                "\u26a0\ufe0f 权重警戒! 使用率 %.1f%% >= %.0f%%，进入冷静模式 (+500ms)",
                ratio * 100, WARNING_THRESHOLD * 100,
            )
            await asyncio.sleep(0.5)

        await self.weightBucket.acquire(weight)
        return "warning" if ratio >= WARNING_THRESHOLD else "ok"
