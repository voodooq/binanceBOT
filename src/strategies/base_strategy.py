import asyncio
import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from src.exchanges.binance_client import BinanceClient
from src.models.bot import BotConfig

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """
    所有量化策略的抽象基类。
    实现此基类的子类将被 StrategyManager 统一生命周期管理。
    """

    def __init__(self, bot_config: BotConfig, client: BinanceClient):
        """
        @param bot_config: 当前机器人的配置数据 (由 DB 提供)
        @param client: 已初始化的 Binance 客户端实例
        """
        self.bot_config = bot_config
        self._client = client

        # 运行期事件队列：价格事件采取 latest-wins，订单事件严格串行消费
        self._price_event_queue: asyncio.Queue[Decimal] = asyncio.Queue(maxsize=1)
        self._order_event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._price_worker_task: asyncio.Task | None = None
        self._order_worker_task: asyncio.Task | None = None
        self._event_processors_started = False
        self._event_processors_lock = asyncio.Lock()
        self._event_processors_stopped = False

    async def start_event_processing(self) -> None:
        """启动内部事件处理协程，确保价格/订单事件串行落地。"""
        if self._event_processors_started:
            return

        async with self._event_processors_lock:
            if self._event_processors_started:
                return

            self._event_processors_stopped = False
            bot_id = getattr(self.bot_config, "id", "unknown")
            self._price_worker_task = asyncio.create_task(
                self._price_worker_loop(),
                name=f"bot_{bot_id}_price_worker",
            )
            self._order_worker_task = asyncio.create_task(
                self._order_worker_loop(),
                name=f"bot_{bot_id}_order_worker",
            )
            self._event_processors_started = True

    async def shutdown_event_processing(self) -> None:
        """停止内部事件处理协程。"""
        self._event_processors_stopped = True

        tasks = [
            task
            for task in (self._price_worker_task, self._order_worker_task)
            if task is not None
        ]
        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._price_worker_task = None
        self._order_worker_task = None
        self._event_processors_started = False

    async def handle_price_update(self, price: Decimal) -> None:
        """
        统一入口：将价格事件放入串行队列。
        若行情高频到达，则只保留最新价格，避免任务堆积。
        """
        if self._event_processors_stopped:
            return

        if not self._event_processors_started:
            await self.start_event_processing()

        if self._price_event_queue.full():
            try:
                self._price_event_queue.get_nowait()
                self._price_event_queue.task_done()
            except asyncio.QueueEmpty:
                pass

        await self._price_event_queue.put(price)

    async def handle_order_update(self, event: dict[str, Any]) -> None:
        """
        统一入口：将订单事件放入串行队列。
        订单事件不能丢弃，必须按顺序处理。
        """
        if self._event_processors_stopped:
            return

        if not self._event_processors_started:
            await self.start_event_processing()

        await self._order_event_queue.put(event)

    async def _price_worker_loop(self) -> None:
        while True:
            price = await self._price_event_queue.get()
            try:
                await self.on_price_update(price)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "策略价格事件处理异常 [bot_id=%s]",
                    getattr(self.bot_config, "id", "unknown"),
                )
            finally:
                self._price_event_queue.task_done()

    async def _order_worker_loop(self) -> None:
        while True:
            event = await self._order_event_queue.get()
            try:
                await self.on_order_update(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "策略订单事件处理异常 [bot_id=%s]",
                    getattr(self.bot_config, "id", "unknown"),
                )
            finally:
                self._order_event_queue.task_done()

    @abstractmethod
    async def initialize(self) -> None:
        """
        初始化策略：
        系统在启动 Bot 之前会调用此方法。
        适合在此处加载交易对精度信息、同步服务器时间、恢复断点状态等。
        """
        pass

    @abstractmethod
    async def on_price_update(self, price: Decimal) -> None:
        """
        价格更新回调：
        由 WebSocket 行情流低延迟触发。
        核心的开平仓信号和逻辑判断应在此处处理。
        """
        pass

    @abstractmethod
    async def on_order_update(self, event: dict[str, Any]) -> None:
        """
        订单状态变更回调：
        由 WebSocket 用户数据流触发。
        用于处理订单 FILLED, CANCELED 等状态更新，及执行后续操作 (如挂出平仓单)。
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """
        优雅停止：
        系统在关闭或挂起 Bot 之前会调用此方法。
        适合在此处执行撤销所有活动挂单、回写运行时状态至数据库等清理操作。
        """
        pass