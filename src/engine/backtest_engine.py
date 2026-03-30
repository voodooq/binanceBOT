import logging
import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Dict, Any, Type

from src.models.bot import BotConfig, StrategyType
from src.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

class MockBinanceClient:
    """
    工业级影子客户端 (Fidelity Mock Client)。
    提供悲观撮合、滑点惩罚、资金费率扣减以及穿透成交逻辑。
    """
    def __init__(self, initial_balance: Any = Decimal("10000")):
        # 资产状态 (对齐用户建议的 Decimal 处理)
        self.balance = Decimal(str(initial_balance))        # USDT 余额
        self.positions = Decimal("0")                      # Base 资产持仓量
        self.avg_price = Decimal("0")                      # 持仓成本
        self.initial_balance = self.balance
        
        # 订单薄状态
        self.pending_orders = []                           # [{orderId, side, price, qty, status...}]
        self.trades = []                                   # 已成交历史记录
        
        # 撮合精度与限制
        self._pricePrecision = 4
        self._quantityPrecision = 4
        self._minNotional = Decimal("5")
        self._rateLimiter = type("MockRateLimiter", (), {"isInCircuitBreaker": False})()
        
        # 工业级回测保真度参数 (Fidelity Params)
        self.maker_fee = Decimal("0.0002")      # 挂单手续费 0.02% (假设 BNB 抵扣)
        self.taker_fee = Decimal("0.0005")      # 吃单手续费 0.05%
        self.slippage_rate = Decimal("0.0002")  # 市价单固定滑点惩罚 0.02%
        self.pierce_margin = Decimal("0.0001")  # 穿透撮合裕度 (需穿透 0.01% 才算成交)
        self.funding_rate = Decimal("0.0001")   # 假设平均资金费率 0.01%
        
        # 引擎状态
        self.current_price = Decimal("0")
        self.current_index = 0
        self.history_data = []
        self.last_funding_timestamp = 0
        self.is_mock = True

    # ==========================================
    # 核心撮合引擎 (由 BacktestEngine 驱动)
    # ==========================================
    async def push_kline(self, high_p: Decimal, low_p: Decimal, close_p: Decimal, kline_time: int):
        """
        注入 K 线数据，触发悲观撮合逻辑。
        由 BacktestEngine 在每根 K 线处理开始时调用。
        """
        self.current_price = close_p
        
        # 1. 资金费率结算 (模拟合约对冲，每 8 小时: UTC 0, 8, 16)
        self._process_funding_fee(kline_time)
        
        # 2. 遍历挂单进行悲观穿透撮合
        remaining_orders = []
        filled_any = False
        
        for order in self.pending_orders:
            order_price = order["price"]
            is_hit = False
            
            if order["side"] == "BUY":
                # 只有当 K 线最低价 穿透了 (挂单价 * (1 - margin)) 时，才算成交
                required_low = order_price * (Decimal("1") - self.pierce_margin)
                if low_p <= required_low:
                    is_hit = True
            
            elif order["side"] == "SELL":
                # 只有当 K 线最高价 穿透了 (挂单价 * (1 + margin)) 时，才算成交
                required_high = order_price * (Decimal("1") + self.pierce_margin)
                if high_p >= required_high:
                    is_hit = True
                    
            if is_hit:
                # 触发成交执行
                await self._execute_trade(
                    side=order["side"], 
                    quantity=order["origQty"], 
                    price=order_price, 
                    order_id=order["orderId"],
                    is_maker=True,
                    timestamp=kline_time
                )
                filled_any = True
                # 注意：此处不直接返回，因为策略需要接收 orderUpdate 事件，
                # 我们在 BacktestEngine 中通过 trades 长度变化或回调来补充事件。
            else:
                remaining_orders.append(order)
        
        self.pending_orders = remaining_orders
        return filled_any

    async def _execute_trade(self, side: str, quantity: Decimal, price: Decimal, order_id: str = None, is_maker: bool = True, timestamp: int = 0):
        """执行资产划转，应用手续费 (回测专用强化版)"""
        fee_rate = self.maker_fee if is_maker else self.taker_fee
        notional = price * quantity
        fee = notional * fee_rate
        
        if side == "BUY":
            # 严格余额校验：防止回测中产生“上帝视野”的透支开仓
            total_needed = notional + fee
            if self.balance < total_needed:
                # 如果余额不足，尝试缩减规模到可用余额的最大值 (等同于实际无法成交更多)
                logger.warning(f"🚨 [Mock] 余额不足 (%s < %s)，强制缩减成交规模", self.balance, total_needed)
                if self.balance > Decimal("5"): # 至少留 $5 
                    quantity = (self.balance - Decimal("1")) / (price * (1 + fee_rate))
                    if quantity <= 0: return {"status": "REJECTED", "msg": "Insufficient Balance"}
                    notional = price * quantity
                    fee = notional * fee_rate
                else:
                    return {"status": "REJECTED", "msg": "Insufficient Balance"}

            self.balance -= (notional + fee)
            new_qty = self.positions + quantity
            if new_qty > 0:
                self.avg_price = (self.avg_price * self.positions + notional) / new_qty
            self.positions = new_qty
        else:
            # 卖单需校验持仓
            if self.positions < quantity:
                logger.warning(f"🚨 [Mock] 持仓不足 (%s < %s)，强制缩减成交规模", self.positions, quantity)
                quantity = self.positions
                if quantity <= 0: return {"status": "REJECTED", "msg": "Insufficient Position"}
                notional = price * quantity
                fee = notional * fee_rate

            self.balance += (notional - fee)
            self.positions -= quantity
            
        trade_id = order_id or f"mock_t_{len(self.trades)}"
        resp = {
            "side": side,
            "price": price,
            "qty": quantity,
            "fee": fee,
            "status": "FILLED",
            "orderId": trade_id,
            "timestamp": timestamp,
            "is_maker": is_maker
        }
        self.trades.append(resp)
        # 增加回测专用可见日志，帮助诊断“成交次数”
        logger.info(f"💰 [BacktestMatch] {side} 成交: {quantity} @ {price}, 余额: {self.balance:.2f} USDT")
        return resp

    def _process_funding_fee(self, timestamp_ms: int):
        """模拟资金费率扣减 (UTC 0, 8, 16 时触发)"""
        if self.positions == 0:
            return
            
        # 简单判定逻辑：如果当前小时是结算小时，且上个时间戳不在同一个小时
        dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
        if dt.hour in [0, 8, 16] and dt.minute < 5: # 结算点前 5 分钟内判定一次
            if self.last_funding_timestamp == 0 or (timestamp_ms - self.last_funding_timestamp) > 3600000:
                notional_value = abs(self.positions) * self.current_price
                fee = notional_value * self.funding_rate
                self.balance -= fee
                self.last_funding_timestamp = timestamp_ms
                logger.info(f"💸 [Funding] 结算资金费率: {fee:.4f} USDT (基于头寸 {notional_value:.2f})")

    # ==========================================
    # 模拟 API 接口 (策略调用)
    # ==========================================
    async def createOrder(self, symbol: str | None = None, side: str = "BUY", type: str = "LIMIT", quantity: Any = 0, price: Any = None, **kwargs):
        if type == "MARKET":
            return await self.createMarketOrder(side=side, quantity=quantity, **kwargs)
        else:
            return await self.createLimitOrder(side=side, price=Decimal(str(price or "0")), quantity=Decimal(str(quantity)), **kwargs)

    async def createLimitOrder(self, side: str, price: Decimal, quantity: Decimal, **kwargs):
        order_id = f"mock_{len(self.trades) + len(self.pending_orders) + 1}"
        order = {
            "orderId": order_id,
            "side": side,
            "price": price,
            "origQty": quantity,
            "status": "NEW",
            "type": "LIMIT",
            "symbol": "BTCUSDT"
        }
        self.pending_orders.append(order)
        return {"orderId": order_id, "status": "NEW", "price": str(price), "origQty": str(quantity)}

    async def createMarketOrder(self, side: str, quantity: Decimal | None = None, quoteQuantity: Decimal | None = None, **kwargs):
        # 引入滑点惩罚
        if side == "BUY":
            exec_price = self.current_price * (Decimal("1") + self.slippage_rate)
            if quantity is None and quoteQuantity is not None:
                quantity = Decimal(str(quoteQuantity)) / exec_price
        else:
            exec_price = self.current_price * (Decimal("1") - self.slippage_rate)
            if quantity is None and quoteQuantity is not None:
                quantity = Decimal(str(quoteQuantity)) / self.current_price # 估算

        return await self._execute_trade(side, quantity, exec_price, is_maker=False)

    # 接口辅助方法 (对齐 BinanceClient)
    async def getCurrentPrice(self, *args, **kwargs) -> Decimal: return self.current_price
    async def getFreeBalance(self, asset: str) -> Decimal: return self.balance if asset == "USDT" else self.positions
    async def getTotalPositionValue(self, *args, **kwargs):
        pos_val = self.positions * self.current_price
        return pos_val, self.balance + pos_val
    async def getKlines(self, limit: int = 50, **kwargs):
        start = max(0, self.current_index - limit + 1)
        return self.history_data[start : self.current_index + 1]
    
    def formatPrice(self, price: Decimal) -> str: return str(round(price, self._pricePrecision))
    def formatQuantity(self, qty: Decimal) -> str: return str(round(qty, self._quantityPrecision))
    async def cancelAllOrders(self, **kwargs): self.pending_orders = []; return {"status": "CANCELED"}
    async def cancelOrder(self, orderId: str, **kwargs):
        self.pending_orders = [o for o in self.pending_orders if o["orderId"] != str(orderId)]
        return {"status": "CANCELED"}
    async def getBidAskSpread(self, **kwargs): return Decimal("0.0001")
    async def nuke_all_orders(self, **kwargs): return await self.cancelAllOrders()
    async def getOpenOrders(self, **kwargs): return [{"orderId": o["orderId"], "price": str(o["price"]), "side": o["side"]} for o in self.pending_orders]

    # 期货方法支持 (回测)
    async def getFuturesPosition(self, symbol: str) -> dict | None:
        """回测模式模拟持仓返回"""
        return {
            "symbol": symbol,
            "positionAmt": str(self.positions),
            "entryPrice": str(self.avg_price),
            "unRealizedProfit": "0",
            "leverage": "1"
        }

    async def futuresCreateOrder(self, **kwargs):
        """合约下单别名 (重定向到通用 createOrder)"""
        return await self.createOrder(**kwargs)

    # 别名定义
    get_klines = getKlines; get_current_price = getCurrentPrice; create_market_order = createMarketOrder; create_limit_order = createLimitOrder; create_order = createOrder; cancel_all_orders = cancelAllOrders; get_total_position_value = getTotalPositionValue; get_free_balance = getFreeBalance

class BacktestEngine:
    def __init__(self, strategy_class: Type[BaseStrategy], bot_config: BotConfig):
        self.strategy_class = strategy_class
        self.bot_config = bot_config
        self.mock_client = MockBinanceClient(initial_balance=bot_config.total_investment)
        
    async def run(self, history_data: List[list]) -> Dict[str, Any]:
        strategy = self.strategy_class(bot_config=self.bot_config, client=self.mock_client)
        
        if history_data:
            self.mock_client.current_price = Decimal(str(history_data[0][4]))
            self.mock_client.history_data = history_data

        await strategy.initialize()
        
        start_equity = self.mock_client.balance
        max_equity = start_equity
        max_drawdown = Decimal("0")
        
        # 强制热启动分析
        if self.bot_config.parameters.get("adaptive_mode") and len(history_data) >= 30:
            try:
                klinesInit = history_data[:50]
                adjustment = strategy._analyzer.analyze(klinesInit)
                strategy._currentAdjustment = adjustment
                logger.debug(f"🧠 回测初始分析完成: {adjustment.state.value}")
            except Exception as e:
                logger.warning(f"回测初始分析失败: {e}")

        for i, kline in enumerate(history_data):
            # [time, open, high, low, close, ...]
            timestamp = int(kline[0])
            close_price = Decimal(str(kline[4]))
            high_p = Decimal(str(kline[2]))
            low_p = Decimal(str(kline[3]))
            
            self.mock_client.current_index = i
            
            # 1. 推进模拟器：执行悲观撮合与资金费率结算
            # 记录成交前后的 trades 列表长度，用于触发策略回调
            prev_trade_count = len(self.mock_client.trades)
            await self.mock_client.push_kline(high_p, low_p, close_price, timestamp)
            
            # 2. 触发成交事件 (Order Update)
            new_trades = self.mock_client.trades[prev_trade_count:]
            for trade in new_trades:
                # 只有挂单成交才需要触发策略逻辑（买单成交挂卖单）
                if trade.get("is_maker"):
                    event = {
                        "e": "executionReport", "x": "TRADE", "X": "FILLED",
                        "S": trade["side"], "p": str(trade["price"]), "q": str(trade["qty"]),
                        "i": trade["orderId"], "s": self.bot_config.symbol
                    }
                    await strategy.on_order_update(event)

            # 3. 驱动策略价格更新主题
            await strategy.on_price_update(close_price)
            
            # 4. 驱动自适应分析步进
            if self.bot_config.parameters.get("adaptive_mode") and i >= 30 and i % 15 == 0:
                try:
                    posValue, totalValue = await self.mock_client.getTotalPositionValue()
                    posRatio = posValue / totalValue if totalValue > 0 else Decimal("0")
                    klinesSlice = await self.mock_client.getKlines(limit=50)
                    adjustment = strategy._analyzer.analyze(klinesSlice, positionRatio=posRatio)
                    strategy._currentAdjustment = adjustment
                except: pass

            # 5. 记录净值指标
            current_equity = self.mock_client.balance + (self.mock_client.positions * close_price)
            max_equity = max(max_equity, current_equity)
            drawdown = (max_equity - current_equity) / max_equity if max_equity > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)
            
        end_equity = self.mock_client.balance + (self.mock_client.positions * self.mock_client.current_price)
        total_pnl = end_equity - start_equity
        roi = total_pnl / start_equity
        
        return {
            "symbol": self.bot_config.symbol,
            "start_balance": float(start_equity),
            "end_balance": float(end_equity),
            "total_pnl": float(total_pnl),
            "total_fees": float(sum(Decimal(str(t.get("fee", 0))) for t in self.mock_client.trades)),
            "roi": float(roi * 100),
            "max_drawdown": float(max_drawdown * 100),
            "trade_count": len(self.mock_client.trades),
        }


backtest_engine = None # 这里不需要单例，每次回测都是独立实例
