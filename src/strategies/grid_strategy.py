"""
币安交易机器人 — 网格交易策略

实现等差网格交易逻辑：在价格区间内均匀分布网格线，
价格下穿网格线时买入，买入成交后在上一级网格挂卖单形成配对利润循环。
集成止损/止盈、价差控制和资金预留等风控机制。
"""
import asyncio
import json
import logging
import time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from dataclasses import dataclass

from src.exchanges.binance_client import BinanceClient
from src.utils.notifier import Notifier
from src.strategies.market_analyzer import MarketAnalyzer, MarketState, GridAdjustment
from src.strategies.base_strategy import BaseStrategy
from src.models.bot import BotConfig

logger = logging.getLogger(__name__)

# 状态持久化文件路径 (V3.0 中可以迁移至数据库，暂不阻断旧逻辑)
STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"

@dataclass
class GridSettingsProxy:
    """临时将 JSON 参数转为强类型风格的小配置类，接平 V2 的历史代码"""
    gridLowerPrice: Decimal
    gridUpperPrice: Decimal
    gridCount: int
    gridInvestmentPerGrid: Decimal
    reserveRatio: Decimal
    adaptiveMode: bool
    analysisInterval: int
    maxSpreadPercent: Decimal
    maxOrderCount: int
    maxPositionRatio: Decimal
    stopLossPercent: Decimal
    takeProfitAmount: Decimal
    martinMultiplier: Decimal
    maxMartinLevels: int
    tradingSymbol: str # 用来兼容日志
    tradeCooldown: float = 5.0
    staleDataTimeout: float = 300.0
    maxDrawdown: Decimal = Decimal("0.2") # 最大回撤阈值
    decayMinMultiplier: Decimal = Decimal("0.2")


class GridSide(str, Enum):
    """网格方向"""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """挂单状态"""
    PENDING = "PENDING"     # 已挂单，等待成交
    FILLED = "FILLED"       # 已成交
    CANCELLED = "CANCELLED" # 已撤销


class GridOrder:
    """
    网格订单数据结构。
    追踪每个网格价位上的订单状态和配对关系。
    """

    def __init__(
        self,
        gridIndex: int,
        price: Decimal,
        side: GridSide,
        quantity: Decimal = Decimal("0"),
        orderId: int | None = None,
        status: OrderStatus = OrderStatus.PENDING,
        entryPrice: Decimal | None = None,  # V2.3: 记录买入成本（对于卖单）
    ) -> None:
        self.gridIndex = gridIndex
        self.price = price
        self.side = side
        self.quantity = quantity
        self.orderId = orderId
        self.status = status
        self.entryPrice = entryPrice

    def toDict(self) -> dict[str, Any]:
        """序列化为字典，用于状态持久化"""
        return {
            "gridIndex": self.gridIndex,
            "price": str(self.price),
            "side": self.side.value,
            "quantity": str(self.quantity),
            "orderId": self.orderId,
            "status": self.status.value,
            "entryPrice": str(self.entryPrice) if self.entryPrice else None,
        }

    @classmethod
    def fromDict(cls, data: dict[str, Any]) -> "GridOrder":
        """从字典反序列化"""
        return cls(
            gridIndex=data["gridIndex"],
            price=Decimal(data["price"]),
            side=GridSide(data["side"]),
            quantity=Decimal(data["quantity"]),
            orderId=data.get("orderId"),
            status=OrderStatus(data["status"]),
            entryPrice=Decimal(data["entryPrice"]) if data.get("entryPrice") else None,
        )


class GridStrategy(BaseStrategy):
    """
    网格交易策略引擎。

    核心流程：
    1. 根据配置生成等差网格价位表
    2. 监听实时价格，当价格穿越网格线时触发买入
    3. 买单成交后，在上一级网格自动挂卖单（配对利润循环）
    4. 持续检测风控条件（止损/止盈/价差/资金预留）
    """
    
    def __init__(self, bot_config: BotConfig, client: BinanceClient):
        super().__init__(bot_config, client)
        
        # NOTE: 实例化 V3 V2 的兼容配置代理
        p = bot_config.parameters
        self._settings = GridSettingsProxy(
            gridLowerPrice=Decimal(str(p.get("grid_lower_price", 0))),
            gridUpperPrice=Decimal(str(p.get("grid_upper_price", 0))),
            gridCount=int(p.get("grid_count", 0)),
            gridInvestmentPerGrid=Decimal(str(p.get("grid_investment_per_grid", 0))),
            reserveRatio=Decimal(str(p.get("reserve_ratio", "0.05"))),
            adaptiveMode=bool(p.get("adaptive_mode", False)),
            analysisInterval=int(p.get("analysis_interval", 15)),
            maxSpreadPercent=Decimal(str(p.get("max_spread_percent", "0.005"))),
            maxOrderCount=int(p.get("max_order_count", 50)),
            maxPositionRatio=Decimal(str(p.get("max_position_ratio", "0.95"))),
            stopLossPercent=Decimal(str(p.get("stop_loss_percent", "0.2"))),
            takeProfitAmount=Decimal(str(p.get("take_profit_amount", "1000"))),
            martinMultiplier=Decimal(str(p.get("martin_multiplier", "1.5"))),
            maxMartinLevels=int(p.get("max_martin_levels", 3)),
            tradingSymbol=bot_config.symbol,
            tradeCooldown=float(p.get("trade_cooldown", 5.0)),
            staleDataTimeout=float(p.get("stale_data_timeout", 300.0)),
            maxDrawdown=Decimal(str(p.get("max_drawdown", "0.2"))),
        )

        from src.utils.notifier import Notifier # 临时提供 None，或者你可以从某个上下文获取
        self._notifier = Notifier() # 如果不需要发送，直接 mock 掉
        
        # 网格价位列表（从低到高）
        self._gridPrices: list[Decimal] = []
        # 挂单池：price (Decimal) -> GridOrder
        self._orders: dict[Decimal, GridOrder] = {}
        # 累计已实现利润
        self._realizedProfit: Decimal = Decimal("0")
        # 策略是否正在运行
        self._running: bool = False
        # 上一次接收到的价格
        self._lastPrice: Decimal = Decimal("0")

        # [V3.0] 性能优化缓存
        self._lastSpread: Decimal = Decimal("1")
        self._lastSpreadTime: float = 0

        # --- 自适应策略 ---
        self._analyzer = MarketAnalyzer(self._settings)
        self._currentAdjustment: GridAdjustment | None = None
        self._analysisTask: asyncio.Task | None = None

        # --- 安全层 ---
        self._martinLevel: int = 0           # 当前连续马丁加仓层数
        self._initialEquity: Decimal | None = None  # 初始账户净值（用于回撤计算）

        # --- ⏳ 交易冷却锁 ---
        self._lastTradeTime: float = 0.0
        self._cooldownSeconds: float = self._settings.tradeCooldown

        # --- RateLimiter 引用（通过 client 间接访问） ---
        self._rateLimiter = client._rateLimiter

    # ==================================================
    # 初始化
    # ==================================================

    def generateGrid(self) -> list[Decimal]:
        """
        生成等差网格价位表。

        从 gridLowerPrice 到 gridUpperPrice 均匀划分 gridCount 个区间，
        产生 gridCount + 1 个价位点。
        """
        lower = self._settings.gridLowerPrice
        upper = self._settings.gridUpperPrice
        count = self._settings.gridCount

        # 等差步长
        step = (upper - lower) / count

        self._gridPrices = [lower + step * i for i in range(count + 1)]

        logger.info("📐 网格已生成: %d 格, 步长 %s", count, step)
        for i, price in enumerate(self._gridPrices):
            logger.debug("  网格 %d: %s", i, price)

        return self._gridPrices

    async def initialize(self) -> None:
        """
        策略初始化：生成网格，尝试恢复上次状态，检查账户余额。
        """
        self.generateGrid()

        # 尝试恢复之前的策略状态
        restored = self._loadState()
        if restored:
            logger.info("🔄 已恢复上次策略状态 (%d 个挂单)", len(self._orders))
        else:
            logger.info("🆕 全新策略启动")
            # --- 战场清理 (V3.0) ---
            try:
                logger.info("🧹 正在执行 nuke_all_orders 清场程序以释放测试网可用额度...")
                await self._client.nuke_all_orders()
            except Exception as e:
                logger.error("❌ 战场清理失败: %s", e)

        # 检查可用余额
        freeBalance = await self._client.getFreeBalance("USDT")
        totalRequired = self._settings.gridInvestmentPerGrid * self._settings.gridCount
        logger.info(
            "💰 可用余额: %s USDT, 策略总需: %s USDT",
            freeBalance, totalRequired,
        )

        if freeBalance < totalRequired * self._settings.reserveRatio:
            logger.warning(
                "⚠️ 可用余额 (%s) 低于最低要求 (%s)，策略可能无法完全执行",
                freeBalance, totalRequired * self._settings.reserveRatio,
            )

        self._notifier.notify(
            f"🤖 网格策略已初始化\n"
            f"交易对: {self._settings.tradingSymbol}\n"
            f"网格范围: {self._settings.gridLowerPrice} ~ {self._settings.gridUpperPrice}\n"
            f"网格数: {self._settings.gridCount}\n"
            f"可用余额: {freeBalance} USDT\n"
            f"自适应模式: {'✅ 已启用' if self._settings.adaptiveMode else '❌ 未启用'}"
        )
        # 顺势拉起主循环
        await self.start()

    # ==================================================
    # 核心交易逻辑
    # ==================================================

    async def on_price_update(self, price: Decimal) -> None:
        """
        价格更新回调 — WebSocket 推送新价格时调用。

        检查价格是否穿越网格线，以及风控条件是否触发。
        """
        logger.debug(f"⚡ 收到实时价格: {price}")
        # print(f"Receive Price: {price}") # 注释掉干扰输出
        if not self._running:
            return

        self._lastPrice = price

        # --- 风控检查 ---
        if await self._checkStopLoss(price):
            return
        if await self._checkTakeProfit():
            return
        if await self._checkMaxDrawdown():
            return

        # --- 自适应暂停检查 ---
        if self._currentAdjustment and self._currentAdjustment.shouldPause:
            logger.debug("⚠️ 自适应暂停中 (%s)，跳过新建仓", self._currentAdjustment.state.value)
            return

        # --- 数据超时保护 ---
        if self._isDataStale():
            logger.warning("⚠️ K 线数据过期，进入保护模式，暂停新建仓")
            return

        # --- 网格交易逻辑 ---
        await self._evaluateGridOrders(price)

    async def _evaluateGridOrders(self, currentPrice: Decimal) -> None:
        """
        评估当前价格与网格的关系，决定是否下单。
        V2.3: 支持动态密度。新单将根据基于 ATR 的动态步长和密度因子进行布阵。
        """
        if not self._currentAdjustment:
            return

        # 计算当前动态步长
        baseStep = (self._settings.gridUpperPrice - self._settings.gridLowerPrice) / Decimal(str(self._settings.gridCount))
        density = self._currentAdjustment.densityMultiplier
        dynamicStep = baseStep / density

        # 从低到高扫描
        checkPrice = self._settings.gridLowerPrice
        while checkPrice <= self._settings.gridUpperPrice:
            # 价格低于当前标价点
            if currentPrice <= checkPrice:
                # 检查该价位是否有挂单 (允许 10% step 的微小容差)
                # v2.3 使用价格作为 key，但为了更稳健，我们扫描所有 PENDING 单
                isPriceOccupied = False
                for o in self._orders.values():
                    if o.status == OrderStatus.PENDING and abs(o.price - checkPrice) < (dynamicStep * Decimal("0.1")):
                        isPriceOccupied = True
                        break
                
                if not isPriceOccupied:
                    # 简单估算索引
                    virtualIdx = int((checkPrice - self._settings.gridLowerPrice) / dynamicStep) if dynamicStep > 0 else 0
                    await self._placeBuyOrder(virtualIdx, checkPrice)
                    await asyncio.sleep(0.15)  # 阶梯式挂单延迟，避开 Binance 10秒/50单 的红线 (Err -1015)

            checkPrice += dynamicStep
            if dynamicStep <= 0: break

    async def _placeBuyOrder(self, gridIndex: int, price: Decimal) -> None:
        """
        在指定网格价位挂买入限价单。

        @param gridIndex 网格索引
        @param price 买入价格
        """
        # --- 价差检查 (V3.0 缓存优化) ---
        now = time.time()
        if now - self._lastSpreadTime > 5:
            # 仅在缓存失效时请求盘口，消耗 5 权重
            self._lastSpread = await self._client.getBidAskSpread()
            self._lastSpreadTime = now
            
        if self._lastSpread > self._settings.maxSpreadPercent:
            logger.warning(
                "⏸️ 价差过大 (%s%% > %s%%)，暂停在网格 %d 挂单",
                self._lastSpread * 100, self._settings.maxSpreadPercent * 100, gridIndex,
            )
            return

        # --- 资金预留检查 (V3.0 使用缓存镜像) ---
        # getFreeBalance 现在从本地快照读取，0 权重
        freeBalance = await self._client.getFreeBalance("USDT")
        
        # 使用本地挂买单列表计算已占用资金
        pendingBuyOrders = [o for o in self._orders.values() if o.status == OrderStatus.PENDING and o.side == GridSide.BUY]
        totalInvested = sum(o.quantity * o.price for o in pendingBuyOrders) # 近似值
        
        totalFunds = freeBalance + totalInvested
        if freeBalance < totalFunds * self._settings.reserveRatio:
            logger.warning(
                "⏸️ 可用余额 (%s) 低于预留要求 (%s%%)，暂停新建仓位",
                freeBalance, self._settings.reserveRatio * 100,
            )
            return

        # --- 仓位占比检查 (V3.0 零权重计算) ---
        # 传入当前价格计算实时持仓价值
        positionOverLimit = await self._checkPositionRatio(price)
        if positionOverLimit:
            logger.warning("⚠️ 持仓占比超限，暂停买入")
            return

        # --- 挂单数上限检查 (V3.0: 本地计数, 0 权重) ---
        pendingCount = sum(
            1 for o in self._orders.values()
            if o.status == OrderStatus.PENDING
        )
        if pendingCount >= self._settings.maxOrderCount:
            logger.warning(
                "\u26a0\ufe0f 挂单数已达上限 (%d/%d)\uff0c\u6682\u505c\u65b0\u6302\u5355",
                pendingCount, self._settings.maxOrderCount,
            )
            return

        # --- RateLimiter 熔断检查 ---
        if self._rateLimiter.isInCircuitBreaker:
            logger.warning("\ud83d\udea8 \u6743\u91cd\u7194\u65ad\u4e2d\uff0c\u8df3\u8fc7\u65b0\u4e70\u5355")
            return

        # 计算买入数量（自适应模式下动态调整投入量）
        baseInvestment = self._settings.gridInvestmentPerGrid
        if self._currentAdjustment:
            baseInvestment = baseInvestment * self._currentAdjustment.investmentMultiplier
            # NOTE: 限制马丁格尔加仓不超过配置的上限
            maxInvestment = self._settings.gridInvestmentPerGrid * self._settings.martinMultiplier
            baseInvestment = min(baseInvestment, maxInvestment)

        # --- 马丁安全层：连续加仓层数超限时回退到标准投入 ---
        if self._martinLevel >= self._settings.maxMartinLevels:
            logger.warning("⚠️ 马丁加仓已达上限 (%d层)，回退标准投入", self._martinLevel)
            baseInvestment = self._settings.gridInvestmentPerGrid

        quantity = baseInvestment / price

        # --- 🛡️ NOTIONAL (最小下单金额) 保护 ---
        # 币安要求单笔订单金额必须大于 minNotional (通常测试网是 5或10，主网是 10或5)
        # 如果计算出的投资额不够，强制上调 quantity 凑够最低消费限制，防止 -1013 错误
        minNotional = self._client._minNotional
        if (quantity * price) < minNotional:
            logger.debug("⚠️ 买单金额 (%.2f) 小于最低要求 (%s)，自动补足数量", float(quantity * price), float(minNotional))
            # 补足最低金额，并额外加上 1% 缓冲防止因为价格在挂单瞬间微跌导致四舍五入后又不够了
            safeNotional = minNotional * Decimal("1.01")
            quantity = safeNotional / price
            
        # 截断到交易所允许的精度
        quantity = Decimal(self._client.formatQuantity(quantity))

        # --- ⏳ 交易冷却拦截器 ---
        currentTime = time.time()
        if currentTime - self._lastTradeTime < self._cooldownSeconds:
            # 冷却期内直接跳过，保障狙击节奏
            return

        try:
            order = await self._client.createLimitOrder(
                side="BUY",
                price=price,
                quantity=quantity,
            )
            self._lastTradeTime = time.time()

            gridOrder = GridOrder(
                gridIndex=gridIndex,
                price=price,
                side=GridSide.BUY,
                quantity=quantity,
                orderId=order.get("orderId"),
                status=OrderStatus.PENDING,
            )
            self._orders[price] = gridOrder

            # 更新马丁层数
            if self._currentAdjustment and self._currentAdjustment.investmentMultiplier > Decimal("1"):
                self._martinLevel += 1
            else:
                self._martinLevel = 0  # 非加仓模式时重置

            logger.info("🟢 买单已挂: 网格 %d @ %s, 数量 %s", gridIndex, price, quantity)
            self._notifier.notify(
                f"🟢 买单已挂\n"
                f"网格 {gridIndex} @ {price}\n"
                f"数量: {self._client.formatQuantity(quantity)} {self._settings.tradingSymbol.replace('USDT', '')}\n"
                f"投入: {baseInvestment:.1f} USDT"
            )
            self._saveState()

        except Exception as e:
            logger.error("❌ 网格 %d 买单失败: %s", gridIndex, e)

    async def on_order_update(self, event: dict[str, Any]) -> None:
        """
        订单状态更新回调 — 用户数据流推送时调用。

        支持 FILLED / PARTIALLY_FILLED / CANCELED 三种状态：
        - 买单完全成交：自动挂配对卖单
        - 卖单完全成交：记录利润并通知
        - 部分成交：记录日志，不触发配对
        - 取消/过期：清理本地订单状态
        """
        orderId = event.get("i")  # orderId
        status = event.get("X")   # 订单状态
        side = event.get("S")     # BUY / SELL

        # 查找对应的网格订单
        matchedGrid: GridOrder | None = None
        for gridOrder in self._orders.values():
            if gridOrder.orderId == orderId:
                matchedGrid = gridOrder
                break

        if not matchedGrid:
            return

        # --- 取消/过期/拒绝：清理本地状态 ---
        if status in ("CANCELED", "EXPIRED", "REJECTED"):
            logger.info(
                "🗑️ 订单已终结 (%s): 网格 %d, orderId=%s",
                status, matchedGrid.gridIndex, orderId,
            )
            matchedGrid.status = OrderStatus.CANCELLED
            del self._orders[matchedGrid.price]
            self._saveState()
            return

        # --- 部分成交：仅记录日志 ---
        if status == "PARTIALLY_FILLED":
            filledQty = Decimal(event.get("z", "0"))
            logger.info(
                "\u23f3 \u90e8\u5206\u6210\u4ea4: \u7f51\u683c %d, %s %s, \u5df2\u6210\u4ea4 %s",
                matchedGrid.gridIndex, side, matchedGrid.price, filledQty,
            )
            return

        # --- 完全成交 ---
        if status != "FILLED":
            return

        matchedGrid.status = OrderStatus.FILLED
        filledPrice = Decimal(event.get("L", "0"))  # 最后成交价
        filledQty = Decimal(event.get("z", "0"))     # 累计成交数量

        if side == "BUY":
            logger.info(
                "\u2705 \u4e70\u5355\u6210\u4ea4: \u7f51\u683c %d @ %s, \u6570\u91cf %s",
                matchedGrid.gridIndex, filledPrice, filledQty,
            )
            self._notifier.notify(
                f"\u2705 \u4e70\u5355\u6210\u4ea4\n"
                f"\u7f51\u683c {matchedGrid.gridIndex} @ {filledPrice}\n"
                f"\u6570\u91cf: {filledQty}"
            )
            # 立即在上一级网格挂配对卖单
            await self._placeSellOrder(
                gridIndex=matchedGrid.gridIndex,
                buyPrice=filledPrice,
                quantity=filledQty,
            )

        elif side == "SELL":
            # V2.3: 直接使用卖单记录的 entryPrice 计算利润
            if matchedGrid.entryPrice:
                profit = (filledPrice - matchedGrid.entryPrice) * filledQty
                self._realizedProfit += profit

                logger.info(
                    "\ud83d\udcb0 \u5356\u5355\u6210\u4ea4: \u7f51\u683c %d @ %s | \u672c\u6b21\u5229\u6da6: %s USDT | \u7d2f\u8ba1\u5229\u6da6: %s USDT",
                    matchedGrid.gridIndex, filledPrice, profit, self._realizedProfit,
                )

                self._notifier.notify(
                    f"\ud83d\udcb0 \u914d\u5bf9\u5957\u5229\u5b8c\u6210\n"
                    f"\u7f51\u683c {matchedGrid.gridIndex}: "
                    f"\u4e70\u5165 {matchedGrid.entryPrice} \u2192 \u5356\u51fa {filledPrice}\n"
                    f"\u5229\u6da6: {profit} USDT\n"
                    f"\u7d2f\u8ba1: {self._realizedProfit} USDT"
                )

                # 清除已完成的网格订单，允许重新挂单
                del self._orders[matchedGrid.price]

        self._saveState()

    async def _placeSellOrder(
        self,
        gridIndex: int,
        buyPrice: Decimal,
        quantity: Decimal,
    ) -> None:
        """
        挂配对卖单：价格 = 上一级网格价位。

        @param gridIndex 买入网格索引
        @param buyPrice 实际买入价格
        @param quantity 买入数量
        """
        # 上一级网格价位
        sellGridIndex = gridIndex + 1
        if sellGridIndex >= len(self._gridPrices):
            # 已在最高网格，直接用买入价 + 步长
            step = (self._settings.gridUpperPrice - self._settings.gridLowerPrice) / self._settings.gridCount
            sellPrice = buyPrice + step
        else:
            sellPrice = self._gridPrices[sellGridIndex]

        try:
            await asyncio.sleep(0.2)

            # --- ⏳ 交易冷却拦截器 (卖单使用排队等待) ---
            currentTime = time.time()
            timeToWait = self._cooldownSeconds - (currentTime - self._lastTradeTime)
            if timeToWait > 0:
                await asyncio.sleep(timeToWait)

            # --- 🛡️ NOTIONAL (最小下单金额) 保护 ---
            # 卖单同样需要遵守币安的最小交易额度规则
            minNotional = self._client._minNotional
            if (quantity * sellPrice) < minNotional:
                logger.debug("⚠️ 卖单金额 (%.2f) 小于最低要求 (%s)，自动补足数量", float(quantity * sellPrice), float(minNotional))
                safeNotional = minNotional * Decimal("1.01")
                quantity = safeNotional / sellPrice
                
            # 截断到交易所允许的精度
            quantity = Decimal(self._client.formatQuantity(quantity))

            order = await self._client.createLimitOrder(
                side="SELL",
                price=sellPrice,
                quantity=quantity,
            )
            self._lastTradeTime = time.time()

            # NOTE: 卖单记录买入成本，用于成交后计算利润
            sellOrder = GridOrder(
                gridIndex=gridIndex,
                price=sellPrice,
                side=GridSide.SELL,
                quantity=quantity,
                orderId=order.get("orderId"),
                status=OrderStatus.PENDING,
                entryPrice=buyPrice,  # 记录买入成本
            )
            self._orders[sellPrice] = sellOrder

            logger.info(
                "🔴 卖单已挂: 网格 %d → 卖出 @ %s, 数量 %s",
                gridIndex, sellPrice, quantity,
            )
            self._notifier.notify(
                f"🔴 卖单已挂\n"
                f"网格 {gridIndex} → 卖出 @ {sellPrice}\n"
                f"数量: {self._client.formatQuantity(quantity)}"
            )
            self._saveState()

        except Exception as e:
            logger.error("❌ 配对卖单失败 (网格 %d): %s", gridIndex, e)

    # ==================================================
    # 风控系统
    # ==================================================

    async def _checkStopLoss(self, currentPrice: Decimal) -> bool:
        """
        止损检查：当价格跌破最低网格线的 N% 时，市价清仓。

        @param currentPrice 当前价格
        @returns 是否触发了止损
        """
        stopPrice = self._gridPrices[0] * (1 - self._settings.stopLossPercent)

        if currentPrice <= stopPrice:
            logger.critical(
                "🚨 触发止损! 当前价格 %s 低于止损线 %s",
                currentPrice, stopPrice,
            )
            await self._emergencyExit("止损触发")
            return True
        return False

    async def _checkTakeProfit(self) -> bool:
        """
        止盈检查：累计利润达到目标时，撤销所有挂单。

        @returns 是否触发了止盈
        """
        if self._realizedProfit >= self._settings.takeProfitAmount:
            logger.info(
                "🎯 触发止盈! 累计利润 %s USDT 达到目标 %s USDT",
                self._realizedProfit, self._settings.takeProfitAmount,
            )
            await self._emergencyExit("止盈达标")
            return True
        return False

    async def _emergencyExit(self, reason: str) -> None:
        """
        紧急退出：撤销所有挂单，市价清仓所有持仓。

        @param reason 退出原因
        """
        self._running = False

        logger.warning("🚨 紧急退出: %s", reason)

        # 1. 撤销所有挂单
        try:
            await self._client.cancelAllOrders()
        except Exception as e:
            logger.error("撤销挂单失败: %s", e)

        # 2. 查询并清仓持仓
        try:
            # 获取基础资产名称（如 BTCUSDT → BTC）
            baseAsset = self._settings.tradingSymbol.replace("USDT", "")
            balance = await self._client.getFreeBalance(baseAsset)

            if balance > 0:
                logger.info("📤 清仓 %s %s", balance, baseAsset)
                await self._client.createMarketOrder(
                    side="SELL",
                    quantity=balance,
                )
        except Exception as e:
            logger.error("清仓失败: %s", e)

        # 3. 通知
        await self._notifier.sendImmediate(
            f"🚨 <b>紧急退出</b>\n"
            f"原因: {reason}\n"
            f"最后价格: {self._lastPrice}\n"
            f"累计利润: {self._realizedProfit} USDT"
        )

        self._saveState()

    # ==================================================
    # 策略生命周期 (重写自 BaseStrategy.initialize)
    # ==================================================

    async def start(self) -> None:
        """启动策略 (保留原名叫 start 作为内部别名或外部主动调用)"""
        self._running = True
        logger.info("🚀 网格策略已启动 (ID: %d)", self.bot_config.id)

        # 记录初始净值（用于回撤计算）
        try:
            _, totalValue = await self._client.getTotalPositionValue()
            self._initialEquity = totalValue
            logger.info("💰 初始账户净值: %s USDT", totalValue)
        except Exception as e:
            logger.warning("获取初始净值失败: %s", e)

        # 启动自适应市场分析任务
        if self._settings.adaptiveMode:
            self._analysisTask = asyncio.create_task(self._analysisLoop())
            logger.info("🧠 自适应市场分析已启动 (间隔: %d秒)", self._settings.analysisInterval)

    async def stop(self) -> None:
        """优雅停止策略"""
        self._running = False

        if self._analysisTask:
            self._analysisTask.cancel()
            try:
                await self._analysisTask
            except asyncio.CancelledError:
                pass

        self._saveState()
        logger.info("⏹️ 网格策略已停止")

    async def _analysisLoop(self) -> None:
        """
        市场分析循环：定期采集多周期 K 线数据，计算技术指标，调整网格参数。
        采用 MTF 多周期确认：1h 大周期 + 15m 小周期。
        """
        # NOTE: 首次启动等待 10 秒让连接先稳定
        await asyncio.sleep(10)

        while self._running:
            try:
                # v2.2: 计算实时持仓占比
                posValue, totalValue = await self._client.getTotalPositionValue()
                posRatio = posValue / totalValue if totalValue > 0 else Decimal("0")
                
                # MTF: 同时获取大小周期 K 线
                klinesBig = await self._client.getKlines(interval="1h", limit=50)
                klinesSmall = await self._client.getKlines(interval="15m", limit=50)
                adjustment = self._analyzer.analyze(klinesBig, klinesSmall, positionRatio=posRatio)

                # v2.3: ATR 间距/费率盾牌现在由 analyzer 内部统一计算并输出在 densityMultiplier/suggestedGridStep 中

                oldState = self._currentAdjustment.state if self._currentAdjustment else None
                self._currentAdjustment = adjustment

                if oldState != adjustment.state:
                    self._notifier.notify(
                        f"🧠 市场状态切换\n"
                        f"新状态: {adjustment.state.value}\n"
                        f"网格偏移: {adjustment.gridCenterShift:+.1%}\n"
                        f"密度系数: {adjustment.densityMultiplier:.1f}x\n"
                        f"投入系数: {adjustment.investmentMultiplier:.1f}x\n"
                        f"暂停建仓: {'是' if adjustment.shouldPause else '否'}"
                    )

                logger.info("🧠 市场分析: %s", adjustment)

                # --- 智能撤单: 清理偏离过大的订单 ---
                if self._lastPrice > 0:
                    cancelledCount = await self._client.cancelFarOrders(
                        currentPrice=self._lastPrice,
                        threshold=Decimal("0.05")  # 基础阈值 5%，后续可加入配置
                    )
                    if cancelledCount > 0:
                        # 撤单后同步更新本地订单状态
                        await self._syncOrdersWithExchange()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("市场分析失败: %s", e)

            await asyncio.sleep(self._settings.analysisInterval)

    # ==================================================
    # 安全层
    # ==================================================

    async def _checkMaxDrawdown(self) -> bool:
        """
        \u68c0\u67e5\u8d26\u6237\u56de\u64a4\u662f\u5426\u8d85\u8fc7\u9600\u503c\u3002
        [V3.0] \u4f7f\u7528\u672c\u5730\u4f59\u989d\u5feb\u7167 + lastPrice \u8ba1\u7b97\uff0c0 \u6743\u91cd\u6d88\u8017\u3002
        """
        if self._initialEquity is None or self._initialEquity <= 0:
            return False
        if self._lastPrice <= 0:
            return False

        try:
            # NOTE: \u672c\u5730\u8ba1\u7b97\uff0c\u4e0d\u89e6\u53d1\u4efb\u4f55 REST \u8bf7\u6c42
            positionValue, totalValue = await self._client.getTotalPositionValue(self._lastPrice)
            drawdown = (self._initialEquity - totalValue) / self._initialEquity

            if drawdown >= self._settings.maxDrawdown:
                logger.critical(
                    "\ud83d\udea8 \u8d26\u6237\u56de\u64a4\u8d85\u9650! \u56de\u64a4=%.1f%%, \u9600\u503c=%.1f%%",
                    float(drawdown * 100), float(self._settings.maxDrawdown * 100),
                )
                await self._emergencyExit(
                    f"\u56de\u64a4\u8d85\u9650 ({drawdown:.1%} > {self._settings.maxDrawdown:.1%})"
                )
                return True
        except Exception as e:
            logger.error("\u56de\u64a4\u68c0\u67e5\u5931\u8d25: %s", e)

        return False

    async def _checkPositionRatio(self, currentPrice: Decimal = Decimal("0")) -> bool:
        """
        \u68c0\u67e5\u6301\u4ed3\u5360\u6bd4\u662f\u5426\u8d85\u9650\u3002
        [V3.0] \u4f7f\u7528\u672c\u5730\u4f59\u989d + \u5f53\u524d\u4ef7\u683c\u8ba1\u7b97\uff0c0 \u6743\u91cd\u3002
        \u8d85\u8fc7 maxPositionRatio \u65f6\u505c\u6b62\u4e70\u5165\uff0c\u53ea\u6302\u5356\u5355\u3002
        """
        if currentPrice <= 0:
            currentPrice = self._lastPrice
        if currentPrice <= 0:
            return False

        try:
            # NOTE: \u4f20\u5165 currentPrice \u786e\u4fdd getTotalPositionValue \u4e0d\u56de\u9000 REST
            positionValue, totalValue = await self._client.getTotalPositionValue(currentPrice)
            if totalValue <= 0:
                return False

            ratio = positionValue / totalValue
            if ratio >= self._settings.maxPositionRatio:
                logger.warning(
                    "\u26a0\ufe0f \u6301\u4ed3\u5360\u6bd4 %.1f%% \u8d85\u9650 (%.1f%%)\uff0c\u505c\u6b62\u4e70\u5165",
                    float(ratio * 100), float(self._settings.maxPositionRatio * 100),
                )
                return True
        except Exception as e:
            logger.error("\u4ed3\u4f4d\u68c0\u67e5\u5931\u8d25: %s", e)

        return False

    def _isDataStale(self) -> bool:
        """
        检查 K 线数据是否过期。
        如果自适应模式开启且上次分析时间超过阀值，则进入保护模式。
        """
        if not self._settings.adaptiveMode:
            return False

        import time
        lastTime = self._analyzer.lastAnalysisTime
        if lastTime == 0:
            return False  # 尚未进行首次分析

        elapsed = time.time() - lastTime
        return elapsed > self._settings.staleDataTimeout

    @property
    def isRunning(self) -> bool:
        return self._running

    # ==================================================
    # 状态持久化
    # ==================================================

    def _saveState(self) -> None:
        """将策略状态保存到 JSON 文件，支持重启恢复"""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        # 用 Bot ID 替代单一的交易对命名
        stateFile = STATE_DIR / f"bot_{self.bot_config.id}_grid.state.json"

        state = {
            "realizedProfit": str(self._realizedProfit),
            "lastPrice": str(self._lastPrice),
            "running": self._running,
            "orders": {
                str(k): v.toDict() for k, v in self._orders.items()
            },
        }

        try:
            stateFile.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.debug("💾 策略状态已保存")
        except Exception as e:
            logger.error("状态保存失败: %s", e)

    def _loadState(self) -> bool:
        """
        从 JSON 文件恢复策略状态。

        @returns 是否成功恢复
        """
        # 用 Bot ID 替代单一的交易对命名
        stateFile = STATE_DIR / f"bot_{self.bot_config.id}_grid.state.json"

        if not stateFile.exists():
            return False

        try:
            data = json.loads(stateFile.read_text(encoding="utf-8"))
            self._realizedProfit = Decimal(data.get("realizedProfit", "0"))
            self._lastPrice = Decimal(data.get("lastPrice", "0"))

            for key, orderData in data.get("orders", {}).items():
                order = GridOrder.fromDict(orderData)
                self._orders[order.price] = order

            logger.info(
                "📂 恢复状态: 累计利润=%s, 挂单数=%d",
                self._realizedProfit, len(self._orders),
            )
            return True

        except Exception as e:
            logger.error("状态恢复失败: %s", e)
            return False

    async def _syncOrdersWithExchange(self) -> None:
        """从交易所同步当前挂单状态，清理本地已撤销且不存在于交易所的订单"""
        try:
            openOrders = await self._client.getOpenOrders()
            openIds = {int(o["orderId"]) for o in openOrders}

            # 找出本地记录中，但在交易所已经不存在的 PENDING 订单
            toRemove = []
            for idx, order in self._orders.items():
                if order.status == OrderStatus.PENDING and order.orderId not in openIds:
                    toRemove.append(idx)

            for prc in toRemove:
                logger.info("🧹 清理本地已失效订单: 价格 %s, orderId=%s", prc, self._orders[prc].orderId)
                del self._orders[prc]

            if toRemove:
                self._saveState()

        except Exception as e:
            logger.error("同步订单状态失败: %s", e)
