"""
异常处理与重试装饰器单元测试
"""
import asyncio

import pytest

from src.utils.error_handler import (
    BotError,
    ApiError,
    NetworkError,
    StrategyError,
    InsufficientBalanceError,
    InvalidOrderError,
    classifyError,
    retryOnError,
)


class TestExceptionHierarchy:
    """异常层级结构测试"""

    def test_apiErrorIsBotError(self) -> None:
        assert isinstance(ApiError(code=-1, message="test"), BotError)

    def test_networkErrorIsBotError(self) -> None:
        assert isinstance(NetworkError("test"), BotError)

    def test_strategyErrorIsBotError(self) -> None:
        assert isinstance(StrategyError("test"), BotError)

    def test_insufficientBalanceIsApiError(self) -> None:
        e = InsufficientBalanceError()
        assert isinstance(e, ApiError)
        assert e.code == -2010

    def test_invalidOrderIsApiError(self) -> None:
        e = InvalidOrderError()
        assert isinstance(e, ApiError)
        assert e.code == -1013


class TestClassifyError:
    """错误分类测试"""

    def test_retryableErrors(self) -> None:
        assert classifyError(-1021) == "retryable"  # 时间同步
        assert classifyError(-1003) == "retryable"  # 速率限制

    def test_skipErrors(self) -> None:
        assert classifyError(-2010) == "skip"  # 余额不足
        assert classifyError(-1013) == "skip"  # 参数无效

    def test_unknownError(self) -> None:
        assert classifyError(-9999) == "unknown"


class TestRetryOnError:
    """重试装饰器测试"""

    @pytest.mark.asyncio
    async def test_successNoRetry(self) -> None:
        """成功调用不应触发重试"""
        callCount = 0

        @retryOnError(maxRetries=3)
        async def successFunc() -> str:
            nonlocal callCount
            callCount += 1
            return "ok"

        result = await successFunc()
        assert result == "ok"
        assert callCount == 1

    @pytest.mark.asyncio
    async def test_retryOnRetryableError(self) -> None:
        """可重试错误应触发重试"""
        callCount = 0

        @retryOnError(maxRetries=3, baseDelay=0.01)
        async def failThenSucceed() -> str:
            nonlocal callCount
            callCount += 1
            if callCount < 3:
                raise ApiError(code=-1003, message="Rate limit exceeded")
            return "ok"

        result = await failThenSucceed()
        assert result == "ok"
        assert callCount == 3

    @pytest.mark.asyncio
    async def test_noRetryOnSkipError(self) -> None:
        """不可重试错误应直接抛出"""
        callCount = 0

        @retryOnError(maxRetries=3, baseDelay=0.01)
        async def insufficientBalance() -> str:
            nonlocal callCount
            callCount += 1
            raise InsufficientBalanceError("No funds")

        with pytest.raises(InsufficientBalanceError):
            await insufficientBalance()
        assert callCount == 1  # 只调用一次，不重试

    @pytest.mark.asyncio
    async def test_retryOnNetworkError(self) -> None:
        """网络异常应触发重试"""
        callCount = 0

        @retryOnError(maxRetries=2, baseDelay=0.01)
        async def networkFail() -> str:
            nonlocal callCount
            callCount += 1
            if callCount < 2:
                raise ConnectionError("Connection reset")
            return "ok"

        result = await networkFail()
        assert result == "ok"
        assert callCount == 2

    @pytest.mark.asyncio
    async def test_retryExhausted(self) -> None:
        """重试耗尽后应抛出最后一个异常"""

        @retryOnError(maxRetries=2, baseDelay=0.01)
        async def alwaysFail() -> str:
            raise ApiError(code=-1003, message="Rate limit")

        with pytest.raises(ApiError):
            await alwaysFail()

    @pytest.mark.asyncio
    async def test_timeSyncCallback(self) -> None:
        """时间同步错误应调用校准回调"""
        syncCalled = False

        async def mockSync() -> None:
            nonlocal syncCalled
            syncCalled = True

        callCount = 0

        @retryOnError(maxRetries=2, baseDelay=0.01, onTimeSyncError=mockSync)
        async def timeSyncFail() -> str:
            nonlocal callCount
            callCount += 1
            if callCount < 2:
                raise ApiError(code=-1021, message="Timestamp outside")
            return "ok"

        result = await timeSyncFail()
        assert result == "ok"
        assert syncCalled is True
