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
from dataclasses import dataclass
from typing import Dict, Optional, Any

from src.exchanges.binance_client import BinanceClient
from src.models.bot import BotConfig
from src.services.notification_service import notification_service, NotificationLevel
from src.strategies.market_analyzer import MarketAnalyzer, MarketState, GridAdjustment
from src.db.session import AsyncSessionLocal
from src.strategies.base_strategy import BaseStrategy
from src.engine.redis_pubsub import redis_bus

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
    trendEmaPeriod: int = 200 # 自适应模式下，分析系统用到此项判断牛熊


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
        def to_decimal(val, default="0"):
            if val is None or str(val).strip() == "":
                return Decimal(default)
            try:
                return Decimal(str(val))
            except Exception:
                return Decimal(default)

        self._settings = GridSettingsProxy(
            gridLowerPrice=to_decimal(p.get("grid_lower_price")),
            gridUpperPrice=to_decimal(p.get("grid_upper_price")),
            gridCount=int(p.get("grid_count", 0)),
            gridInvestmentPerGrid=to_decimal(p.get("grid_investment_per_grid")),
            reserveRatio=to_decimal(p.get("reserve_ratio", "0.05")),
            adaptiveMode=bool(p.get("adaptive_mode", False)),
            analysisInterval=int(p.get("analysis_interval", 15)),
            maxSpreadPercent=to_decimal(p.get("max_spread_percent", "0.005")),
            maxOrderCount=int(p.get("max_order_count", 50)),
            maxPositionRatio=to_decimal(p.get("max_position_ratio", "0.95")),
            stopLossPercent=to_decimal(p.get("stop_loss_percent", "0.2")),
            takeProfitAmount=to_decimal(p.get("take_profit_amount", "1000")),
            martinMultiplier=to_decimal(p.get("martin_multiplier", "1.5")),
            maxMartinLevels=int(p.get("max_martin_levels", 3)),
            tradingSymbol=bot_config.symbol,
            tradeCooldown=float(p.get("trade_cooldown", 5.0)),
            staleDataTimeout=float(p.get("stale_data_timeout", 300.0)),
            maxDrawdown=to_decimal(p.get("max_drawdown", "0.2")),
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

        # 防并发锁 (元组: (gridIndex, GridSide))，防止异步 HTTP 延迟时重复进单
        self._creation_locks: set[tuple[int, GridSide]] = set()

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

        # 2. 尝试恢复之前的策略状态
        restored = self._loadState()
        
        # 3. 获取当前市场价
        currentPrice = await self._client.getCurrentPrice()
        self._lastPrice = currentPrice

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
            
            # --- [P4] Gap Check: 检查价格是否击穿边界 ---
            if currentPrice > self._settings.gridUpperPrice or currentPrice < self._settings.gridLowerPrice:
                logger.warning("🚨 [Gap Check] 价格已击穿网格边界 (%s), 启动失败，请调整区间。", currentPrice)
                self._notifier.notify(f"🚨 **Gap Check 拦截**\n价格 {currentPrice} 已超出网格区间 {self._settings.gridLowerPrice}~{self._settings.gridUpperPrice}。机器人将处于 PAUSED 状态。")
                self._running = False
                return

            # --- [P3] 自动底仓构建 (Bootstrapping) ---
            await self._bootstrapPosition(currentPrice)

        # 4. 检查可用余额 (USDT)
        freeBalance = await self._client.getFreeBalance("USDT")
        
        # [P2] 手续费缓冲验证：总投资额 = (网格数 * 单格投入) × 1.002
        totalRequired = (self._settings.gridInvestmentPerGrid * self._settings.gridCount) * Decimal("1.002")
        logger.info(
            "💰 账户可用余额: %s USDT, 策略维持总需 (含0.2%%手续费): %s USDT",
            freeBalance, totalRequired,
        )

        self._notifier.notify(
            f"🤖 网格策略初始化完成\n"
            f"交易对: {self._settings.tradingSymbol}\n"
            f"当前价: {currentPrice}\n"
            f"网格: {self._settings.gridLowerPrice} ~ {self._settings.gridUpperPrice}\n"
            f"Bootstrapping: {'已执行/恢复' if not restored else '状态已恢复'}"
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

        # [P3] 实时价格广播：同步至前端监控水位线
        asyncio.create_task(redis_bus.publish_trade_event(
            user_id=self.bot_config.user_id,
            bot_id=self.bot_config.id,
            event_type="PRICE_UPDATE",
            data={
                "symbol": self._settings.tradingSymbol,
                "price": float(price)
            }
        ))

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

    async def panic_close(self) -> dict[str, Any]:
        """
        [一键平仓]
        强制清理战场：撤销由于此机器人发起的所有现货挂单，
        并将本持仓周期内的 Base Asset 依照交易所精度 (Lot Size) 及最小金额限制 (Min Notional)
        全部通过市价卖出回收为 USDT。
        """
        logger.warning("🚨 [一键平仓] 正在接收强平指令，启动强制撤单清算...")
        
        # 1. 撤销当前所有的 PENDING 网格单
        try:
            await self._client.cancelAllOrders()
            # 标记本地状态位全部取消以防僵尸恢复
            for order in self._orders.values():
                order.status = OrderStatus.CANCELLED
            self._orders.clear()
            self._saveState() # 保存清空后的状态
            logger.info("🗑️ [一键平仓] 网格挂单拦截并清理完毕")
        except Exception as e:
            logger.error("❌ [一键平仓] 撤单阶段发生异常: %s", e)
            return {"status": "error", "message": f"撤单阶段失败: {e}"}

        # 2. 查询该币种实际的可用余额
        baseAsset = self._settings.tradingSymbol.replace("USDT", "")
        freeBalance = await self._client.getFreeBalance(baseAsset)
        
        # 3. 截断小数位并进行 LOT_SIZE 对齐。借助 self._client.formatQuantity 可以直接获得截断后符合规则的字符串。
        try:
            sell_qty_str = self._client.formatQuantity(freeBalance)
            sell_qty_dec = Decimal(sell_qty_str)
        except Exception as e:
            logger.warning("⚠️ [一键平仓] 格式化挂单数量失败: %s", e)
            return {"status": "error", "message": "无法计算抛售精度"}

        if sell_qty_dec <= 0:
            msg = f"账户内 {baseAsset} 可用余额为 {freeBalance} (格式化后 0)，无可抛货物，清算直接结束"
            logger.info("ℹ️ [一键平仓] %s", msg)
            self._notifier.notify(f"ℹ️ **一键平仓**\n{msg}")
            return {"status": "success", "message": msg}

        # 4. 获取即时的最新买盘价格（或简单的最后交易价），以测算 MIN_NOTIONAL 强制防抛墙保护
        try:
            currentPrice = await self._client.getCurrentPrice()
            estimated_value = sell_qty_dec * currentPrice
            minNotional = self._client._minNotional
            if estimated_value < minNotional:
                error_msg = f"可抛资产 ({sell_qty_dec} @ {currentPrice}) 总价值约 {estimated_value:.2f} USDT，未能满足交易所要求的系统下限 ({minNotional} USDT)。强制抛售已中止，请人工接管。"
                logger.error("🚫 [一键平仓] %s", error_msg)
                self._notifier.notify(f"🚫 **一键平仓失败**\n{error_msg}")
                return {"status": "error", "message": error_msg}
        except Exception as e:
            logger.warning("⚠️ 评估名义价值时报错 (尝试跳过强制): %s", e)

        # 5. 放出真实市价单 (MARKET SELL) 强抛
        try:
            order = await self._client.createMarketOrder(
                side="SELL",
                quantity=sell_qty_dec
            )
            logger.warning("🔥 [一键平仓] 市价抛售完成! 卖出 %s %s", sell_qty_dec, baseAsset)
            self._notifier.notify(
                f"🔥 **一键平仓执行完毕**\n"
                f"标的: {self._settings.tradingSymbol}\n"
                f"状态: 所有网格单已撤销\n"
                f"清算脱手: {sell_qty_dec} {baseAsset}"
            )
            # 重设自身标记：清理所有状态以便不再有遗留
            self._running = False # 停止策略运行
            self._saveState() # 保存清空后的状态
            return {"status": "success", "data": order, "message": "所有挂单已撤销，资产池已通过市价折旧"}
        except Exception as e:
            logger.error("❌ [一键平仓] 市价卖出遇到核心异常: %s", e)
            self._notifier.notify(f"❌ **一键平仓失败**\n市价卖出阶段失败: {e}")
            return {"status": "error", "message": f"市价甩卖阶段失败: {e}"}

    async def _evaluateGridOrders(self, currentPrice: Decimal) -> None:
        """
        评估当前价格与网格的关系，决定是否下单。
        V2.3: 支持动态密度。新单将根据基于 ATR 的动态步长和密度因子进行布阵。
        """
        if not self._currentAdjustment:
            if not self._settings.adaptiveMode:
                # 修复: 如果关闭了自适应模式，_currentAdjustment 永远不会被 _analysisLoop 设置。
                # 此时应该注入一个默认的静态 Adjustment 让网格计算能够走下去
                self._currentAdjustment = GridAdjustment(
                    state=MarketState.NORMAL,
                    gridCenterShift=Decimal("0"),
                    densityMultiplier=Decimal("1"),
                    investmentMultiplier=Decimal("1"),
                    shouldPause=False
                )
            else:
                logger.info("🛡️ [诊断] 自适应分析未完成，暂缓挂单")
                return

        # 计算当前动态步长
        baseStep = (self._settings.gridUpperPrice - self._settings.gridLowerPrice) / Decimal(str(self._settings.gridCount))
        density = self._currentAdjustment.densityMultiplier
        dynamicStep = baseStep / density

        # 从低到高扫描
        checkPrice = self._settings.gridLowerPrice
        while checkPrice <= self._settings.gridUpperPrice:
            # --- 卖出盘区 (当前价格以上) ---
            if checkPrice > currentPrice:
                isPriceOccupied = False
                for o in self._orders.values():
                    if o.side == GridSide.SELL and o.status in (OrderStatus.PENDING,):
                        if abs(o.price - checkPrice) < (dynamicStep * Decimal("0.1")):
                            isPriceOccupied = True
                            break
                
                if not isPriceOccupied:
                    # 简单估算索引
                    virtualIdx = int((checkPrice - self._settings.gridLowerPrice) / dynamicStep) if dynamicStep > 0 else 0
                    # 对于初始化卖单区，相当于假装以 checkPrice - step 买入，这里将调用一个独立的逻辑来进行现货高频核算卖单
                    await self._placeInitialSellOrder(virtualIdx, checkPrice, dynamicStep)
                    await asyncio.sleep(0.15)
                    
            # --- 买入盘区 (当前价格以下) ---
            elif checkPrice < currentPrice:
                isPriceOccupied = False
                for o in self._orders.values():
                    # 判断如果该价格附近存在 PENDING 或者 已经买入了但还没完成套利清仓的买单(FILLED)，则视为此网格已被占用
                    if o.side == GridSide.BUY and o.status in (OrderStatus.PENDING, OrderStatus.FILLED):
                        if abs(o.price - checkPrice) < (dynamicStep * Decimal("0.1")):
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
        lock_key = (gridIndex, GridSide.BUY)
        if lock_key in self._creation_locks:
            return  # 正在挂单中，跳过本次触发
        self._creation_locks.add(lock_key)

        try:
            # --- 价差检查 (V3.0 缓存优化) ---
            now = time.time()
            if now - self._lastSpreadTime > 5:
                # 仅在缓存失效时请求盘口，消耗 5 权重
                self._lastSpread = await self._client.getBidAskSpread()
                self._lastSpreadTime = now
                
            if self._lastSpread > self._settings.maxSpreadPercent:
                logger.info(
                    "🛡️ [诊断-拦截] 价差过大 (%s%% > %s%%)，暂停在网格 %d 挂单",
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
                logger.info(
                    "🛡️ [诊断-拦截] 可用余额 (%s) 低于预留要求 (%s%%)，暂停新建仓位",
                    freeBalance, self._settings.reserveRatio * 100,
                )
                return

            # --- 仓位占比检查 (V3.0 零权重计算) ---
            # 传入当前价格计算实时持仓价值
            positionOverLimit = await self._checkPositionRatio(price)
            if positionOverLimit:
                logger.info("🛡️ [诊断-拦截] 持仓占比超限，暂停买入")
                return

            # --- 挂单数上限检查 (V3.0: 本地计数, 0 权重) ---
            pendingCount = sum(
                1 for o in self._orders.values()
                if o.status == OrderStatus.PENDING
            )
            if pendingCount >= self._settings.maxOrderCount:
                logger.info(
                    "🛡️ [诊断-拦截] 挂单数已达上限 (%d/%d)，暂停新挂单",
                    pendingCount, self._settings.maxOrderCount,
                )
                return

            # --- RateLimiter 熔断检查 ---
            if self._rateLimiter.isInCircuitBreaker:
                logger.info("🛡️ [诊断-拦截] 权重熔断中，跳过新买单")
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
                # NOTE 关闭高频打印： logger.info("🛡️ [诊断-拦截] 处于交易冷却期中 (%s 秒前)", currentTime - self._lastTradeTime)
                return

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
        finally:
            self._creation_locks.discard(lock_key)

    async def _placeInitialSellOrder(self, gridIndex: int, sellPrice: Decimal, step: Decimal) -> None:
        """
        在高于现价的网格初始化挂卖单（卖盘区构建）。
        需核对基础资产余额，只有在此前建有底仓（或本身持有代币）时才能挂出。
        """
        lock_key = (gridIndex, GridSide.SELL)
        if lock_key in self._creation_locks:
            return
        self._creation_locks.add(lock_key)

        try:
            assumedBuyPrice = sellPrice - step
            if assumedBuyPrice <= 0: return

            # 计算理论投入和购买量（自适应模式下动态调整投入量）
            baseInvestment = self._settings.gridInvestmentPerGrid
            if self._currentAdjustment:
                baseInvestment = baseInvestment * self._currentAdjustment.investmentMultiplier
                maxInvestment = self._settings.gridInvestmentPerGrid * self._settings.martinMultiplier
                baseInvestment = min(baseInvestment, maxInvestment)

            quantity = baseInvestment / assumedBuyPrice

            # --- 🛡️ 仓位预检查 (无币不可挂卖单) ---
            baseAsset = self._settings.tradingSymbol.replace("USDT", "")
            freeBase = await self._client.getFreeBalance(baseAsset)
            
            if freeBase < quantity:
                # 剩余可用代币已经不足满铺当前这层高位网格，安静撤退不抱错
                return
                
            # --- 🛡️ NOTIONAL (最小下单金额) 保护 ---
            minNotional = self._client._minNotional
            if (quantity * sellPrice) < minNotional:
                if freeBase >= (minNotional * Decimal("1.01") / sellPrice):
                    quantity = (minNotional * Decimal("1.01")) / sellPrice
                else:
                    return
                    
            # 截断到交易所允许的精度
            quantity = Decimal(self._client.formatQuantity(quantity))

            # --- ⏳ 交易冷却拦截器 ---
            currentTime = time.time()
            if currentTime - self._lastTradeTime < self._cooldownSeconds:
                return

            order = await self._client.createLimitOrder(
                side="SELL",
                price=sellPrice,
                quantity=quantity,
            )
            self._lastTradeTime = time.time()

            sellOrder = GridOrder(
                gridIndex=gridIndex,
                price=sellPrice,
                side=GridSide.SELL,
                quantity=quantity,
                orderId=order.get("orderId"),
                status=OrderStatus.PENDING,
                entryPrice=assumedBuyPrice,
            )
            self._orders[sellPrice] = sellOrder
            logger.info("🟡 初始卖盘区建仓: 网格 %d @ %s, 数量 %s", gridIndex, sellPrice, quantity)
            self._notifier.notify(
                f"🟡 卖盘区底仓部署完成\n"
                f"网格 {gridIndex} → 挂卖 @ {sellPrice}\n"
                f"数量: {quantity}"
            )
            self._saveState()

        except Exception as e:
            logger.error("❌ 初始卖单布阵失败 (网格 %d): %s", gridIndex, e)
        finally:
            self._creation_locks.discard(lock_key)

    async def _bootstrapPosition(self, currentPrice: Decimal) -> None:
        """
        [P3] 自动底仓构建逻辑。
        针对当前价格以上的卖盘区网格，预先通过市价单买入所需的 Base Asset，
        确保系统启动后可以直接挂出完整的卖单墙。
        """
        logger.info("🚀 [Bootstrapping] 启动底仓自动构建程序...")
        
        baseAsset = self._settings.tradingSymbol.replace("USDT", "")
        # 计算理论步长
        baseStep = (self._settings.gridUpperPrice - self._settings.gridLowerPrice) / Decimal(str(self._settings.gridCount))
        
        # 1. 计算所有在当前价格之上的网格需要的 Base Asset 总量
        totalBaseNeeded = Decimal("0")
        checkPrice = self._settings.gridLowerPrice
        while checkPrice <= self._settings.gridUpperPrice:
            if checkPrice > currentPrice:
                # 假设买入价为该卖单价减去一个步长
                assumedBuyPrice = checkPrice - baseStep
                if assumedBuyPrice > 0:
                    qty = self._settings.gridInvestmentPerGrid / assumedBuyPrice
                    totalBaseNeeded += qty
            checkPrice += baseStep
            if baseStep <= 0: break
            
        if totalBaseNeeded <= 0:
            logger.info("ℹ️ [Bootstrapping] 当前处于高位，无需额外买入底仓")
            return

        # 2. 检查现有持仓情况
        try:
            freeBase = await self._client.getFreeBalance(baseAsset)
            neededToBuy = totalBaseNeeded - freeBase
        except Exception as e:
            logger.error("❌ [Bootstrapping] 无法获取账户余额: %s", e)
            return

        if neededToBuy <= 0:
            logger.info("✅ [Bootstrapping] 现有底仓 (%s %s) 已满足要求 (需 %s)", freeBase, baseAsset, totalBaseNeeded)
            return

        # 3. 执行市价买入补齐底仓
        logger.warning("🧱 [Bootstrapping] 发现底仓缺口: 需买入 %s %s 以填补高位卖单", neededToBuy, baseAsset)
        
        # 检查 USDT 是否足够执行此次强买
        try:
            freeUSDT = await self._client.getFreeBalance("USDT")
            estimatedCost = neededToBuy * currentPrice * Decimal("1.02") # 加 2% 价格波动缓冲
            if freeUSDT < estimatedCost:
                logger.warning("⚠️ [Bootstrapping] USDT 余额 (%s) 不足以购买所需底仓 (预估需 %s)", freeUSDT, estimatedCost)
                # 如果不够，则有多少买多少，或者直接抛出由于资金不足无法完全挂单的警告
                neededToBuy = freeUSDT / (currentPrice * Decimal("1.02"))
                if neededToBuy <= 0: return

            # 格式化数量
            buyQty = Decimal(self._client.formatQuantity(neededToBuy))
            if buyQty <= 0: return

            logger.info("🛒 [Bootstrapping] 正在通过市价单买入底仓: %s %s ...", buyQty, baseAsset)
            order = await self._client.createMarketOrder(
                side="BUY",
                quantity=buyQty
            )
            logger.info("🔥 [Bootstrapping] 底仓补齐完成! 成交详情: %s", order.get("orderId"))
            self._notifier.notify(
                f"🧱 **底仓自动构建完成**\n"
                f"市价买入: {buyQty} {baseAsset}\n"
                f"用途: 支撑后续高位网格卖单挂出"
            )
        except Exception as e:
            logger.error("❌ [Bootstrapping] 市价买入补仓失败: %s", e)
            self._notifier.notify(f"⚠️ **底仓构建失败**\n原因: {e}")
        finally:
            self._creation_locks.discard(lock_key)

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
        feeAmt = Decimal(event.get("n", "0"))        # 手续费
        feeAsset = event.get("N", "")               # 手续费币种

        # [P3] 实时通知推送：成交通知
        notification_service.send_notification(
            user_id=self.bot_config.user_id,
            title=f"✅ 网格单成交: {self.bot_config.symbol}",
            message=f"策略 [{self.bot_config.name}] 的一笔 {side} 单已成交。\n价格: {filledPrice} | 数量: {filledQty}",
            level=NotificationLevel.SUCCESS,
            data={"bot_id": self.bot_config.id, "order_id": orderId}
        )

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

                # [P3] Redis 广播利润事件，驱动前端金光动画
                try:
                    await redis_bus.publish_trade_event(
                        user_id=self.bot_config.user_id,
                        bot_id=self.bot_config.id,
                        event_type="PROFIT_MATCHED",
                        data={
                            "grid_index": matchedGrid.gridIndex,
                            "sell_price": float(filledPrice),
                            "buy_price": float(matchedGrid.entryPrice),
                            "profit": float(profit),
                            "total_pnl": float(self._realizedProfit),
                            "symbol": self._settings.tradingSymbol
                        }
                    )
                except Exception as e:
                    logger.warning("推送 Redis 利润事件失败: %s", e)

                # 清除已完成的网格订单，允许重新挂单
                del self._orders[matchedGrid.price]
                
                # 同步清除关联的已持仓买单节点，彻底释放该网格
                if matchedGrid.entryPrice and matchedGrid.entryPrice in self._orders:
                    del self._orders[matchedGrid.entryPrice]

        # V3 新增: 原子的短生命周期 DB 事务以落库记录此笔完整成交
        try:
            from src.models.trade import Trade, OrderSide as DBOrderSide, OrderStatus as DBOrderStatus
            from sqlalchemy import update
            async with AsyncSessionLocal() as session:
                # 1. 记录成交明细
                new_trade = Trade(
                    bot_config_id=self.bot_config.id,
                    exchange_order_id=str(orderId) if orderId is not None else "local",
                    symbol=self._settings.tradingSymbol,
                    side=DBOrderSide.BUY if side == "BUY" else DBOrderSide.SELL,
                    price=filledPrice,
                    quantity=filledQty,
                    executed_qty=filledQty,
                    status=DBOrderStatus.FILLED,
                    fee=feeAmt,
                    fee_asset=feeAsset
                )
                session.add(new_trade)
                
                # 2. 如果是卖单成交，同步更新 BotConfig 的 cumulative PnL
                if side == "SELL":
                    await session.execute(
                        update(BotConfig)
                        .where(BotConfig.id == self.bot_config.id)
                        .values(total_pnl=self._realizedProfit)
                    )
                
                await session.commit()
        except Exception as e:
            logger.error("记录 Trade 订单 [bot=%d, orderId=%s] 及 PnL 同步失败: %s", self.bot_config.id, orderId, e)

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
        lock_key = (gridIndex, GridSide.SELL)
        if lock_key in self._creation_locks:
            return
        self._creation_locks.add(lock_key)

        try:
            # 上一级网格价位
            sellGridIndex = gridIndex + 1
            if sellGridIndex >= len(self._gridPrices):
                # 已在最高网格，直接用买入价 + 步长
                step = (self._settings.gridUpperPrice - self._settings.gridLowerPrice) / self._settings.gridCount
                sellPrice = buyPrice + step
            else:
                sellPrice = self._gridPrices[sellGridIndex]

            await asyncio.sleep(0.2)

            # --- ⏳ 交易冷却拦截器 (卖单使用排队等待) ---
            currentTime = time.time()
            timeToWait = self._cooldownSeconds - (currentTime - self._lastTradeTime)
            if timeToWait > 0:
                await asyncio.sleep(timeToWait)

            # --- 🛡️ 仓位预检查 (防止手中无币却盲目触发配对卖出) ---
            baseAsset = self._settings.tradingSymbol.replace("USDT", "")
            freeBase = await self._client.getFreeBalance(baseAsset)
            if freeBase < quantity:
                logger.warning("⚠️ 基础资产 [%s] 余额不足 (%s < %s)，无法全额挂配对卖单。(可能被手动卖出或清仓)", baseAsset, freeBase, quantity)
                quantity = freeBase
                
            # --- 🛡️ NOTIONAL (最小下单金额) 保护 ---
            # 卖单同样需要遵守币安的最小交易额度规则
            minNotional = self._client._minNotional
            if (quantity * sellPrice) < minNotional:
                logger.debug("⚠️ 打算挂卖单金额 (%.4f) 小于最低要求 (%s)", float(quantity * sellPrice), float(minNotional))
                # 对于卖单如果当前仓位连最低卖出都达不到，补足也会因没币而被拒，因此不如跳过不挂单
                if freeBase >= (minNotional * Decimal("1.01") / sellPrice):
                    safeNotional = minNotional * Decimal("1.01")
                    quantity = safeNotional / sellPrice
                else:
                    logger.error("❌ 仓位不足以满足交易所最小挂单金额，放弃挂配对卖单。待人工介入。")
                    return
                
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
        finally:
            self._creation_locks.discard(lock_key)

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
