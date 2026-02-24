import asyncio
import json
import logging
from typing import Callable, Coroutine

from redis.asyncio.client import PubSub

from src.db.session import redis_client
from src.engine.strategy_manager import strategy_manager
from src.engine.ws_hub import ws_hub

logger = logging.getLogger(__name__)

class RedisEventBus:
    """
    负责订阅跨进程级的指令 (如外部 Web 发出的强制停机指令 / 熔断系统广播)。
    """
    KILL_SWITCH_CHANNEL = "global:kill_switch"

    def __init__(self):
        self._pubsub: PubSub | None = None
        self._listener_task: asyncio.Task | None = None

    async def start(self):
        """连入 Redis 并挂载订阅"""
        # NOTE: 直接使用模块级单例，而非 FastAPI 依赖注入专用的 get_redis() 生成器
        self._pubsub = redis_client.pubsub()
        await self._pubsub.subscribe(self.KILL_SWITCH_CHANNEL)
        logger.info(f"[RedisEventBus] Subscribed to '{self.KILL_SWITCH_CHANNEL}'")
        
        # 启动后台守护任务循环读消息
        self._listener_task = asyncio.create_task(self._listen_loop())

    async def stop(self):
        if self._listener_task:
            self._listener_task.cancel()
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe()
                await self._pubsub.close()
            except Exception as e:
                # 当 supervisor 同时停止所有进程时，redis 可能已经先退出，这里静默处理即可
                logger.debug(f"[RedisEventBus] 退出时断开订阅失败 (Redis可能已下线): {e}")
        logger.info("[RedisEventBus] Stopped")

    async def publish_kill_switch(self, reason: str, triggered_by: int):
        """主动触发全局交易挂起"""
        # NOTE: 直接使用模块级单例
        payload = json.dumps({
            "action": "HALT_ALL",
            "reason": reason,
            "triggered_by": triggered_by
        })
        await redis_client.publish(self.KILL_SWITCH_CHANNEL, payload)
        logger.warning(f"[RedisEventBus] Kill switch triggered! Reason: {reason}")

        
    async def _listen_loop(self):
        try:
            while True:
                message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    channel = message["channel"].decode("utf-8")
                    data = message["data"].decode("utf-8")
                    
                    if channel == self.KILL_SWITCH_CHANNEL:
                        await self._handle_kill_switch_event(data)
                        
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"RedisEventBus 监听崩溃: {e}")

    async def _handle_kill_switch_event(self, raw_data: str):
        try:
            payload = json.loads(raw_data)
            action = payload.get("action")
            if action == "HALT_ALL":
                logger.critical("🛑 [Kill Switch] 收到全服挂起指令，立即斩断交易并推送给所有的前端!")
                
                # 1. 中断管理器内所有的机器人运行
                await strategy_manager.stop_all_bots()
                
                # 2. 推送系统公告级提醒给所有 Web 端访客
                await ws_hub.broadcast({
                    "type": "SYSTEM_ALERT",
                    "level": "CRITICAL",
                    "message": f"管理员已启动全局熔断保护引擎。原因：{payload.get('reason', '未知')}"
                })
        except Exception as e:
            logger.error(f"处理 Kill Switch 消息时发生错误: {e}")

redis_bus = RedisEventBus()
