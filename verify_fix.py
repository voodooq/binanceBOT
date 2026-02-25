import asyncio
from decimal import Decimal
from dataclasses import dataclass
from src.exchanges.binance_client import BinanceClient, ClientConfig
from src.strategies.grid_strategy import GridStrategy
from src.models.bot import BotConfig, StrategyType

@dataclass
class MockRateLimiter:
    isInCircuitBreaker = False
    async def acquireWeight(self, w): pass
    async def acquireOrderSlot(self): pass

async def verify():
    print("--- Testing BinanceClient aliases ---")
    config = ClientConfig("key", "secret", True, "BTCUSDT")
    limiter = MockRateLimiter()
    client = BinanceClient(config, limiter)
    
    # Check if methods exist
    methods = [
        "getCurrentPrice", "get_current_price",
        "getKlines", "get_klines",
        "createMarketOrder", "create_market_order",
        "createOrder", "create_order",
        "futuresCreateOrder", "futures_create_order"
    ]
    for m in methods:
        if hasattr(client, m):
            print(f"✅ Method {m} exists")
        else:
            print(f"❌ Method {m} MISSING")

    print("\n--- Testing GridStrategy parameter safety ---")
    # Test with empty parameters
    # Note: Use dict for parameters to simulate real-world usage
    class SimpleBot:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.id = kwargs.get("id", 1)
            self.user_id = kwargs.get("user_id", 1)
            self.name = kwargs.get("name", "TestBot")
            self.symbol = kwargs.get("symbol", "BTCUSDT")
            self.strategy_type = kwargs.get("strategy_type", StrategyType.GRID)
            self.parameters = kwargs.get("parameters", {})
            self.is_testnet = kwargs.get("is_testnet", True)
            self.total_investment = kwargs.get("total_investment", Decimal("1000"))

    bot_config = SimpleBot(parameters={})
    
    try:
        strategy = GridStrategy(bot_config, client)
        print("✅ GridStrategy initialized with empty parameters")
        print(f"   LowerPrice: {strategy._settings.gridLowerPrice}")
    except Exception as e:
        print(f"❌ GridStrategy failed with empty parameters: {e}")

    # Test with malformed parameters
    bot_config.parameters = {"grid_lower_price": "abc", "grid_upper_price": " "}
    try:
        strategy = GridStrategy(bot_config, client)
        print("✅ GridStrategy initialized with malformed parameters")
        print(f"   LowerPrice (abc -> default 0): {strategy._settings.gridLowerPrice}")
        print(f"   UpperPrice (empty -> default 0): {strategy._settings.gridUpperPrice}")
    except Exception as e:
        print(f"❌ GridStrategy failed with malformed parameters: {e}")

if __name__ == "__main__":
    import traceback
    try:
        asyncio.run(verify())
    except Exception:
        traceback.print_exc()
