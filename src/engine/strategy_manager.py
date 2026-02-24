import asyncio
import logging
from typing import Dict, Type

from src.exchanges.binance_client import BinanceClient, ClientConfig
from src.models.bot import BotConfig, BotStatus, StrategyType
from src.strategies.base_strategy import BaseStrategy

# Import concrete strategies when they are ready
from src.strategies.grid_strategy import GridStrategy

logger = logging.getLogger(__name__)

class StrategyManager:
    """
    负责所有策略实例生命周期管理（启动、挂起、停止、状态查询）。
    通过 asyncio.Task 并发运行多个机器人实例。
    """
    def __init__(self):
        # 存储正在运行的机器人的 task 和对应的 strategy 实例
        # key: bot_config.id, value: { "task": asyncio.Task, "strategy": BaseStrategy }
        self._active_bots: Dict[int, Dict[str, any]] = {}
        
        # 策略类型 -> 策略实现类的映射表
        self._strategy_registry: Dict[StrategyType, Type[BaseStrategy]] = {
            StrategyType.GRID: GridStrategy,
        }

    def register_strategy(self, strategy_type: StrategyType, strategy_class: Type[BaseStrategy]):
        """注册具体策略路由"""
        self._strategy_registry[strategy_type] = strategy_class

    async def start_bot(self, bot_config: BotConfig, api_key_str: str, api_secret_str: str) -> bool:
        """
        启动指定的机器人实例。
        @param bot_config: DB 取出的机器人配置
        @param api_key_str: 解密后的公钥
        @param api_secret_str: 解密后的私钥
        """
        bot_id = bot_config.id
        
        if bot_id in self._active_bots:
            task = self._active_bots[bot_id]["task"]
            if not task.done():
                logger.warning("⚠️ Bot [%d] 已经在运行中，请勿重复启动", bot_id)
                # 这种情况下允许前端刷新状态，抛出特定标识供前端识别
                return False
            else:
                logger.warning("🧹 发现 Bot [%d] 的僵尸任务 (已结束但未清理字典)，执行强制清理", bot_id)
                self._active_bots.pop(bot_id, None)

        strategy_class = self._strategy_registry.get(bot_config.strategy_type)
        if not strategy_class:
            logger.error("❌ 未知或尚未注册的策略类型: %s", bot_config.strategy_type)
            return False

        try:
            # 1. 初始化客户端连接池代理/凭据
            # 从 parameters 中提取单个策略的代理偏好，如无则为 None
            proxy = bot_config.parameters.get("proxy", None)
            
            client_config = ClientConfig(
                apiKey=api_key_str,
                apiSecret=api_secret_str,
                useTestnet=bot_config.is_testnet,
                tradingSymbol=bot_config.symbol,
                proxy=proxy
            )
            
            from src.utils.rate_limiter import RateLimiter
            rate_limiter = RateLimiter() # 为每个机器人独立分配速率桶（或稍后改造为连接池级共享）
            
            client = BinanceClient(config=client_config, rateLimiter=rate_limiter)
            await client.connect()

            # 2. 实例化对应策略并调用统一生命周期的钩子
            strategy_instance = strategy_class(bot_config=bot_config, client=client)
            await strategy_instance.initialize()

            # 3. 创建 asyncio.Task 守护协程，捕获运行时错误并处理
            task = asyncio.create_task(
                self._run_bot_loop(bot_id, strategy_instance, client),
                name=f"bot_{bot_id}"
            )
            
            self._active_bots[bot_id] = {
                "task": task,
                "strategy": strategy_instance,
                "client": client
            }
            logger.info("🟢 Bot [%d] 启动成功 (策略: %s, 币种: %s)", bot_id, bot_config.strategy_type.value, bot_config.symbol)
            return True

        except Exception as e:
            logger.exception("💥 Bot [%d] 启动时发生异常: %s", bot_id, str(e))
            return False

    async def _run_bot_loop(self, bot_id: int, strategy: BaseStrategy, client: BinanceClient) -> None:
        """
        内部的运行大循环，负责维护各个流的健康挂载。
        这里使用 asyncio.gather 并发管理行情与订单推送流。
        """
        try:
            logger.info("📡 Bot [%d] 协程开始拉起 WebSocket 监听...", bot_id)
            # 在单独的任务中挂载 WebSocket 流，若抛出异常则被 catch 住。
            await asyncio.gather(
                client.startTradeStream(onPrice=strategy.on_price_update),
                client.startUserDataStream(onOrderUpdate=strategy.on_order_update)
            )
        except asyncio.CancelledError:
            logger.info("🛑 Bot [%d] 的执行任务已收到取消指令，准备清理并退出...", bot_id)
            raise
        except Exception as e:
            logger.error("💥 Bot [%d] 运行时奔溃: %s", bot_id, e)
            # Todo: 此处可触发数据库状态回写 BotStatus.ERROR
        finally:
            logger.info("🧹 Bot [%d] 执行清理程序...", bot_id)
            try:
                await strategy.stop()
            except Exception as e:
                logger.error("Bot [%d] stop 钩子异常: %s", bot_id, e)
                
            try:
                await client.disconnect()
            except Exception as e:
                logger.error("Bot [%d] client 释放异常: %s", bot_id, e)
            
            # 从管理器卸载本任务，非常关键
            if bot_id in self._active_bots:
                self._active_bots.pop(bot_id, None)
                logger.info("🗑️ Bot [%d] 的运行态数据已彻底从系统擦除", bot_id)

    async def stop_bot(self, bot_id: int) -> bool:
        """
        主动挂起/停止指定的机器人实例。
        本质就是取消对应的 asyncio 协程，内部通过 CancelledError 捕获并清理。
        """
        bot_info = self._active_bots.get(bot_id)
        if not bot_info:
            logger.info("Bot [%d] 不在运行列表中", bot_id)
            return False

        logger.info("⏳ 正在请求停止 Bot [%d]...", bot_id)
        task: asyncio.Task = bot_info["task"]
        task.cancel()
        
        try:
            await task
        except asyncio.CancelledError:
            logger.info("✅ Bot [%d] 现已安全停止完毕", bot_id)
            
        return True

    async def panic_close_bot(self, bot_id: int) -> dict[str, any]:
        """
        触发机器人的一键平仓。
        首先通过策略的专属方法安全撤单和清算可用余额，然后安全卸载其运行协程。
        """
        bot_info = self._active_bots.get(bot_id)
        if not bot_info:
            logger.warning("Bot [%d] 不在运行状态中，无法执行平仓", bot_id)
            return {"status": "error", "message": "Bot 不在运行状态中"}
        
        logger.warning("🚨 引擎正在强平 Bot [%d]...", bot_id)
        strategy: BaseStrategy = bot_info["strategy"]
        
        # 强平逻辑
        if hasattr(strategy, "panic_close"):
            result = await strategy.panic_close()
        else:
            result = {"status": "error", "message": "该策略类型暂不支持一键平仓"}
            
        # 无论清盘由于精度或市价等原因有没有完全清算成功，机器人本身都必须立刻挂起下线
        await self.stop_bot(bot_id)
        return result

    async def stop_all_bots(self) -> None:
        """全局资源回收 (系统退出时触发)"""
        active_ids = list(self._active_bots.keys())
        if not active_ids:
            return
            
        logger.warning("🟥 正在停止所有活动的机器人实例: %s", active_ids)
        stop_tasks = [self.stop_bot(bot_id) for bot_id in active_ids]
        await asyncio.gather(*stop_tasks, return_exceptions=True)
        logger.info("✔️ 所有机器人安全停止完毕")

# 全局单例管理器
strategy_manager = StrategyManager()
