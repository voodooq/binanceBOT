import logging
import asyncio
from decimal import Decimal
from datetime import datetime
from typing import List, Dict, Any, Type

from src.models.bot import BotConfig, StrategyType
from src.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

class MockBinanceClient:
    """
    影子客户端 (Mock Client)。
    在回测过程中替代真实的 BinanceClient，模拟撮合与资产变动。
    """
    def __init__(self, initial_balance: Decimal = Decimal("10000")):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.positions = Decimal("0")
        self.avg_price = Decimal("0")
        self.trades = []
        self.current_price = Decimal("0")
        self._pricePrecision = 4
        self._quantityPrecision = 4
        # NOTE: GridStrategy.__init__ 会引用 client._rateLimiter，回测时不需要限速
        self._rateLimiter = None

    async def getCurrentPrice(self, symbol: str | None = None) -> Decimal:
        """获取当前模拟价格 (回测时由引擎注入)"""
        return self.current_price

    def _ensureConnected(self):
        return self

    async def createOrder(self, symbol: str, side: str, type: str, quantity: Decimal, price: Decimal = None, **kwargs):
        """模拟下单撮合"""
        exec_price = price if price else self.current_price
        notional = exec_price * quantity
        
        if side == "BUY":
            # 简化：不考虑手续费
            self.balance -= notional
            new_qty = self.positions + quantity
            if new_qty > 0:
                self.avg_price = (self.avg_price * self.positions + notional) / new_qty
            self.positions = new_qty
        else:
            self.balance += notional
            self.positions -= quantity
            
        self.trades.append({
            "side": side,
            "price": exec_price,
            "qty": quantity,
        })
        return {"orderId": f"mock_{len(self.trades)}", "status": "FILLED", "price": str(exec_price), "origQty": str(quantity)}

    async def futuresCreateOrder(self, **kwargs):
        """模拟合约下单"""
        return await self.createOrder(**kwargs)

    async def cancelOrder(self, **kwargs):
        return {"status": "CANCELED"}

    async def getFreeBalance(self, asset: str) -> Decimal:
        # 回测时简单返回可用余额
        return self.balance if asset != "BTC" else self.positions # 简化处理

    async def getFuturesPosition(self, symbol: str):
        return {"positionAmt": str(self.positions), "entryPrice": str(self.avg_price)}

    def formatPrice(self, price: Decimal) -> str:
        return str(round(price, self._pricePrecision))

    def formatQuantity(self, quantity: Decimal) -> str:
        return str(round(quantity, self._quantityPrecision))

    async def getKlines(self, symbol: str | None = None, interval: str = "1h", limit: int = 50, **kwargs):
        return []
    
    # 别名兼容
    get_klines = getKlines

class BacktestEngine:
    """
    轻量化回测引擎。
    支持所有继承自 BaseStrategy 的策略快速进行历史拟合。
    """
    
    def __init__(self, strategy_class: Type[BaseStrategy], bot_config: BotConfig):
        self.strategy_class = strategy_class
        self.bot_config = bot_config
        self.mock_client = MockBinanceClient(initial_balance=bot_config.total_investment)
        
    async def run(self, history_data: List[list]) -> Dict[str, Any]:
        """
        开始回测。
        @param history_data: 币安 K 线数组 [[time, open, high, low, close, vol...], ...]
        """
        # 1. 实例化策略并注入 Mock 客户端
        strategy = self.strategy_class(bot_config=self.bot_config, client=self.mock_client)
        
        # 2. 执行初始化
        await strategy.initialize()
        
        # 3. 逐 K 线驱动 (使用收盘价)
        start_equity = self.mock_client.balance
        max_equity = start_equity
        min_equity = start_equity
        max_drawdown = Decimal("0")
        
        logger.info(f"📊 开始回测: {len(history_data)} 条 K 线数据...")
        
        for kline in history_data:
            close_price = Decimal(str(kline[4]))
            self.mock_client.current_price = close_price
            
            # TODO: 模拟订单更新事件 (回测简版可忽略详情)
            
            # 触发策略逻辑
            await strategy.on_price_update(close_price)
            
            # 计算当前净值 (Equity)
            current_equity = self.mock_client.balance + (self.mock_client.positions * close_price)
            max_equity = max(max_equity, current_equity)
            drawdown = (max_equity - current_equity) / max_equity
            max_drawdown = max(max_drawdown, drawdown)
            
        end_equity = self.mock_client.balance + (self.mock_client.positions * self.mock_client.current_price)
        total_pnl = end_equity - start_equity
        roi = total_pnl / start_equity
        
        return {
            "symbol": self.bot_config.symbol,
            "start_balance": float(start_equity),
            "end_balance": float(end_equity),
            "total_pnl": float(total_pnl),
            "roi": float(roi * 100),
            "max_drawdown": float(max_drawdown * 100),
            "trade_count": len(self.mock_client.trades),
        }

backtest_engine = None # 这里不需要单例，每次回测都是独立实例
