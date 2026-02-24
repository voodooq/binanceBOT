from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from src.exchanges.binance_client import BinanceClient
from src.models.bot import BotConfig


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
