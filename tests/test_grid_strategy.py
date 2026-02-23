"""
网格交易策略单元测试
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.binance_config import Settings
from src.strategies.grid_strategy import GridStrategy, GridOrder, GridSide, OrderStatus


def _makeSettings(**overrides) -> Settings:
    """创建测试用 Settings 实例"""
    defaults = {
        "apiKey": "test_key_1234",
        "apiSecret": "test_secret_1234",
        "useTestnet": True,
        "tradingSymbol": "BTCUSDT",
        "gridUpperPrice": Decimal("70000"),
        "gridLowerPrice": Decimal("60000"),
        "gridCount": 10,
        "gridInvestmentPerGrid": Decimal("10"),
        "stopLossPercent": Decimal("0.05"),
        "takeProfitAmount": Decimal("100"),
        "maxSpreadPercent": Decimal("0.001"),
        "reserveRatio": Decimal("0.1"),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _makeStrategy(settings: Settings | None = None) -> GridStrategy:
    """创建带 Mock 依赖的策略实例"""
    if settings is None:
        settings = _makeSettings()

    mockClient = AsyncMock()
    mockClient.getFreeBalance = AsyncMock(return_value=Decimal("1000"))
    mockClient.getBidAskSpread = AsyncMock(return_value=Decimal("0.0001"))
    mockClient.createLimitOrder = AsyncMock(return_value={"orderId": 12345})
    mockClient.cancelAllOrders = AsyncMock(return_value=[])
    mockClient.createMarketOrder = AsyncMock(return_value={"orderId": 99999})

    # V3.0: GridStrategy 通过 client._rateLimiter 获取引用
    mockRateLimiter = MagicMock()
    mockRateLimiter.isInCircuitBreaker = False
    mockRateLimiter.isInWarningZone = False
    mockClient._rateLimiter = mockRateLimiter

    mockNotifier = MagicMock()
    mockNotifier.notify = MagicMock()
    mockNotifier.sendImmediate = AsyncMock(return_value=True)

    return GridStrategy(
        settings=settings,
        client=mockClient,
        notifier=mockNotifier,
    )


class TestGridGeneration:
    """网格生成测试"""

    def test_gridPriceCount(self) -> None:
        """n 格应生成 n+1 个价位"""
        strategy = _makeStrategy(_makeSettings(gridCount=10))
        prices = strategy.generateGrid()
        assert len(prices) == 11

    def test_gridPriceRange(self) -> None:
        """最低价 = gridLowerPrice, 最高价 = gridUpperPrice"""
        settings = _makeSettings(
            gridLowerPrice=Decimal("1000"),
            gridUpperPrice=Decimal("2000"),
            gridCount=5,
        )
        strategy = _makeStrategy(settings)
        prices = strategy.generateGrid()

        assert prices[0] == Decimal("1000")
        assert prices[-1] == Decimal("2000")

    def test_gridStepSize(self) -> None:
        """网格应等差分布"""
        settings = _makeSettings(
            gridLowerPrice=Decimal("100"),
            gridUpperPrice=Decimal("200"),
            gridCount=4,
        )
        strategy = _makeStrategy(settings)
        prices = strategy.generateGrid()

        # 步长应为 25
        for i in range(1, len(prices)):
            assert prices[i] - prices[i - 1] == Decimal("25")


class TestGridOrder:
    """GridOrder 序列化/反序列化测试"""

    def test_toDict(self) -> None:
        order = GridOrder(
            gridIndex=3,
            price=Decimal("65000"),
            side=GridSide.BUY,
            quantity=Decimal("0.001"),
            orderId=12345,
            status=OrderStatus.PENDING,
        )
        d = order.toDict()
        assert d["gridIndex"] == 3
        assert d["price"] == "65000"
        assert d["side"] == "BUY"
        assert d["orderId"] == 12345

    def test_roundTrip(self) -> None:
        """序列化后反序列化应得到等价对象"""
        original = GridOrder(
            gridIndex=5,
            price=Decimal("67500.50"),
            side=GridSide.SELL,
            quantity=Decimal("0.00015"),
            orderId=67890,
            status=OrderStatus.FILLED,
        )
        restored = GridOrder.fromDict(original.toDict())
        assert restored.gridIndex == original.gridIndex
        assert restored.price == original.price
        assert restored.side == original.side
        assert restored.quantity == original.quantity
        assert restored.orderId == original.orderId
        assert restored.status == original.status


class TestStopLoss:
    """止损逻辑测试"""

    @pytest.mark.asyncio
    async def test_stopLossTriggered(self) -> None:
        """价格跌破止损线应触发紧急退出"""
        settings = _makeSettings(
            gridLowerPrice=Decimal("60000"),
            stopLossPercent=Decimal("0.05"),
        )
        strategy = _makeStrategy(settings)
        strategy.generateGrid()
        strategy._running = True

        # 止损线 = 60000 * (1 - 0.05) = 57000
        triggered = await strategy._checkStopLoss(Decimal("56999"))
        assert triggered is True
        assert strategy._running is False

    @pytest.mark.asyncio
    async def test_stopLossNotTriggered(self) -> None:
        """价格在止损线之上不应触发"""
        settings = _makeSettings(
            gridLowerPrice=Decimal("60000"),
            stopLossPercent=Decimal("0.05"),
        )
        strategy = _makeStrategy(settings)
        strategy.generateGrid()
        strategy._running = True

        triggered = await strategy._checkStopLoss(Decimal("58000"))
        assert triggered is False
        assert strategy._running is True


class TestTakeProfit:
    """止盈逻辑测试"""

    @pytest.mark.asyncio
    async def test_takeProfitTriggered(self) -> None:
        """累计利润达到目标应触发止盈"""
        settings = _makeSettings(takeProfitAmount=Decimal("100"))
        strategy = _makeStrategy(settings)
        strategy.generateGrid()
        strategy._running = True
        strategy._realizedProfit = Decimal("100")

        triggered = await strategy._checkTakeProfit()
        assert triggered is True

    @pytest.mark.asyncio
    async def test_takeProfitNotTriggered(self) -> None:
        """累计利润未达标不应触发"""
        settings = _makeSettings(takeProfitAmount=Decimal("100"))
        strategy = _makeStrategy(settings)
        strategy._running = True
        strategy._realizedProfit = Decimal("50")

        triggered = await strategy._checkTakeProfit()
        assert triggered is False
