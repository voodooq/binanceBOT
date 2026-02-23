"""
币安交易机器人 — Telegram 异步通知模块

通过 Telegram Bot API 推送关键事件（套利成功、止损触发、异常告警等）。
未配置 Bot Token 时静默跳过，不影响主流程。
"""
import asyncio
import logging
from collections import deque

import aiohttp

logger = logging.getLogger(__name__)

# Telegram Bot API 基础地址
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"

# NOTE: Telegram 限制每秒约 30 条消息，使用队列缓冲防止触发限流
MAX_QUEUE_SIZE = 100
SEND_INTERVAL = 0.05  # 两条消息之间的最小间隔（秒）


class Notifier:
    """
    异步 Telegram 通知器。

    使用内部消息队列缓冲通知，后台任务依次发送，
    避免突发大量通知触发 Telegram API 限流。
    """

    def __init__(self, botToken: str = "", chatId: str = "", proxyUrl: str | None = None) -> None:
        self._botToken = botToken
        self._chatId = chatId
        self._proxyUrl = proxyUrl
        self._enabled = bool(botToken and chatId)
        self._queue: deque[str] = deque(maxlen=MAX_QUEUE_SIZE)
        self._sendTask: asyncio.Task | None = None
        self._session: aiohttp.ClientSession | None = None

        if self._enabled:
            logger.info("📱 Telegram 通知已启用 (代理: %s)", proxyUrl or "直连")
        else:
            logger.info("📱 Telegram 通知未配置，通知功能跳过")

    async def start(self) -> None:
        """启动后台发送任务"""
        if not self._enabled:
            return
        # NOTE: 显式注入代理，不依赖 os.environ 的全局生效时机
        self._session = aiohttp.ClientSession()
        self._sendTask = asyncio.create_task(self._sendLoop())
        logger.debug("Telegram 通知后台任务已启动")

    async def stop(self) -> None:
        """停止后台发送任务并清理资源"""
        if self._sendTask:
            self._sendTask.cancel()
            try:
                await self._sendTask
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
        logger.debug("Telegram 通知后台任务已停止")

    def notify(self, message: str) -> None:
        """
        将通知消息加入发送队列（非阻塞）。
        未启用时静默返回。

        @param message 要发送的消息文本
        """
        if not self._enabled:
            return
        self._queue.append(message)

    async def sendImmediate(self, message: str) -> bool:
        """
        立即发送一条消息（绕过队列），用于紧急告警。

        @param message 紧急消息文本
        @returns 是否发送成功
        """
        if not self._enabled:
            return False
        return await self._doSend(message)

    async def _sendLoop(self) -> None:
        """后台循环：持续从队列取出消息并发送"""
        while True:
            try:
                if self._queue:
                    message = self._queue.popleft()
                    await self._doSend(message)
                    await asyncio.sleep(SEND_INTERVAL)
                else:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                # 退出前发送队列中剩余的消息
                while self._queue:
                    message = self._queue.popleft()
                    await self._doSend(message)
                raise
            except Exception as e:
                logger.error("Telegram 发送异常: %s", e)
                await asyncio.sleep(5.0)

    async def _doSend(self, message: str) -> bool:
        """
        执行实际的消息发送。

        @param message 消息文本
        @returns 是否发送成功
        """
        if not self._session:
            return False

        url = TELEGRAM_API_BASE.format(token=self._botToken)
        payload = {
            "chat_id": self._chatId,
            "text": message,
            "parse_mode": "HTML",
        }

        try:
            async with self._session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
                proxy=self._proxyUrl,
            ) as resp:
                if resp.status == 200:
                    logger.debug("📤 Telegram 消息已发送")
                    return True
                else:
                    body = await resp.text()
                    logger.warning("Telegram 发送失败 [%d]: %s", resp.status, body)
                    return False
        except Exception as e:
            logger.error("Telegram 网络错误: %s", e)
            return False
