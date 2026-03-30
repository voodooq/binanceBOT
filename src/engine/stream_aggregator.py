import asyncio
import logging
from decimal import Decimal
from typing import Any, Callable, Dict, Optional

from binance import AsyncClient, BinanceSocketManager

logger = logging.getLogger(__name__)

MAX_RECONNECT_DELAY = 30


class StreamAggregator:
    """
    WebSocket 流聚合器。

    1. 行情聚合 (Market Aggregator): 多 Bot 共享同一个 Symbol 的 Ticker 流。
    2. 用户流聚合 (User Stream Aggregator): 同一 API Key 的 Bot 共享同一个 UserData 流。
    """

    def __init__(self):
        self._public_clients: Dict[bool, Optional[AsyncClient]] = {
            False: None,
            True: None,
        }
        self._socket_managers: Dict[bool, Optional[BinanceSocketManager]] = {
            False: None,
            True: None,
        }

        # 行情订阅: { (symbol, is_testnet): { "callbacks": set(), "task": Task } }
        self._market_subscriptions: Dict[tuple[str, bool], Dict[str, Any]] = {}

        # 用户流订阅:
        # {
        #   api_key_id: {
        #       "callbacks": set(),
        #       "task": Task,
        #       "client": AsyncClient,
        #       "bm": BinanceSocketManager,
        #       "api_key": str,
        #       "api_secret": str,
        #       "is_testnet": bool
        #   }
        # }
        self._user_subscriptions: Dict[int, Dict[str, Any]] = {}

        self._lock = asyncio.Lock()

    async def _ensure_public_client(self, is_testnet: bool):
        """延迟初始化公共行情客户端"""
        if not self._public_clients[is_testnet]:
            client = await AsyncClient.create(testnet=is_testnet)
            self._public_clients[is_testnet] = client
            self._socket_managers[is_testnet] = BinanceSocketManager(client)

    async def _dispatch_callback(self, callback: Callable, payload: Any, tag: str) -> None:
        try:
            result = callback(payload)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception as e:
            logger.error("%s: %s", tag, e)

    async def _get_market_callbacks(
        self, key: tuple[str, bool]
    ) -> tuple[Callable[[Decimal], Any], ...]:
        async with self._lock:
            subscription = self._market_subscriptions.get(key)
            if not subscription:
                return ()
            return tuple(subscription.get("callbacks", set()))

    async def _get_user_callbacks(self, api_key_id: int) -> tuple[Callable, ...]:
        async with self._lock:
            subscription = self._user_subscriptions.get(api_key_id)
            if not subscription:
                return ()
            return tuple(subscription.get("callbacks", set()))

    async def subscribe_market(
        self,
        symbol: str,
        callback: Callable[[Decimal], Any],
        is_testnet: bool = False,
    ):
        """订阅公共行情流 (Ticker)"""
        async with self._lock:
            await self._ensure_public_client(is_testnet)
            symbol = symbol.lower()
            key = (symbol, is_testnet)
            existing = self._market_subscriptions.get(key)

            if not existing or existing["task"].done():
                callbacks = set(existing.get("callbacks", set())) if existing else set()
                callbacks.add(callback)

                logger.info(
                    "📡 [Aggregator] 开启新行情流: %s (Testnet: %s)",
                    symbol,
                    is_testnet,
                )
                task = asyncio.create_task(
                    self._market_loop(symbol, is_testnet),
                    name=f"market_stream_{symbol}_{'testnet' if is_testnet else 'mainnet'}",
                )
                self._market_subscriptions[key] = {
                    "callbacks": callbacks,
                    "task": task,
                }
            else:
                existing["callbacks"].add(callback)
                logger.info(
                    "🔗 [Aggregator] 共享现有行情流: %s (订阅数: %d)",
                    symbol,
                    len(existing["callbacks"]),
                )

    async def unsubscribe_market(
        self, symbol: str, callback: Callable, is_testnet: bool = False
    ):
        """取消行情订阅"""
        task_to_cancel: asyncio.Task | None = None

        async with self._lock:
            symbol = symbol.lower()
            key = (symbol, is_testnet)
            if key in self._market_subscriptions:
                self._market_subscriptions[key]["callbacks"].discard(callback)
                if not self._market_subscriptions[key]["callbacks"]:
                    logger.info("🛑 [Aggregator] 无订阅者，正在销毁行情流: %s", symbol)
                    task_to_cancel = self._market_subscriptions[key]["task"]
                    del self._market_subscriptions[key]

        if task_to_cancel:
            task_to_cancel.cancel()
            await asyncio.gather(task_to_cancel, return_exceptions=True)

    async def _market_loop(self, symbol: str, is_testnet: bool):
        """行情推送主循环，异常后自动重连。"""
        key = (symbol, is_testnet)
        backoff = 1

        while True:
            callbacks = await self._get_market_callbacks(key)
            if not callbacks:
                logger.info("🏁 [Aggregator] 行情流退出: %s", symbol)
                return

            try:
                await self._ensure_public_client(is_testnet)
                sm = self._socket_managers[is_testnet]
                if sm is None:
                    raise RuntimeError("BinanceSocketManager 未初始化")

                logger.info("▶️ [Aggregator] 行情流已连接: %s", symbol)
                res_socket = sm.symbol_ticker_socket(symbol=symbol)

                async with res_socket as stream:
                    backoff = 1
                    while True:
                        msg = await stream.recv()
                        if not msg or "c" not in msg:
                            continue

                        callbacks = await self._get_market_callbacks(key)
                        if not callbacks:
                            logger.info("🏁 [Aggregator] 行情流无订阅者，停止分发: %s", symbol)
                            return

                        price = Decimal(str(msg["c"]))
                        for cb in callbacks:
                            await self._dispatch_callback(
                                cb,
                                price,
                                f"Market Callback Error [{symbol}]",
                            )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                callbacks = await self._get_market_callbacks(key)
                if not callbacks:
                    logger.info("🏁 [Aggregator] 行情流已撤销，无需重连: %s", symbol)
                    return

                logger.warning(
                    "⚠️ [Aggregator] 行情流断开 [%s]，%d 秒后重连: %s",
                    symbol,
                    backoff,
                    e,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_RECONNECT_DELAY)

    # --- User Data Stream Section ---

    async def subscribe_user_data(
        self,
        api_key_id: int,
        api_key: str,
        api_secret: str,
        is_testnet: bool,
        callback: Callable,
    ):
        """订阅用户数据流 (鉴权)"""
        async with self._lock:
            existing = self._user_subscriptions.get(api_key_id)

            if not existing or existing["task"].done():
                if existing and existing.get("client"):
                    try:
                        await existing["client"].close_connection()
                    except Exception:
                        logger.debug("关闭旧用户流客户端失败: KeyID %s", api_key_id)

                logger.info("🔐 [Aggregator] 开启用户私有流: KeyID %s", api_key_id)

                client = await AsyncClient.create(
                    api_key=api_key,
                    api_secret=api_secret,
                    testnet=is_testnet,
                )
                bm = BinanceSocketManager(client)
                callbacks = set(existing.get("callbacks", set())) if existing else set()
                callbacks.add(callback)

                task = asyncio.create_task(
                    self._user_loop(api_key_id),
                    name=f"user_stream_{api_key_id}",
                )

                self._user_subscriptions[api_key_id] = {
                    "callbacks": callbacks,
                    "task": task,
                    "client": client,
                    "bm": bm,
                    "api_key": api_key,
                    "api_secret": api_secret,
                    "is_testnet": is_testnet,
                }
            else:
                existing["callbacks"].add(callback)
                logger.info("🔗 [Aggregator] 共享用户私有流: KeyID %s", api_key_id)

    async def unsubscribe_user_data(self, api_key_id: int, callback: Callable):
        """取消用户流订阅"""
        task_to_cancel: asyncio.Task | None = None
        client_to_close: AsyncClient | None = None

        async with self._lock:
            if api_key_id in self._user_subscriptions:
                self._user_subscriptions[api_key_id]["callbacks"].discard(callback)
                if not self._user_subscriptions[api_key_id]["callbacks"]:
                    logger.info("🛑 [Aggregator] 无订阅者，正在销毁用户流: %s", api_key_id)
                    task_to_cancel = self._user_subscriptions[api_key_id]["task"]
                    client_to_close = self._user_subscriptions[api_key_id]["client"]
                    del self._user_subscriptions[api_key_id]

        if task_to_cancel:
            task_to_cancel.cancel()
            await asyncio.gather(task_to_cancel, return_exceptions=True)

        if client_to_close:
            try:
                await client_to_close.close_connection()
            except Exception:
                logger.debug("关闭用户流客户端失败: KeyID %s", api_key_id)

    async def _keepalive_user_stream(self, api_key_id: int, client: AsyncClient):
        """Listen Key 自动保活任务"""
        try:
            while True:
                await asyncio.sleep(1800)  # 每 30 分钟续期一次
                try:
                    logger.debug("🔄 [Aggregator] 正在续期 Listen Key: KeyID %s", api_key_id)
                    await client.start_user_data_stream()
                    logger.debug("✅ [Aggregator] Listen Key 续期成功: KeyID %s", api_key_id)
                except Exception as e:
                    logger.error(
                        "⚠️ [Aggregator] Listen Key 单次续期异常，将在下个周期重试 [KeyID: %s]: %s",
                        api_key_id,
                        e,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(
                "❌ [Aggregator] Listen Key 核心保活协程崩溃 [KeyID: %s]: %s",
                api_key_id,
                e,
            )

    async def _recreate_user_client(self, api_key_id: int) -> None:
        """用户流异常后重建客户端连接。"""
        async with self._lock:
            entry = self._user_subscriptions.get(api_key_id)
            if not entry:
                return

            api_key = entry["api_key"]
            api_secret = entry["api_secret"]
            is_testnet = entry["is_testnet"]

        new_client = await AsyncClient.create(
            api_key=api_key,
            api_secret=api_secret,
            testnet=is_testnet,
        )
        new_bm = BinanceSocketManager(new_client)

        old_client: AsyncClient | None = None
        async with self._lock:
            entry = self._user_subscriptions.get(api_key_id)
            if not entry:
                await new_client.close_connection()
                return

            old_client = entry.get("client")
            entry["client"] = new_client
            entry["bm"] = new_bm

        if old_client:
            try:
                await old_client.close_connection()
            except Exception:
                logger.debug("关闭旧用户流连接失败: KeyID %s", api_key_id)

    async def _user_loop(self, api_key_id: int):
        """用户数据推送主循环，异常后自动重连。"""
        backoff = 1

        while True:
            callbacks = await self._get_user_callbacks(api_key_id)
            if not callbacks:
                logger.info("🏁 [Aggregator] 用户流退出: KeyID %s", api_key_id)
                return

            async with self._lock:
                entry = self._user_subscriptions.get(api_key_id)
                client = entry.get("client") if entry else None
                bm = entry.get("bm") if entry else None

            if not client or not bm:
                logger.warning("⚠️ [Aggregator] 用户流缺少连接上下文，准备重建: KeyID %s", api_key_id)
                await self._recreate_user_client(api_key_id)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_RECONNECT_DELAY)
                continue

            keepalive = asyncio.create_task(
                self._keepalive_user_stream(api_key_id, client),
                name=f"user_stream_keepalive_{api_key_id}",
            )

            try:
                logger.info("▶️ [Aggregator] 用户流已连接: KeyID %s", api_key_id)
                user_socket = bm.user_socket()

                async with user_socket as stream:
                    backoff = 1
                    while True:
                        msg = await stream.recv()
                        if not msg:
                            continue

                        callbacks = await self._get_user_callbacks(api_key_id)
                        if not callbacks:
                            logger.info(
                                "🏁 [Aggregator] 用户流无订阅者，停止分发: KeyID %s",
                                api_key_id,
                            )
                            return

                        for cb in callbacks:
                            await self._dispatch_callback(
                                cb,
                                msg,
                                f"User Stream Callback Error [{api_key_id}]",
                            )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                callbacks = await self._get_user_callbacks(api_key_id)
                if not callbacks:
                    logger.info("🏁 [Aggregator] 用户流已撤销，无需重连: KeyID %s", api_key_id)
                    return

                logger.warning(
                    "⚠️ [Aggregator] 用户流断开 [KeyID: %s]，%d 秒后重连: %s",
                    api_key_id,
                    backoff,
                    e,
                )
            finally:
                keepalive.cancel()
                await asyncio.gather(keepalive, return_exceptions=True)

            callbacks = await self._get_user_callbacks(api_key_id)
            if not callbacks:
                logger.info("🏁 [Aggregator] 用户流已无订阅者: KeyID %s", api_key_id)
                return

            await self._recreate_user_client(api_key_id)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_RECONNECT_DELAY)

    async def stop(self):
        """停机清理"""
        async with self._lock:
            market_tasks = [
                sub["task"]
                for sub in self._market_subscriptions.values()
                if sub.get("task") is not None
            ]
            user_tasks = [
                sub["task"]
                for sub in self._user_subscriptions.values()
                if sub.get("task") is not None
            ]
            user_clients = [
                sub["client"]
                for sub in self._user_subscriptions.values()
                if sub.get("client") is not None
            ]
            public_clients = [
                client
                for client in self._public_clients.values()
                if client is not None
            ]

            self._market_subscriptions.clear()
            self._user_subscriptions.clear()
            self._public_clients = {False: None, True: None}
            self._socket_managers = {False: None, True: None}

        for task in [*market_tasks, *user_tasks]:
            task.cancel()
        if market_tasks or user_tasks:
            await asyncio.gather(*market_tasks, *user_tasks, return_exceptions=True)

        for client in user_clients:
            try:
                await client.close_connection()
            except Exception:
                logger.debug("关闭用户流客户端失败")

        for client in public_clients:
            try:
                await client.close_connection()
            except Exception:
                logger.debug("关闭公共行情客户端失败")

        logger.info("🏁 [Aggregator] 全局流聚合中心已下线")


stream_aggregator = StreamAggregator()