"""
币安交易机器人 — 异常处理与自动重试模块

定义分层异常体系，并提供装饰器实现针对不同错误码的智能重试。
"""
import asyncio
import logging
import functools
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ==================================================
# 自定义异常层级
# ==================================================

class BotError(Exception):
    """机器人基础异常，所有自定义异常的父类"""
    pass


class ApiError(BotError):
    """
    币安 API 返回的业务错误。
    携带币安错误码和消息，便于精确处理。
    """

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"Binance API Error [{code}]: {message}")


class NetworkError(BotError):
    """网络层异常（超时、断连等）"""
    pass


class StrategyError(BotError):
    """策略逻辑异常（风控触发、参数无效等）"""
    pass


class InsufficientBalanceError(ApiError):
    """余额不足 (-2010)"""

    def __init__(self, message: str = "Insufficient balance") -> None:
        super().__init__(code=-2010, message=message)


class InvalidOrderError(ApiError):
    """订单参数无效 (-1013)"""

    def __init__(self, message: str = "Invalid order parameters") -> None:
        super().__init__(code=-1013, message=message)


# ==================================================
# 错误码 → 处理策略映射
# ==================================================

# NOTE: 可重试的错误码及其处理说明
RETRYABLE_ERRORS = {
    -1021: "时间同步错误 — 需调用 syncServerTime 后重试",
    -1003: "超出速率限制 — 需等待后重试",
    -1015: "撤单过于频繁 — 需等待后重试",
}

# NOTE: 不可重试的错误码，应记录日志并跳过
NON_RETRYABLE_ERRORS = {
    -2010: "余额不足 — 跳过本次操作",
    -1013: "订单价格/数量无效 — 检查参数精度",
    -1121: "订单价格/数量超出范围 — 检查交易对限制",
    -2015: "API Key 权限不足或 IP 未在白名单 — 检查 API 配置",
}


def classifyError(code: int) -> str:
    """
    根据错误码分类，返回处理建议。

    @param code 币安 API 错误码
    @returns 分类标签: 'retryable' / 'skip' / 'unknown'
    """
    if code in RETRYABLE_ERRORS:
        return "retryable"
    if code in NON_RETRYABLE_ERRORS:
        return "skip"
    return "unknown"


# ==================================================
# 自动重试装饰器
# ==================================================

def retryOnError(
    maxRetries: int = 3,
    baseDelay: float = 1.0,
    maxDelay: float = 60.0,
    onTimeSyncError: Callable | None = None,
) -> Callable[[F], F]:
    """
    异步函数重试装饰器。

    针对不同错误码采取不同策略：
    - 可重试错误：指数退避重试
    - 时间同步错误：先调用校准回调再重试
    - 不可重试错误：直接记录日志并抛出
    - 网络异常：指数退避重试

    @param maxRetries 最大重试次数
    @param baseDelay 初始等待时间（秒）
    @param maxDelay 最大等待时间（秒）
    @param onTimeSyncError 时间同步错误时的校准回调（如 syncServerTime）
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            lastException: Exception | None = None

            for attempt in range(1, maxRetries + 1):
                try:
                    return await func(*args, **kwargs)

                except ApiError as e:
                    lastException = e
                    errorType = classifyError(e.code)

                    if errorType == "skip":
                        # 不可重试错误，记录日志后直接抛出
                        logger.error(
                            "❌ 不可重试错误 [%d]: %s | 函数: %s",
                            e.code, e.message, func.__name__,
                        )
                        raise

                    if errorType == "retryable":
                        delay = min(baseDelay * (2 ** (attempt - 1)), maxDelay)

                        # 时间同步错误的特殊处理
                        if e.code == -1021 and onTimeSyncError:
                            logger.warning(
                                "🕐 时间同步错误，执行校准后重试 (第 %d/%d 次)",
                                attempt, maxRetries,
                            )
                            try:
                                await onTimeSyncError()
                            except Exception as syncErr:
                                logger.error("时间校准失败: %s", syncErr)
                        else:
                            logger.warning(
                                "⚠️ API 错误 [%d]: %s | 等待 %.1f 秒后重试 (第 %d/%d 次)",
                                e.code, e.message, delay, attempt, maxRetries,
                            )

                        await asyncio.sleep(delay)
                        continue

                    # 未知错误码
                    logger.error(
                        "❓ 未知 API 错误 [%d]: %s | 函数: %s (第 %d/%d 次)",
                        e.code, e.message, func.__name__, attempt, maxRetries,
                    )
                    if attempt < maxRetries:
                        await asyncio.sleep(baseDelay)
                        continue
                    raise

                except (
                    asyncio.TimeoutError,
                    ConnectionError,
                    OSError,
                ) as e:
                    lastException = e
                    delay = min(baseDelay * (2 ** (attempt - 1)), maxDelay)
                    logger.warning(
                        "🌐 网络异常: %s | 等待 %.1f 秒后重试 (第 %d/%d 次)",
                        type(e).__name__, delay, attempt, maxRetries,
                    )
                    await asyncio.sleep(delay)
                    continue

            # 重试耗尽
            logger.error(
                "💀 重试耗尽 (%d 次) | 函数: %s | 最后异常: %s",
                maxRetries, func.__name__, lastException,
            )
            if lastException:
                raise lastException
            raise BotError(f"重试耗尽: {func.__name__}")

        return wrapper  # type: ignore

    return decorator
