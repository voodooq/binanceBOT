import asyncio
import json
import logging
from typing import Any

from redis.asyncio.client import PubSub

from src.db.session import redis_client
from src.engine.ws_hub import ws_hub

logger = logging.getLogger(__name__)


def _normalize_pubsub_value(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if value is None:
        return ""
    return str(value)


class RedisEventBus:
    """
    负责订阅跨进程级的指令 (如外部 Web 发出的强制停机指令 / 熔断系统广播)。
    """

    KILL_SWITCH_CHANNEL = "global:kill_switch"
    TRADE_EVENTS_CHANNEL = "user:trade_events"

    def __init__(self):
        self._pubsub: PubSub | None = None
        self._listener_task: asyncio.Task | None = None

    async def start(self):
        """连入 Redis 并挂载订阅"""
        if self._listener_task and not self._listener_task.done():
            logger.info("[RedisEventBus] Listener already running")
            return

        self._pubsub = redis_client.pubsub()
        await self._pubsub.subscribe(
            self.KILL_SWITCH_CHANNEL,
            self.TRADE_EVENTS_CHANNEL,
        )
        logger.info(
            "[RedisEventBus] Subscribed to '%s' and '%s'",
            self.KILL_SWITCH_CHANNEL,
            self.TRADE_EVENTS_CHANNEL,
        )

        # 启动后台守护任务循环读消息
        self._listener_task = asyncio.create_task(
            self._listen_loop(),
            name="redis_event_bus_listener",
        )

    async def stop(self):
        if self._listener_task:
            self._listener_task.cancel()
            await asyncio.gather(self._listener_task, return_exceptions=True)
            self._listener_task = None

        if self._pubsub:
            try:
                await self._pubsub.unsubscribe(
                    self.KILL_SWITCH_CHANNEL,
                    self.TRADE_EVENTS_CHANNEL,
                )
                await self._pubsub.close()
            except Exception as e:
                # 当 supervisor 同时停止所有进程时，redis 可能已经先退出，这里静默处理即可
                logger.debug(f"[RedisEventBus] 退出时断开订阅失败: {e}")
            finally:
                self._pubsub = None

        logger.info("[RedisEventBus] Stopped")

    async def publish_kill_switch(self, reason: str, triggered_by: int):
        """主动触发全局交易挂起"""
        payload = json.dumps(
            {
                "action": "HALT_ALL",
                "reason": reason,
                "triggered_by": triggered_by,
            }
        )
        await redis_client.publish(self.KILL_SWITCH_CHANNEL, payload)
        logger.warning(f"[RedisEventBus] Kill switch triggered! Reason: {reason}")

    async def publish_trade_event(
        self, user_id: int, bot_id: int, event_type: str, data: dict
    ):
        """推送具体的交易事件 (如 PnL 释放、成交提醒) 到频道，由各 WS 进程转发给对应用户"""
        payload = json.dumps(
            {
                "user_id": user_id,
                "bot_id": bot_id,
                "type": event_type,
                "data": data,
            }
        )
        await redis_client.publish(self.TRADE_EVENTS_CHANNEL, payload)
        logger.debug(
            f"[RedisEventBus] Published trade event for Bot [{bot_id}]: {event_type}"
        )

    async def _listen_loop(self):
        if not self._pubsub:
            return

        try:
            while True:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message:
                    channel = _normalize_pubsub_value(message.get("channel"))
                    data = _normalize_pubsub_value(message.get("data"))

                    if channel == self.KILL_SWITCH_CHANNEL:
                        await self._handle_kill_switch_event(data)
                    elif channel == self.TRADE_EVENTS_CHANNEL:
                        await self._handle_trade_event(data)

                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("RedisEventBus 监听崩溃")

    async def _handle_kill_switch_event(self, raw_data: str):
        try:
            payload = json.loads(raw_data)
            action = payload.get("action")
            if action == "HALT_ALL":
                logger.critical("🛑 [Kill Switch] 收到全服挂起指令，立即斩断交易并推送给所有的前端!")

                # 1. 中断管理器内所有的机器人运行
                from src.engine.strategy_manager import strategy_manager

                await strategy_manager.stop_all_bots()

                # 2. 推送系统公告级提醒给所有 Web 端访客
                await ws_hub.broadcast(
                    {
                        "type": "SYSTEM_ALERT",
                        "level": "CRITICAL",
                        "message": f"管理员已启动全局熔断保护引擎。原因：{payload.get('reason', '未知')}",
                    }
                )
        except Exception as e:
            logger.error(f"处理 Kill Switch 消息时发生错误: {e}")

    async def _handle_trade_event(self, raw_data: str):
        """解析来自 Redis 的私有交易事件并将其通过 WS 推送给特定用户"""
        try:
            payload = json.loads(raw_data)
            user_id = payload.get("user_id")
            if user_id:
                # 路由给 WS 挂载点进行推送
                await ws_hub.send_personal_message(payload, user_id)
        except Exception as e:
            logger.error(f"处理 Trade Event 消息时发生错误: {e}")


redis_bus = RedisEventBus()