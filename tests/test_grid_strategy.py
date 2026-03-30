"""
网格交易策略单元测试
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.strategies.grid_strategy as grid_strategy_module
from src.models.bot import BotConfig, BotStatus, StrategyType
from src.strategies.grid_strategy import GridOrder, GridSide, GridStrategy, OrderStatus


def _make_bot_config(**parameter_overrides) -> BotConfig:
    parameters = {
        "grid_lower_price": "60000",
        "grid_upper_price": "70000",
        "grid_count": 10,
        "grid_investment_per_grid": "10",
        "reserve_ratio": "0.1",
        "adaptive_mode": False,
        "analysis_interval": 15,
        "max_spread_percent": "0.001",
        "max_order_count": 50,
        "max_position_ratio": "0.95",
        "stop_loss_percent": "0.05",
        "take_profit_amount": "100",
        "martin_multiplier": "1.5",
        "max_martin_levels": 3,
        "trade_cooldown": 0,
        "stale_data_timeout": 300,
        "max_drawdown": "0.2",
    }
    parameters.update(parameter_overrides)

    bot = BotConfig(
        user_id=1,
        api_key_id=1,
        name="Test Grid Bot",
        symbol="BTCUSDT",
        strategy_type=StrategyType.GRID,
        status=BotStatus.IDLE,
        parameters=parameters,
        base_asset="BTC",
        quote_asset="USDT",
        total_investment=Decimal("1000"),
        total_pnl=Decimal("0"),
        is_testnet=True,
    )
    bot.id = 1
    return bot


def _make_client() -> MagicMock:
    client = MagicMock()
    client.is_mock = True

    async def _get_balance(asset: str = "USDT") -> Decimal:
        if asset == "USDT":
            return Decimal("1000")
        return Decimal("0")

    client.getFreeBalance = AsyncMock(side_effect=_get_balance)
    client.getBidAskSpread = AsyncMock(return_value=Decimal("0.0001"))
    client.createLimitOrder = AsyncMock(return_value={"orderId": 12345})
    client.cancelAllOrders = AsyncMock(return_value=[])
    client.createMarketOrder = AsyncMock(return_value={"orderId": 99999})
    client.getTotalPositionValue = AsyncMock(return_value=(Decimal("0"), Decimal("1000")))
    client.getCurrentPrice = AsyncMock(return_value=Decimal("65000"))
    client.getKlines = AsyncMock(return_value=[])
    client.get_klines = AsyncMock(return_value=[])
    client.nuke_all_orders = AsyncMock(return_value=None)
    client.getOpenOrders = AsyncMock(return_value=[])
    client.formatQuantity = MagicMock(side_effect=lambda qty: str(Decimal(str(qty))))
    client.minNotional = Decimal("10")
    client._minNotional = Decimal("10")

    mock_rate_limiter = MagicMock()
    mock_rate_limiter.isInCircuitBreaker = False
    mock_rate_limiter.isInWarningZone = False
    client._rateLimiter = mock_rate_limiter
    return client


def _make_strategy(**parameter_overrides) -> tuple[GridStrategy, MagicMock, MagicMock]:
    bot_config = _make_bot_config(**parameter_overrides)
    client = _make_client()

    notifier = MagicMock()
    notifier.notify = MagicMock()
    notifier.sendImmediate = AsyncMock(return_value=True)

    with patch("src.utils.notifier.Notifier", return_value=notifier):
        strategy = GridStrategy(bot_config=bot_config, client=client)

    strategy._notifier = notifier
    return strategy, client, notifier


@pytest.fixture(autouse=True)
def _patch_external_side_effects(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        grid_strategy_module.notification_service,
        "send_notification",
        MagicMock(),
    )
    monkeypatch.setattr(
        grid_strategy_module.redis_bus,
        "publish_trade_event",
        AsyncMock(),
    )


class TestGridGeneration:
    """网格生成测试"""

    def test_grid_price_count(self) -> None:
        strategy, _, _ = _make_strategy(grid_count=10)
        prices = strategy.generateGrid()
        assert len(prices) == 11

    def test_grid_price_range(self) -> None:
        strategy, _, _ = _make_strategy(
            grid_lower_price="1000",
            grid_upper_price="2000",
            grid_count=5,
        )
        prices = strategy.generateGrid()

        assert prices[0] == Decimal("1000")
        assert prices[-1] == Decimal("2000")

    def test_grid_step_size(self) -> None:
        strategy, _, _ = _make_strategy(
            grid_lower_price="100",
            grid_upper_price="200",
            grid_count=4,
        )
        prices = strategy.generateGrid()

        for i in range(1, len(prices)):
            assert prices[i] - prices[i - 1] == Decimal("25")

    def test_invalid_grid_count_raises(self) -> None:
        strategy, _, _ = _make_strategy(grid_count=0)
        with pytest.raises(ValueError, match="grid_count"):
            strategy.generateGrid()


class TestGridOrder:
    """GridOrder 序列化/反序列化测试"""

    def test_to_dict(self) -> None:
        order = GridOrder(
            gridIndex=3,
            price=Decimal("65000"),
            side=GridSide.BUY,
            quantity=Decimal("0.001"),
            orderId=12345,
            status=OrderStatus.PENDING,
        )
        data = order.toDict()
        assert data["gridIndex"] == 3
        assert data["price"] == "65000"
        assert data["side"] == "BUY"
        assert data["orderId"] == 12345

    def test_round_trip(self) -> None:
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


class TestRiskControls:
    """止损止盈逻辑测试"""

    @pytest.mark.asyncio
    async def test_stop_loss_triggered(self) -> None:
        strategy, _, notifier = _make_strategy(
            grid_lower_price="60000",
            stop_loss_percent="0.05",
        )
        strategy.generateGrid()
        strategy._running = True

        triggered = await strategy._checkStopLoss(Decimal("56999"))
        assert triggered is True
        assert strategy._running is False
        notifier.sendImmediate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_loss_not_triggered(self) -> None:
        strategy, _, _ = _make_strategy(
            grid_lower_price="60000",
            stop_loss_percent="0.05",
        )
        strategy.generateGrid()
        strategy._running = True

        triggered = await strategy._checkStopLoss(Decimal("58000"))
        assert triggered is False
        assert strategy._running is True

    @pytest.mark.asyncio
    async def test_take_profit_triggered(self) -> None:
        strategy, _, notifier = _make_strategy(take_profit_amount="100")
        strategy.generateGrid()
        strategy._running = True
        strategy._realizedProfit = Decimal("100")

        triggered = await strategy._checkTakeProfit()
        assert triggered is True
        assert strategy._running is False
        notifier.sendImmediate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_take_profit_not_triggered(self) -> None:
        strategy, _, _ = _make_strategy(take_profit_amount="100")
        strategy._running = True
        strategy._realizedProfit = Decimal("50")

        triggered = await strategy._checkTakeProfit()
        assert triggered is False


class TestOrderUpdates:
    """订单回调兼容性测试"""

    @pytest.mark.asyncio
    async def test_buy_fill_uses_backtest_fallback_fields(self) -> None:
        strategy, _, _ = _make_strategy()
        strategy.generateGrid()

        buy_order = GridOrder(
            gridIndex=2,
            price=Decimal("65000"),
            side=GridSide.BUY,
            quantity=Decimal("0.01"),
            orderId="mock_buy_1",
            status=OrderStatus.PENDING,
        )
        strategy._orders[buy_order.price] = buy_order
        strategy._placeSellOrder = AsyncMock()

        event = {
            "i": "mock_buy_1",
            "X": "FILLED",
            "S": "BUY",
            "p": "65100",
            "q": "0.01",
        }

        await strategy.on_order_update(event)

        strategy._placeSellOrder.assert_awaited_once_with(
            gridIndex=2,
            buyPrice=Decimal("65100"),
            quantity=Decimal("0.01"),
        )

    @pytest.mark.asyncio
    async def test_sell_fill_calculates_profit_with_backtest_fields(self) -> None:
        strategy, _, _ = _make_strategy()
        strategy.generateGrid()

        entry_price = Decimal("65000")
        sell_price = Decimal("66000")
        quantity = Decimal("0.01")

        sell_order = GridOrder(
            gridIndex=3,
            price=sell_price,
            side=GridSide.SELL,
            quantity=quantity,
            orderId="mock_sell_1",
            status=OrderStatus.PENDING,
            entryPrice=entry_price,
        )
        linked_buy_order = GridOrder(
            gridIndex=3,
            price=entry_price,
            side=GridSide.BUY,
            quantity=quantity,
            orderId="mock_buy_linked",
            status=OrderStatus.FILLED,
        )
        strategy._orders[sell_order.price] = sell_order
        strategy._orders[linked_buy_order.price] = linked_buy_order

        event = {
            "i": "mock_sell_1",
            "X": "FILLED",
            "S": "SELL",
            "p": "66000",
            "q": "0.01",
            "commission": "0.05",
            "commissionAsset": "USDT",
        }

        await strategy.on_order_update(event)

        assert strategy._realizedProfit == Decimal("10")
        assert sell_price not in strategy._orders
        assert entry_price not in strategy._orders
        grid_strategy_module.redis_bus.publish_trade_event.assert_awaited_once()