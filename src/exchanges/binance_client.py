"""
币安交易机器人 — 交易所通信模块

封装币安的 REST API 和 WebSocket 流，提供统一的异步接口。
所有请求自动经过速率限制器拦截，异常自动处理和重试。
"""
import asyncio
import logging
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any

from dataclasses import dataclass
from binance import AsyncClient, BinanceSocketManager
from binance.exceptions import BinanceAPIException

from src.core.config import settings
from src.utils.rate_limiter import RateLimiter
from src.engine.stream_aggregator import stream_aggregator
from src.utils.error_handler import (
    ApiError,
    NetworkError,
    InsufficientBalanceError,
    InvalidOrderError,
    retryOnError,
)

logger = logging.getLogger(__name__)

# NOTE: WebSocket 余额推送超过此时间未更新，视为断线，回退 REST
BALANCE_STALE_TIMEOUT = 3600


def _toBinanceApiError(e: BinanceAPIException, rateLimiter: RateLimiter | None = None) -> ApiError:
    """
    将 python-binance 的异常转换为内部异常体系。
    根据错误码映射到具体子类，便于 retryOnError 装饰器精确处理。
    """
    code = e.code
    status = getattr(e, "status_code", 0)

    # [P3] 核心熔断拦截：429 (Too Many Requests) 或 503 (Service Unavailable)
    if status in (429, 418) or code == -1003:
        if rateLimiter:
            rateLimiter.triggerHardCircuitBreaker(duration=60)
            logger.critical("🚨 [BinanceClient] 收到币安频率限制 (429/1003)，已激活 60s 硬熔断保护")
    
    if code == -2010:
        return InsufficientBalanceError(e.message)
    if code == -1013:
        return InvalidOrderError(e.message)
    return ApiError(code=code, message=e.message)


@dataclass
class ClientConfig:
    apiKey: str
    apiSecret: str
    useTestnet: bool
    tradingSymbol: str
    api_key_id: int = 0
    proxy: str | None = None

class BinanceClient:
    """
    币安交易所客户端。

    提供 REST API 调用（账户查询、下单、撤单）和 WebSocket 订阅
    （实时行情、用户数据流）。所有操作均为异步，经过速率限制。
    支持 V3.0 多账户隔离，基于实例级 ClientConfig 注入凭据。
    """

    def __init__(self, config: ClientConfig, rateLimiter: RateLimiter) -> None:
        self._settings = config
        self._rateLimiter = rateLimiter
        self._client: AsyncClient | None = None
        self._socketManager: BinanceSocketManager | None = None

        # 交易对精度信息缓存
        self._pricePrecision: int = 2
        self._quantityPrecision: int = 6
        self._minNotional: Decimal = Decimal("10")

        # K 线缓存：减少 API 权重消耗
        self._klinesCache: dict[str, tuple[float, list]] = {}
        self._klineCacheTTL: int = 60  # 缓存有效期（秒）

        # 订单 ID 前缀，用于重启后识别自己的挂单
        self._orderIdPrefix = "GRID_V2_"  # 最小下单金额
        self._minQty: Decimal = Decimal("0.000001")

        # 时间偏移量（用于时钟同步）
        self._timeOffset: int = 0

        # 资金账户快照: {asset: free_balance}
        self._balances: dict[str, Decimal] = {}
        self._lastBalanceUpdate: float = 0
        self._lastUserDataEventTime: float = 0
        self._userStreamCallback: Any | None = None

    # ==================================================
    # 生命周期管理
    # ==================================================

    async def connect(self) -> None:
        """
        建立与币安的连接。
        创建 AsyncClient 并加载交易对精度信息。
        """
        logger.info("🔗 正在连接币安 %s ...", "测试网" if self._settings.useTestnet else "主网")

        # NOTE: 支持针对该 Client 级别的独立代理绑定
        requests_params = {"proxy": self._settings.proxy} if self._settings.proxy else None
        
        self._client = await AsyncClient.create(
            api_key=self._settings.apiKey,
            api_secret=self._settings.apiSecret,
            testnet=self._settings.useTestnet,
            requests_params=requests_params,
        )

        # 同步服务器时间
        await self.syncServerTime()

        # 加载交易对精度信息
        await self._loadExchangeInfo()

        # 初始化资金快照 (首次全量从 REST 获取)
        await self._syncBalances()

        # 初始化单例 SocketManager，防止多流并发创建导致竞争
        self._socketManager = BinanceSocketManager(self._client)

        logger.info("✅ 币安连接成功")

    async def disconnect(self) -> None:
        """断开连接，清理资源"""
        if self._socketManager:
            # NOTE: python-binance 的 BinanceSocketManager 没有 stop() 方法。清除引用即可。
            # 增加 hasattr 检查以防未来版本变化或某些特定环境下的意外调用
            if hasattr(self._socketManager, "stop"):
                try:
                    await self._socketManager.stop()
                except Exception:
                    pass
            self._socketManager = None

        if self._client:
            await self._client.close_connection()
            self._client = None
            logger.info("🔌 已断开币安连接并清理 Socket 资源")

    def _ensureConnected(self) -> AsyncClient:
        """检查客户端是否已连接，未连接则抛出异常"""
        if not self._client:
            raise NetworkError("币安客户端未连接，请先调用 connect()")
        return self._client

    # ==================================================
    # 时间同步
    # ==================================================

    async def syncServerTime(self) -> None:
        """
        同步本地时钟与币安服务器时间。
        计算偏移量，后续请求自动使用校准后的时间戳。
        """
        client = self._ensureConnected()

        try:
            await self._rateLimiter.acquireWeight(1)
            serverTime = await client.get_server_time()
            localTime = int(time.time() * 1000)
            self._timeOffset = serverTime["serverTime"] - localTime
            logger.info("🕐 时间同步完成，偏移量: %d ms", self._timeOffset)
        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    # ==================================================
    # 交易对信息
    # ==================================================

    async def _loadExchangeInfo(self) -> None:
        """
        加载交易对精度信息（价格精度、数量精度、最小下单金额）。
        用于后续下单时自动截断数值到允许的精度。
        """
        client = self._ensureConnected()

        try:
            await self._rateLimiter.acquireWeight(10)
            info = await client.get_exchange_info()

            for symbolInfo in info.get("symbols", []):
                if symbolInfo["symbol"] == self._settings.tradingSymbol:
                    for f in symbolInfo["filters"]:
                        if f["filterType"] == "PRICE_FILTER":
                            # NOTE: 从 tickSize 推算价格精度
                            tickSize = Decimal(f["tickSize"])
                            self._pricePrecision = max(0, -tickSize.normalize().as_tuple().exponent)

                        elif f["filterType"] == "LOT_SIZE":
                            stepSizeRaw = f["stepSize"]
                            minQtyRaw = f["minQty"]
                            stepSize = Decimal(stepSizeRaw)
                            self._quantityPrecision = max(0, -stepSize.normalize().as_tuple().exponent)
                            self._minQty = Decimal(minQtyRaw)
                            logger.debug("DEBUG: LOT_SIZE filter: stepSize=%s, minQty=%s, calculated_precision=%d", stepSizeRaw, minQtyRaw, self._quantityPrecision)

                        elif f["filterType"] == "NOTIONAL":
                            self._minNotional = Decimal(f.get("minNotional", "10"))
                            logger.debug("DEBUG: NOTIONAL filter: minNotional=%s", self._minNotional)

                    logger.info(
                        "📊 %s 精度: 价格=%d位, 数量=%d位, 最小金额=%s",
                        self._settings.tradingSymbol,
                        self._pricePrecision,
                        self._quantityPrecision,
                        self._minNotional,
                    )
                    return

            logger.warning("⚠️ 未找到交易对 %s 的精度信息，使用默认值", self._settings.tradingSymbol)

        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    def formatPrice(self, price: Decimal) -> str:
        """将价格截断到交易对允许的精度"""
        quantize = Decimal(10) ** -self._pricePrecision
        return str(price.quantize(quantize, rounding=ROUND_DOWN))

    def formatQuantity(self, quantity: Decimal) -> str:
        """将数量截断到交易对允许的精度"""
        quantize = Decimal(10) ** -self._quantityPrecision
        return str(quantity.quantize(quantize, rounding=ROUND_DOWN))

    @property
    def minNotional(self) -> Decimal:
        return self._minNotional

    @property
    def minQty(self) -> Decimal:
        return self._minQty

    @property
    def tradingSymbol(self) -> str:
        return self._settings.tradingSymbol

    def _normalize_order_side(self, side: str) -> str:
        normalized = str(side or "").upper()
        if normalized not in {"BUY", "SELL"}:
            raise InvalidOrderError("side 必须为 BUY 或 SELL")
        return normalized

    def _assert_trading_allowed(self) -> None:
        settings.assert_trading_allowed(is_testnet=self._settings.useTestnet)

    def _validate_order_values(
        self,
        *,
        side: str,
        quantity: Decimal | None = None,
        price: Decimal | None = None,
        quoteQuantity: Decimal | None = None,
    ) -> tuple[str, Decimal | None, Decimal | None, Decimal | None]:
        normalized_side = self._normalize_order_side(side)

        if quantity is not None and quantity <= 0:
            raise InvalidOrderError("订单数量必须大于 0")

        if quoteQuantity is not None and quoteQuantity <= 0:
            raise InvalidOrderError("quoteOrderQty 必须大于 0")

        if price is not None and price <= 0:
            raise InvalidOrderError("订单价格必须大于 0")

        normalized_quantity = None
        if quantity is not None:
            normalized_quantity = Decimal(self.formatQuantity(quantity))
            if normalized_quantity <= 0:
                raise InvalidOrderError("订单数量格式化后为 0")
            if normalized_quantity < self._minQty:
                raise InvalidOrderError(
                    f"订单数量 {normalized_quantity} 小于交易所最小下单数量 {self._minQty}"
                )

        normalized_price = None
        if price is not None:
            normalized_price = Decimal(self.formatPrice(price))
            if normalized_price <= 0:
                raise InvalidOrderError("订单价格格式化后为 0")

        if normalized_quantity is not None and normalized_price is not None:
            notional = normalized_quantity * normalized_price
            if notional < self._minNotional:
                raise InvalidOrderError(
                    f"订单金额 {notional} 小于交易所最小下单金额 {self._minNotional}"
                )

        if quoteQuantity is not None and quoteQuantity < self._minNotional:
            raise InvalidOrderError(
                f"quoteOrderQty {quoteQuantity} 小于交易所最小下单金额 {self._minNotional}"
            )

        return normalized_side, normalized_quantity, normalized_price, quoteQuantity

    # ==================================================
    # 账户信息
    # ==================================================

    @retryOnError(maxRetries=3, baseDelay=2.0)
    async def getAccountInfo(self) -> dict[str, Any]:
        """
        获取账户余额信息。

        @returns 包含所有资产余额的字典
        """
        client = self._ensureConnected()

        try:
            await self._rateLimiter.acquireWeight(10)
            account = await client.get_account()
            return account
        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    async def getFreeBalance(self, asset: str = "USDT") -> Decimal:
        """
        获取指定资产的可用余额。
        [V3.0 优化] 优先从本地快照读取，废弃高权重 REST 轮询。
        增加过期保护：WebSocket 断线时自动回退 REST 同步。

        @param asset 资产名称
        @returns 可用余额
        """
        # NOTE: 过期保护 — 防止 WebSocket 断线后用僵尸数据做风控决策
        if self._lastBalanceUpdate > 0:
            staleness = time.time() - self._lastBalanceUpdate
            if staleness > BALANCE_STALE_TIMEOUT:
                logger.info(
                    "🔄 余额快照长时间未变更 (%.0f秒)，执行一次 REST 同步确保数据一致性",
                    staleness,
                )
                await self._syncBalances()

        if asset in self._balances:
            return self._balances[asset]
        
        # 如果缓存为空（尚未初始化），回退到一次性 REST 请求并填充缓存
        await self._syncBalances()
        return self._balances.get(asset, Decimal("0"))

    async def _syncBalances(self) -> None:
        """全量同步资金快照 (REST 请求，消耗 10 权重)"""
        try:
            account = await self.getAccountInfo()
            for balance in account.get("balances", []):
                asset = balance["asset"]
                free = Decimal(balance["free"])
                self._balances[asset] = free
            self._lastBalanceUpdate = time.time()
            logger.info("💰 资金快照初始化完成: %s", self._getBalancesSummary())
        except Exception as e:
            logger.error("资金快照初始化失败: %s", e)

    def _getBalancesSummary(self) -> str:
        """生成资金摘要字符串"""
        items = []
        for asset, free in self._balances.items():
            if free > 0:
                items.append(f"{asset}: {free}")
        return ", ".join(items) if items else "无余额"

    def _mark_balance_snapshot_updated(self) -> None:
        self._lastBalanceUpdate = time.time()

    def _update_balance(self, asset: str, free: Any) -> None:
        self._balances[asset] = Decimal(str(free))

    def _handle_user_stream_event(self, event: dict[str, Any]) -> None:
        """
        根据用户流事件增量更新本地余额镜像。
        这样风控计算不必长期依赖初始化时的 REST 快照。
        """
        self._lastUserDataEventTime = time.time()
        event_type = event.get("e") or event.get("eventType")
        updated = False

        try:
            if event_type == "outboundAccountPosition":
                for balance in event.get("B", []):
                    asset = balance.get("a")
                    free = balance.get("f")
                    if asset is None or free is None:
                        continue
                    self._update_balance(asset, free)
                    updated = True

            elif event_type == "balanceUpdate":
                asset = event.get("a")
                delta = event.get("d")
                if asset is not None and delta is not None:
                    self._balances[asset] = self._balances.get(asset, Decimal("0")) + Decimal(str(delta))
                    updated = True

            if updated:
                self._mark_balance_snapshot_updated()
                logger.debug("🔄 用户流余额镜像已更新: %s", self._getBalancesSummary())
        except Exception as e:
            logger.warning("解析用户流余额事件失败: %s | event=%s", e, event)

    # ==================================================
    # 合约 (Futures) API 扩展
    # ==================================================

    @retryOnError(maxRetries=3, baseDelay=2.0)
    async def getFuturesAccountInfo(self) -> dict[str, Any]:
        """获取 U 本位合约账户信息"""
        client = self._ensureConnected()
        try:
            return await client.futures_account()
        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    async def getFuturesPosition(self, symbol: str) -> dict[str, Any]:
        """获取特定交易对的合约持仓信息"""
        client = self._ensureConnected()
        try:
            positions = await client.futures_position_information(symbol=symbol)
            return positions[0] if positions else {}
        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    @retryOnError(maxRetries=2, baseDelay=1.0)
    async def futuresCreateOrder(
        self,
        symbol: str,
        side: str,
        type: str,
        quantity: Decimal,
        price: Decimal | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """创建合约订单"""
        client = self._ensureConnected()
        self._assert_trading_allowed()
        normalized_side, normalized_quantity, normalized_price, _ = self._validate_order_values(
            side=side,
            quantity=quantity,
            price=price,
        )
        params = {
            "symbol": symbol,
            "side": normalized_side,
            "type": type,
            "quantity": self.formatQuantity(normalized_quantity or quantity),
            **kwargs
        }
        if normalized_side == "BUY" and self._rateLimiter.isInCircuitBreaker:
            raise ApiError(code=-1003, message="Rate limiter circuit breaker active for BUY futures orders")

        if normalized_price is not None:
            params["price"] = self.formatPrice(normalized_price)
            params["timeInForce"] = "GTC"

        try:
            await self._rateLimiter.acquireWeight(1)
            return await client.futures_create_order(**params)
        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    # 别名兼容
    futures_create_order = futuresCreateOrder

    # ==================================================
    # 下单操作
    # ==================================================

    @retryOnError(maxRetries=2, baseDelay=1.0)
    async def createLimitOrder(
        self,
        side: str,
        price: Decimal,
        quantity: Decimal,
    ) -> dict[str, Any]:
        """
        创建限价单。

        @param side 方向: 'BUY' 或 'SELL'
        @param price 限价价格
        @param quantity 数量
        @returns 币安返回的订单信息
        """
        client = self._ensureConnected()
        self._assert_trading_allowed()
        normalized_side, normalized_quantity, normalized_price, _ = self._validate_order_values(
            side=side,
            quantity=quantity,
            price=price,
        )

        # 消耗订单速率名额
        await self._rateLimiter.acquireOrderSlot()
        await self._rateLimiter.acquireWeight(1)

        if normalized_side == "BUY" and self._rateLimiter.isInCircuitBreaker:
            raise ApiError(code=-1003, message="Rate limiter circuit breaker active for BUY orders")

        formattedPrice = self.formatPrice(normalized_price or price)
        formattedQty = self.formatQuantity(normalized_quantity or quantity)

        logger.info(
            "📝 挂单: %s %s %s @ %s",
            normalized_side, formattedQty, self._settings.tradingSymbol, formattedPrice,
        )

        try:
            import uuid
            clientOrderId = f"{self._orderIdPrefix}{uuid.uuid4().hex[:16]}"
            order = await client.create_order(
                symbol=self._settings.tradingSymbol,
                side=normalized_side,
                type="LIMIT",
                timeInForce="GTC",
                price=formattedPrice,
                quantity=formattedQty,
                newClientOrderId=clientOrderId,
            )
            logger.info("✅ 订单已创建: orderId=%s", order.get("orderId"))
            return order

        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    @retryOnError(maxRetries=2, baseDelay=1.0)
    async def createMarketOrder(
        self,
        side: str,
        quantity: Decimal | None = None,
        quoteQuantity: Decimal | None = None,
    ) -> dict[str, Any]:
        """
        创建市价单。

        @param side 方向: 'BUY' 或 'SELL'
        @param quantity 基础资产数量（卖出时使用）
        @param quoteQuantity 报价资产金额（买入时使用，如 USDT 金额）
        @returns 币安返回的订单信息
        """
        client = self._ensureConnected()
        self._assert_trading_allowed()

        normalized_side, normalized_quantity, _, normalized_quote_quantity = self._validate_order_values(
            side=side,
            quantity=quantity,
            quoteQuantity=quoteQuantity,
        )

        await self._rateLimiter.acquireOrderSlot()
        await self._rateLimiter.acquireWeight(1)

        params: dict[str, Any] = {
            "symbol": self._settings.tradingSymbol,
            "side": normalized_side,
            "type": "MARKET",
        }

        if normalized_quantity is not None:
            params["quantity"] = self.formatQuantity(normalized_quantity)
        elif normalized_quote_quantity is not None:
            params["quoteOrderQty"] = str(normalized_quote_quantity)
        else:
            raise InvalidOrderError("市价单必须指定 quantity 或 quoteQuantity")

        if normalized_side == "BUY" and self._rateLimiter.isInCircuitBreaker:
            raise ApiError(code=-1003, message="Rate limiter circuit breaker active for BUY orders")

        logger.info(
            "⚡ 市价单: %s %s",
            normalized_side,
            params.get("quantity") or params.get("quoteOrderQty"),
        )

        try:
            order = await client.create_order(**params)
            logger.info("✅ 市价单成交: orderId=%s", order.get("orderId"))
            return order
        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    async def createOrder(
        self,
        symbol: str | None = None,
        side: str = "BUY",
        type: str = "LIMIT",
        quantity: Any = 0,
        price: Any = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        通用下单兼容接口，供旧策略或回测对齐使用。
        当前客户端按单一 symbol 初始化，因此不允许跨 symbol 下单。
        """
        target_symbol = symbol or self._settings.tradingSymbol
        if target_symbol != self._settings.tradingSymbol:
            raise InvalidOrderError(
                f"当前客户端仅支持交易对 {self._settings.tradingSymbol}，不支持下单到 {target_symbol}"
            )

        order_type = str(type or "LIMIT").upper()
        normalized_quantity = Decimal(str(quantity)) if quantity is not None else None
        normalized_price = Decimal(str(price)) if price is not None else None

        quote_quantity = kwargs.get("quoteQuantity", kwargs.get("quoteOrderQty"))
        normalized_quote_quantity = (
            Decimal(str(quote_quantity)) if quote_quantity is not None else None
        )

        if order_type == "MARKET":
            return await self.createMarketOrder(
                side=side,
                quantity=normalized_quantity,
                quoteQuantity=normalized_quote_quantity,
            )

        if order_type == "LIMIT":
            if normalized_price is None:
                raise InvalidOrderError("限价单必须指定 price")
            if normalized_quantity is None:
                raise InvalidOrderError("限价单必须指定 quantity")
            return await self.createLimitOrder(
                side=side,
                price=normalized_price,
                quantity=normalized_quantity,
            )

        raise InvalidOrderError(f"不支持的订单类型: {order_type}")

    create_order = createOrder

    # ==================================================
    # 撤单操作
    # ==================================================

    @retryOnError(maxRetries=2, baseDelay=1.0)
    async def cancelOrder(self, orderId: int) -> dict[str, Any]:
        """
        撤销指定订单。

        @param orderId 要撤销的订单 ID
        @returns 撤单结果
        """
        client = self._ensureConnected()

        await self._rateLimiter.acquireWeight(1)

        try:
            result = await client.cancel_order(
                symbol=self._settings.tradingSymbol,
                orderId=orderId,
            )
            logger.info("🗑️ 已撤单: orderId=%s", orderId)
            return result
        except BinanceAPIException as e:
            # 订单已成交或不存在时，不视为错误
            if e.code == -2011:
                logger.warning("⚠️ 订单 %s 已不存在或已成交", orderId)
                return {"orderId": orderId, "status": "UNKNOWN"}
            raise _toBinanceApiError(e, self._rateLimiter)

    @retryOnError(maxRetries=2, baseDelay=1.0)
    async def cancelAllOrders(self) -> list[dict[str, Any]]:
        """撤销当前交易对的所有挂单"""
        client = self._ensureConnected()

        await self._rateLimiter.acquireWeight(1)

        try:
            result = await client.cancel_all_open_orders(
                symbol=self._settings.tradingSymbol,
            )
            logger.info("🗑️ 已撤销所有挂单 (%d 个)", len(result) if isinstance(result, list) else 0)
            return result if isinstance(result, list) else []
        except BinanceAPIException as e:
            # 如果当前没有挂单，部分 API 可能会返回 -2011，视为正常
            if e.code == -2011:
                logger.info("ℹ️ 当前账户无活跃挂单，无需撤销")
                return []
            raise _toBinanceApiError(e, self._rateLimiter)

    async def nuke_all_orders(self, symbol: str | None = None) -> None:
        """
        一键撤销该币种所有挂单 (清场专用)
        直接通过 get_open_orders 获取订单后执行批量撤销。
        """
        target_symbol = symbol or self._settings.tradingSymbol
        client = self._ensureConnected()
        try:
            await self._rateLimiter.acquireWeight(3)
            orders = await client.get_open_orders(symbol=target_symbol)
            if orders:
                logger.warning("🧹 发现 %d 个遗留订单，正在全数撤销...", len(orders))
                await self._rateLimiter.acquireWeight(1)
                await client.cancel_all_open_orders(symbol=target_symbol)
                logger.info("✅ 战场清理完成")
            else:
                logger.info("ℹ️ 当前账户无活跃挂单，无需清理")
        except Exception as e:
            logger.error("❌ 清理订单失败: %s", e)

    async def cancelFarOrders(
        self,
        currentPrice: Decimal,
        threshold: Decimal = Decimal("0.05"),
    ) -> int:
        """
        智能撤单：撤销偏离当前价格超过 threshold (如 5%) 的挂单。
        保留核心交易区的挂单，减少 API 权重消耗。

        @param currentPrice 当前市场价格
        @param threshold 偏离阈值百分比
        @returns 撤销的订单数量
        """
        openOrders = await self.getOpenOrders()
        cancelCount = 0

        for order in openOrders:
            try:
                orderPrice = Decimal(order["price"])
                deviation = abs(orderPrice - currentPrice) / currentPrice

                if deviation > threshold:
                    logger.debug(
                        "🧠 智能撤单: 价格偏离过大 (%.1f%% > %.1f%%), orderId=%s",
                        float(deviation * 100), float(threshold * 100), order.get("orderId")
                    )
                    await self.cancelOrder(int(order["orderId"]))
                    cancelCount += 1
            except Exception as e:
                logger.error("撤销订单失败: %s", e)

        if cancelCount > 0:
            logger.info("🧠 智能撤单完成: 共撤销 %d 个远端订单", cancelCount)

        return cancelCount

    # ==================================================
    # 查询操作
    # ==================================================

    @retryOnError(maxRetries=3, baseDelay=1.0)
    async def getOpenOrders(self) -> list[dict[str, Any]]:
        """获取当前交易对所有未成交挂单"""
        client = self._ensureConnected()

        await self._rateLimiter.acquireWeight(3)

        try:
            orders = await client.get_open_orders(
                symbol=self._settings.tradingSymbol,
            )
            return orders
        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    @retryOnError(maxRetries=3, baseDelay=1.0)
    async def getOrderBook(self, limit: int = 5) -> dict[str, Any]:
        """
        获取订单簿（买卖盘口），用于计算 Bid-Ask Spread。

        @param limit 档位数量
        @returns 包含 bids 和 asks 的字典
        """
        client = self._ensureConnected()

        await self._rateLimiter.acquireWeight(5)

        try:
            book = await client.get_order_book(
                symbol=self._settings.tradingSymbol,
                limit=limit,
            )
            return book
        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    async def getBidAskSpread(self) -> Decimal:
        """
        计算当前买卖盘口价差（Bid-Ask Spread）。

        @returns 价差占中间价的比例
        """
        book = await self.getOrderBook(limit=1)
        if not book.get("bids") or not book.get("asks"):
            return Decimal("1")  # 无盘口数据时返回极大值，触发暂停

        bestBid = Decimal(book["bids"][0][0])
        bestAsk = Decimal(book["asks"][0][0])
        midPrice = (bestBid + bestAsk) / 2

        if midPrice == 0:
            return Decimal("1")

        spread = (bestAsk - bestBid) / midPrice
        return spread

    @retryOnError(maxRetries=3)
    async def getKlines(
        self,
        interval: str = "1h",
        limit: int = 50,
        symbol: str | None = None,
    ) -> list[list]:
        """
        获取 K 线历史数据（带缓存）。
        相同参数 60 秒内不重复请求，减少 API 权重消耗。

        @param interval K 线周期
        @param limit 获取数量
        @param symbol 可选交易对 (默认使用初始化时的交易对)
        @returns K 线数据列表
        """
        target_symbol = symbol or self._settings.tradingSymbol
        import time as _time
        cacheKey = f"{target_symbol}_{interval}_{limit}"
        now = _time.time()

        # 检查缓存
        if cacheKey in self._klinesCache:
            cachedTime, cachedData = self._klinesCache[cacheKey]
            if now - cachedTime < self._klineCacheTTL:
                logger.debug("✅ K 线缓存命中: %s (%.0f秒前)", cacheKey, now - cachedTime)
                return cachedData

        client = self._ensureConnected()
        try:
            await self._rateLimiter.acquireWeight(1)
            klines = await client.get_klines(
                symbol=target_symbol,
                interval=interval,
                limit=limit,
            )
            # 更新缓存
            self._klinesCache[cacheKey] = (now, klines)
            logger.debug("获取 %s %d 根 %s K 线 (已缓存)", target_symbol, len(klines), interval)
            return klines
        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    # 别名兼容：某些策略可能使用 snake_case 调用
    get_klines = getKlines
    getKlinesHistorical = getKlines

    async def getCurrentPrice(self, symbol: str | None = None) -> Decimal:
        """
        获取当前市场价格。
        [权重 1]
        """
        target_symbol = symbol or self._settings.tradingSymbol
        client = self._ensureConnected()
        try:
            await self._rateLimiter.acquireWeight(1)
            ticker = await client.get_symbol_ticker(symbol=target_symbol)
            return Decimal(ticker["price"])
        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    # 别名兼容
    get_current_price = getCurrentPrice

    @retryOnError(maxRetries=2)
    async def getOpenOrdersCount(self) -> int:
        """
        获取当前交易对的挂单数量。
        """
        client = self._ensureConnected()
        try:
            await self._rateLimiter.acquireWeight(3)
            orders = await client.get_open_orders(
                symbol=self._settings.tradingSymbol,
            )
            return len(orders)
        except BinanceAPIException as e:
            raise _toBinanceApiError(e, self._rateLimiter)

    async def getTotalPositionValue(self, currentPrice: Decimal = Decimal("0")) -> tuple[Decimal, Decimal]:
        """
        获取当前持仓价值和总资产价值。
        [V3.0 优化] 使用本地资金快照。

        @param currentPrice 提供最新市场价，若为 0 则尝试从 ticker 获取（会消耗 1 权重）
        @returns (positionValue, totalValue) 以 USDT 计价
        """
        baseAsset = self._settings.tradingSymbol.replace("USDT", "")
        baseFree = await self.getFreeBalance(baseAsset)
        usdtFree = await self.getFreeBalance("USDT")

        # 如果未提供价格，则回退到 REST 请求 (1 权重)
        if currentPrice == 0:
            try:
                client = self._ensureConnected()
                await self._rateLimiter.acquireWeight(1)
                ticker = await client.get_symbol_ticker(symbol=self._settings.tradingSymbol)
                currentPrice = Decimal(ticker["price"])
            except Exception:
                currentPrice = Decimal("0")

        positionValue = baseFree * currentPrice
        totalValue = usdtFree + positionValue

        return positionValue, totalValue

    async def _is_client_alive(self) -> bool:
        """极低权重 (1) 测试连接是否依然处于 Session 激活态"""
        if not self._client: return False
        try:
            await self._client.get_server_time()
            return True
        except Exception:
            return False

    # ==================================================
    # WebSocket 流
    # ==================================================

    async def startTradeStream(
        self,
        onPrice: Any,
    ) -> None:
        """
        启动实时成交价格 WebSocket 流 (接入 P4 聚合器模式)。
        """
        symbol = self._settings.tradingSymbol
        logger.info("📡 [Aggregator-Client] 正在向聚合器订阅行情: %s", symbol)

        try:
            # 订阅全局单例聚合器
            await stream_aggregator.subscribe_market(symbol, onPrice, is_testnet=self._settings.useTestnet)
            
            # 挂起当前协程，直到 bot 任务被 Cancel
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            logger.info("🛑 [Aggregator-Client] 正在退订行情流: %s", symbol)
            await stream_aggregator.unsubscribe_market(symbol, onPrice, is_testnet=self._settings.useTestnet)
            raise
        except Exception as e:
            logger.error("❌ 行情流桥接异常: %s", e)
            raise

    async def startUserDataStream(
        self,
        onOrderUpdate: Any,
    ) -> None:
        """
        启动用户数据流 WebSocket (接入 P4 聚合器模式)。
        """
        api_key_id = getattr(self._settings, "api_key_id", 0)

        logger.info("📡 [Aggregator-Client] 正在向聚合器订阅用户流: KeyID %s", api_key_id)

        async def _callback(event: dict[str, Any]) -> None:
            self._handle_user_stream_event(event)
            result = onOrderUpdate(event)
            if asyncio.iscoroutine(result):
                await result

        self._userStreamCallback = _callback

        try:
            await stream_aggregator.subscribe_user_data(
                api_key_id=api_key_id,
                api_key=self._settings.apiKey,
                api_secret=self._settings.apiSecret,
                is_testnet=self._settings.useTestnet,
                callback=self._userStreamCallback,
            )

            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            logger.info("🛑 [Aggregator-Client] 正在退订用户流: KeyID %s", api_key_id)
            if self._userStreamCallback is not None:
                await stream_aggregator.unsubscribe_user_data(
                    api_key_id,
                    self._userStreamCallback,
                )
            self._userStreamCallback = None
            raise
        except Exception as e:
            logger.error("❌ 用户流桥接异常: %s", e)
            raise
