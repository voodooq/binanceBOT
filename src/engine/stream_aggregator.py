import asyncio
import logging
import json
from decimal import Decimal
from typing import Dict, List, Set, Callable, Any, Optional

from binance import AsyncClient, BinanceSocketManager
from src.core.config import settings

logger = logging.getLogger(__name__)

class StreamAggregator:
    """
    WebSocket 流聚合器。
    
    1. 行情聚合 (Market Aggregator): 多 Bot 共享同一个 Symbol 的 Ticker 流。
    2. 用户流聚合 (User Stream Aggregator): 同一 API Key 的 Bot 共享同一个 UserData 流。
    """
    
    def __init__(self):
        self._public_clients: Dict[bool, Optional[AsyncClient]] = {False: None, True: None}
        self._socket_managers: Dict[bool, Optional[BinanceSocketManager]] = {False: None, True: None}
        
        # 行情订阅: { (symbol, is_testnet): { "callbacks": set(), "task": Task } }
        self._market_subscriptions: Dict[tuple[str, bool], Dict[str, Any]] = {}
        
        # 用户流订阅: { api_key_id: { "callbacks": set(), "task": Task, "client": AsyncClient } }
        self._user_subscriptions: Dict[int, Dict[str, Any]] = {}
        
        self._lock = asyncio.Lock()

    async def _ensure_public_client(self, is_testnet: bool):
        """延迟初始化公共行情客户端"""
        if not self._public_clients[is_testnet]:
            client = await AsyncClient.create(testnet=is_testnet)
            self._public_clients[is_testnet] = client
            self._socket_managers[is_testnet] = BinanceSocketManager(client)

    async def subscribe_market(self, symbol: str, callback: Callable[[Decimal], Any], is_testnet: bool = False):
        """订阅公共行情流 (Ticker)"""
        async with self._lock:
            await self._ensure_public_client(is_testnet)
            symbol = symbol.lower()
            key = (symbol, is_testnet)
            
            if key not in self._market_subscriptions:
                logger.info(f"📡 [Aggregator] 开启新行情流: {symbol} (Testnet: {is_testnet})")
                task = asyncio.create_task(self._market_loop(symbol, is_testnet))
                self._market_subscriptions[key] = {
                    "callbacks": {callback},
                    "task": task
                }
            else:
                self._market_subscriptions[key]["callbacks"].add(callback)
                logger.info(f"🔗 [Aggregator] 共享现有行情流: {symbol} (订阅数: {len(self._market_subscriptions[key]['callbacks'])})")

    async def unsubscribe_market(self, symbol: str, callback: Callable, is_testnet: bool = False):
        """取消行情订阅"""
        async with self._lock:
            symbol = symbol.lower()
            key = (symbol, is_testnet)
            if key in self._market_subscriptions:
                self._market_subscriptions[key]["callbacks"].discard(callback)
                if not self._market_subscriptions[key]["callbacks"]:
                    logger.info(f"🛑 [Aggregator] 无订阅者，正在销毁行情流: {symbol}")
                    task = self._market_subscriptions[key]["task"]
                    task.cancel()
                    del self._market_subscriptions[key]

    async def _market_loop(self, symbol: str, is_testnet: bool):
        """行情推送主循环"""
        try:
            sm = self._socket_managers[is_testnet]
            res_socket = sm.symbol_ticker_socket(symbol=symbol)
            key = (symbol, is_testnet)
            async with res_socket as stream:
                while True:
                    msg = await stream.recv()
                    if not msg or "c" not in msg:
                        continue
                        
                    price = Decimal(msg["c"])
                    # 分发给所有回调
                    callbacks = self._market_subscriptions.get(key, {}).get("callbacks", set())
                    for cb in list(callbacks):
                        try:
                            if asyncio.iscoroutinefunction(cb):
                                asyncio.create_task(cb(price))
                            else:
                                cb(price)
                        except Exception as e:
                            logger.error(f"Market Callback Error [{symbol}]: {e}")
                            
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Market Loop Crash [{symbol}]: {e}")

    # --- User Data Stream Section ---

    async def subscribe_user_data(self, api_key_id: int, api_key: str, api_secret: str, is_testnet: bool, callback: Callable):
        """订阅用户数据流 (鉴权)"""
        async with self._lock:
            if api_key_id not in self._user_subscriptions:
                logger.info(f"🔐 [Aggregator] 开启用户私有流: KeyID {api_key_id}")
                
                client = await AsyncClient.create(api_key=api_key, api_secret=api_secret, testnet=is_testnet)
                bm = BinanceSocketManager(client)
                task = asyncio.create_task(self._user_loop(api_key_id, bm, client))
                
                self._user_subscriptions[api_key_id] = {
                    "callbacks": {callback},
                    "task": task,
                    "client": client,
                    "bm": bm
                }
            else:
                self._user_subscriptions[api_key_id]["callbacks"].add(callback)
                logger.info(f"🔗 [Aggregator] 共享用户私有流: KeyID {api_key_id}")

    async def unsubscribe_user_data(self, api_key_id: int, callback: Callable):
        """取消用户流订阅"""
        async with self._lock:
            if api_key_id in self._user_subscriptions:
                self._user_subscriptions[api_key_id]["callbacks"].discard(callback)
                if not self._user_subscriptions[api_key_id]["callbacks"]:
                    logger.info(f"🛑 [Aggregator] 无订阅者，正在销毁用户流: {api_key_id}")
                    task = self._user_subscriptions[api_key_id]["task"]
                    client = self._user_subscriptions[api_key_id]["client"]
                    task.cancel()
                    await client.close_connection()
                    del self._user_subscriptions[api_key_id]

    async def _user_loop(self, api_key_id: int, bm: BinanceSocketManager, client: AsyncClient):
        """用户数据推送主循环"""
        try:
            user_socket = bm.user_socket()
            async with user_socket as stream:
                while True:
                    msg = await stream.recv()
                    if not msg:
                        continue
                    
                    # 分发给所有对该 Key 感兴趣的 Bot
                    callbacks = self._user_subscriptions.get(api_key_id, {}).get("callbacks", set())
                    for cb in list(callbacks):
                        try:
                            if asyncio.iscoroutinefunction(cb):
                                asyncio.create_task(cb(msg))
                            else:
                                cb(msg)
                        except Exception as e:
                            logger.error(f"User Stream Callback Error [{api_key_id}]: {e}")
                            
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"User Stream Loop Crash [{api_key_id}]: {e}")

    async def stop(self):
        """停机清理"""
        async with self._lock:
            for sub in self._market_subscriptions.values():
                sub["task"].cancel()
            for sub in self._user_subscriptions.values():
                sub["task"].cancel()
                await sub["client"].close_connection()
            
            for client in self._public_clients.values():
                if client:
                    await client.close_connection()
            
            self._market_subscriptions.clear()
            self._user_subscriptions.clear()
            logger.info("🏁 [Aggregator] 全局流聚合中心已下线")

stream_aggregator = StreamAggregator()
