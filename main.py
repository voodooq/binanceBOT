"""
币安量化交易机器人 — 程序入口

负责初始化所有模块并启动交易策略。
支持优雅关闭（Ctrl+C）：依次撤销挂单、关闭 WebSocket、保存状态。
"""
import asyncio
import signal
import sys
import logging

from src.config.binance_config import loadSettings
from src.utils.logger import setupLogger
from src.utils.rate_limiter import RateLimiter
from src.utils.notifier import Notifier
from src.exchanges.binance_client import BinanceClient
from src.strategies.grid_strategy import GridStrategy

logger = logging.getLogger(__name__)


async def main() -> None:
    """主函数：初始化 → 连接 → 启动策略 → WebSocket 监听"""

    # ============================================
    # 1. 加载配置
    # ============================================
    settings = loadSettings()

    # 2. 初始化日志系统
    setupLogger(logLevel=settings.logLevel)

    # NOTE: 代理必须在所有网络组件初始化之前设置，
    # 确保 python-binance 底层 aiohttp 能正确读取代理
    if settings.proxyUrl:
        import os
        os.environ["HTTPS_PROXY"] = settings.proxyUrl
        os.environ["HTTP_PROXY"] = settings.proxyUrl
        logger.info("🌐 已设置全局代理: %s", settings.proxyUrl)

    logger.info("=" * 60)
    logger.info("🤖 币安量化交易机器人 v2.3.1")
    logger.info("=" * 60)

    # 校验配置
    settings.validate()
    settings.logSummary()

    # ============================================
    # 3. 初始化核心组件
    # ============================================
    rateLimiter = RateLimiter()
    notifier = Notifier(
        botToken=settings.telegramBotToken,
        chatId=settings.telegramChatId,
        proxyUrl=settings.proxyUrl,
    )
    client = BinanceClient(settings=settings, rateLimiter=rateLimiter)
    strategy = GridStrategy(settings=settings, client=client, notifier=notifier)

    # ============================================
    # 4. 建立连接
    # ============================================
    try:
        await notifier.start()
        await client.connect()
        await strategy.initialize()
        await strategy.start()
    except Exception as e:
        logger.critical("❌ 初始化失败: %s", e)
        await _cleanup(client, notifier, strategy)
        return

    # ============================================
    # 5. 注册优雅关闭信号
    # ============================================
    shutdownEvent = asyncio.Event()

    def onSignal() -> None:
        logger.info("🛑 收到关闭信号，正在优雅退出...")
        shutdownEvent.set()

    # NOTE: Windows 不完整支持 loop.add_signal_handler，
    # 使用 signal.signal 兼容跨平台
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, onSignal)
    except NotImplementedError:
        # Windows 回退方案
        signal.signal(signal.SIGINT, lambda s, f: onSignal())

    # ============================================
    # 6. 启动 WebSocket 任务
    # ============================================
    tasks: list[asyncio.Task] = []

    try:
        # 实时行情流
        tradeStreamTask = asyncio.create_task(
            client.startTradeStream(onPrice=strategy.onPriceUpdate),
            name="trade_stream",
        )
        tasks.append(tradeStreamTask)

        # 用户数据流（订单状态更新）
        userStreamTask = asyncio.create_task(
            client.startUserDataStream(onOrderUpdate=strategy.onOrderUpdate),
            name="user_data_stream",
        )
        tasks.append(userStreamTask)

        logger.info("🟢 机器人已启动，等待交易信号...")
        logger.info("   按 Ctrl+C 优雅退出")

        # 等待关闭信号
        await shutdownEvent.wait()

    except Exception as e:
        logger.error("运行时异常: %s", e)

    finally:
        # ============================================
        # 7. 优雅关闭
        # ============================================
        logger.info("🔄 正在关闭...")

        # 取消所有后台任务
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await _cleanup(client, notifier, strategy)

        logger.info("👋 机器人已安全退出")


async def _cleanup(
    client: BinanceClient,
    notifier: Notifier,
    strategy: GridStrategy,
) -> None:
    """
    清理资源：停止策略、断开连接、关闭通知器。
    每一步单独 try-except，确保一个组件失败不影响其他组件的清理。
    """
    try:
        await strategy.stop()
    except Exception as e:
        logger.error("策略停止失败: %s", e)

    try:
        await client.disconnect()
    except Exception as e:
        logger.error("断开连接失败: %s", e)

    try:
        await notifier.stop()
    except Exception as e:
        logger.error("通知器关闭失败: %s", e)


def run() -> None:
    """程序入口点"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 再见！")
        sys.exit(0)


if __name__ == "__main__":
    run()
