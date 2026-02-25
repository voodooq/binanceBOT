import logging
import asyncio
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import select
from os import getenv

from src.models.notification import Notification, NotificationLevel, NotificationSetting
from src.engine.ws_hub import ws_hub
from src.utils.notifier import Notifier
from src.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

class NotificationService:
    """
    高阶通知调度服务。
    负责消息持久化、多端分发（Web/Telegram/Email）以及根据用户等级偏好进行智能过滤。
    """
    def __init__(self):
        # 缓存 Telegram Notifier 实例
        # key: user_id, value: Notifier
        self._tg_notifiers: dict[int, Notifier] = {}

    def send_notification(
        self,
        user_id: int,
        title: str,
        message: str,
        level: NotificationLevel = NotificationLevel.INFO,
        data: Optional[dict] = None
    ):
        """
        发送通知主入口。
        采用 Fire-and-forget 模式，确保不阻塞主交易逻辑。
        """
        asyncio.create_task(self._dispatch(user_id, title, message, level, data))

    async def _dispatch(self, user_id: int, title: str, message: str, level: NotificationLevel, data: Optional[dict]):
        """内部调度与分发逻辑"""
        try:
            async with AsyncSessionLocal() as db:
                # 1. 获取并应用用户通知设置
                stmt = select(NotificationSetting).where(NotificationSetting.user_id == user_id)
                result = await db.execute(stmt)
                setting = result.scalar_one_or_none()
                
                # 默认配置兜底
                if not setting:
                    setting = NotificationSetting(user_id=user_id, web_enabled=True, min_level=NotificationLevel.INFO)
                
                # 2. 检查等级过滤 (优先级: info < success < warning < error < critical)
                level_order = {
                    NotificationLevel.INFO: 0,
                    NotificationLevel.SUCCESS: 1,
                    NotificationLevel.WARNING: 2,
                    NotificationLevel.ERROR: 3,
                    NotificationLevel.CRITICAL: 4
                }
                if level_order.get(level, 0) < level_order.get(setting.min_level, 0):
                    return

                # 3. 持久化到数据库 (流水存证)
                notif = Notification(
                    user_id=user_id,
                    level=level,
                    title=title,
                    message=message,
                    data=data
                )
                db.add(notif)
                await db.commit()
                await db.refresh(notif)

                # 4. 实时 Web 推送 (WebSocket)
                # 即使页面没刷新，前端也能通过 WS 收到 Toast 弹窗
                if setting.web_enabled:
                    await ws_hub.send_personal_message({
                        "type": "NOTIFICATION",
                        "data": {
                            "id": notif.id,
                            "level": level,
                            "title": title,
                            "message": message,
                            "time": datetime.now().isoformat()
                        }
                    }, user_id)

                # 5. Telegram 外部推送
                if setting.telegram_enabled and setting.telegram_chat_id:
                    bot_token = getenv("TELEGRAM_BOT_TOKEN")
                    if bot_token:
                        notifier = self._tg_notifiers.get(user_id)
                        # 如果 Chat ID 变动，则重新创建实例
                        if not notifier or notifier._chatId != setting.telegram_chat_id:
                            proxy = getenv("TELEGRAM_PROXY")
                            notifier = Notifier(botToken=bot_token, chatId=setting.telegram_chat_id, proxyUrl=proxy)
                            await notifier.start()
                            self._tg_notifiers[user_id] = notifier
                        
                        # 格式化消息标题 Emoji
                        icons = {
                            NotificationLevel.INFO: "ℹ️",
                            NotificationLevel.SUCCESS: "✅",
                            NotificationLevel.WARNING: "⚠️",
                            NotificationLevel.ERROR: "🚫",
                            NotificationLevel.CRITICAL: "🚨"
                        }
                        icon = icons.get(level, "🔔")
                        formatted_msg = f"{icon} <b>{title}</b>\n\n{message}"
                        notifier.notify(formatted_msg)

        except Exception as e:
            logger.error(f"💥 Notification Service 调度崩溃: {e}", exc_info=True)

# 全局单例挂载
notification_service = NotificationService()
