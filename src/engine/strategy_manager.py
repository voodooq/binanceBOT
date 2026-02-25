import asyncio
import logging
from typing import Dict, Type

from src.exchanges.binance_client import BinanceClient, ClientConfig
from src.models.bot import BotConfig, BotStatus, StrategyType
from src.models.api_key import ApiKey
from src.strategies.base_strategy import BaseStrategy
from src.services.crypto_service import crypto_service
from sqlalchemy import select
from sqlalchemy.orm import selectinload

# Import concrete strategies when they are ready
from src.strategies.grid_strategy import GridStrategy
from src.strategies.hedge_strategy import HedgeStrategy
from src.services.geo_check_service import geo_check_service
from src.engine.proxy_scheduler import proxy_scheduler

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
            StrategyType.HEDGE: HedgeStrategy,
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
            # V3.0 多租户架构：优先使用机器人参数中的固定代理，如无则由调度器按最小负载分配
            proxy = bot_config.parameters.get("proxy")
            is_auto_proxy = False
            
            if not proxy:
                proxy = proxy_scheduler.get_best_proxy()
                is_auto_proxy = True
            
            # [P3] 地域合规预检：防止由于 IP 违规导致币安账号风险 (封号/限制)
            is_ok, reason = await geo_check_service.is_compliant(proxy)
            if not is_ok:
                logger.error("🛑 Bot [%d] 启动被合规引擎拦截: %s", bot_id, reason)
                if is_auto_proxy:
                    proxy_scheduler.release_proxy(proxy)
                return False
            
            client_config = ClientConfig(
                apiKey=api_key_str,
                apiSecret=api_secret_str,
                useTestnet=bot_config.is_testnet,
                tradingSymbol=bot_config.symbol,
                api_key_id=bot_config.api_key_id,
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
                "client": client,
                "proxy": proxy,
                "is_auto_proxy": is_auto_proxy
            }
            logger.info("🟢 Bot [%d] 启动成功 (策略: %s, 代理: %s)", bot_id, bot_config.strategy_type.value, proxy or "DIRECT")
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
            
            # 从管理器卸载本任务
            if bot_id in self._active_bots:
                bot_info = self._active_bots.pop(bot_id, None)
                # 释放代理负载计数
                if bot_info and bot_info.get("is_auto_proxy"):
                    proxy_scheduler.release_proxy(bot_info.get("proxy"))
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

    async def init_and_resume_all(self, db_session) -> None:
        """
        [P4] 自动恢复自愈逻辑。
        从数据库加载所有标记为 RUNNING 的机器人并尝试拉起。
        """
        logger.info("🎬 [StrategyManager] 启动持久化自愈检测，搜索运行中的机器人...")
        
        # 查询所有活跃状态的机器人，同时预加载 API Key 和 User 及其 DEK
        stmt = select(BotConfig).where(BotConfig.status == BotStatus.RUNNING).options(
            selectinload(BotConfig.api_key),
            selectinload(BotConfig.user)
        )
        result = await db_session.execute(stmt)
        bots = result.scalars().all()
        
        if not bots:
            logger.info("ℹ️ 未发现需要恢复的运行中机器人。")
            return
            
        logger.info("🚀 发现 %d 个待恢复机器人，正在批量拉起...", len(bots))
        
        for bot in bots:
            try:
                # 检查是否重复拉起 (例如人工重启刚好撞在自动化钩子上)
                if bot.id in self._active_bots:
                    continue
                
                # 获取解密凭据
                api_key = bot.api_key
                if not api_key:
                    logger.error("❌ Bot [%d] 缺少 API Key 关联，跳过恢复", bot.id)
                    continue
                    
                # 使用用户的 DEK 解密该 ApiKey 的 Secret
                secret = crypto_service.decrypt_user_secret(
                    bot.user.encrypted_dek, 
                    api_key.encrypted_secret
                )
                
                # 触发异步启动
                success = await self.start_bot(bot, api_key.api_key, secret)
                if success:
                    logger.info("✅ Bot [%d] (%s) 恢复成功", bot.id, bot.name)
                    # [P4] 发送系统自愈报告
                    notification_service.send_notification(
                        user_id=bot.user_id,
                        title="♻️ 系统自动恢复报告",
                        message=f"服务器重启后，机器人 [{bot.name}] ({bot.symbol}) 已自动恢复运行。\n状态: RUNNING | 策略: {bot.strategy_type.upper()}",
                        level=NotificationLevel.SUCCESS
                    )
                else:
                    logger.error("❌ Bot [%d] (%s) 恢复失败", bot.id, bot.name)
                
                await asyncio.sleep(0.5) # 避锋
                
            except Exception as e:
                logger.error("💥 恢复 Bot [%d] 时发生致命错误: %s", bot.id, e)

# 全局单例管理器
strategy_manager = StrategyManager()
