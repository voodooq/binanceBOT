import logging
import asyncio
from decimal import Decimal
from typing import Any, Optional

from src.strategies.base_strategy import BaseStrategy
from src.engine.delta_balancer import delta_balancer
from src.engine.delta_balancer_v2 import DeltaBalancerV2
from src.exchanges.binance_client import BinanceClient
from src.models.bot import BotConfig
from src.services.notification_service import notification_service, NotificationLevel
from src.engine.ws_hub import ws_hub

logger = logging.getLogger(__name__)

class HedgeStrategy(BaseStrategy):
    """
    期现对冲策略 (Beta 原型)。
    
    核心原理：
    1. 在现货市场 (Spot) 买入资产。
    2. 在 U 本位合约市场 (Futures) 开启同等价值的反向头寸 (空头)。
    3. 获取合约市场的资金费率 (Funding Rate) 收益。
    4. 理想状态下，两端盈亏抵消，净值波动接近于零。
    
    V3 增强特性：
    - 集成 DeltaBalancer 实时监控由于手续费扣除、滑点或精度舍入导致的“敞口漂移”。
    - 自动触发重平衡，将对冲基差控制在 0.5% 以内。
    """
    
    def __init__(self, bot_config: BotConfig, client: BinanceClient):
        super().__init__(bot_config, client)
        self._running = False
        self._last_price = Decimal("0")
        
        # 提取策略参数
        params = bot_config.parameters or {}
        # 目标名义价值 (USDT)
        self._target_notional = Decimal(str(params.get("target_notional", bot_config.total_investment)))
        # 重平衡敏感度
        self._rebalance_threshold = Decimal(str(params.get("rebalance_threshold", "0.005")))
        
        # 对冲头寸状态
        self._spot_qty = Decimal("0")
        self._futures_qty = Decimal("0")
        
        # [V4.0] 智能平衡器组件
        self._balancer_v2 = DeltaBalancerV2(bot_config, client)
        self._v2_saved_commissions = Decimal("0") # 影子统计：V2 算法节省的预估手续费

    async def initialize(self) -> None:
        """初始化策略环境与初始建仓"""
        logger.info("🧪 [HedgeStrategy] 正在初始化期现对冲环境...")
        
        # 1. 首先同步现有的持仓状态
        await self._sync_positions()
        
        # 2. 如果两端均无持仓，则视为新启动，执行自动对冲建仓 (Initial Entry)
        # 注意：这里假设用户账户有足够的 USDT
        if self._spot_qty == 0 and abs(self._futures_qty) < Decimal("0.00001"):
            await self._open_initial_hedge()
        else:
            logger.info("📡 检测到存量持仓，将继续在现有基数上进行 Delta 监控。")
            
        self._running = True
        logger.info("✅ [HedgeStrategy] 期现对冲引擎已进入实时监控态。")

    async def _sync_positions(self):
        """同步现货与合约的真实物理持仓"""
        try:
            # 获取现货余额 (底仓资产)
            self._spot_qty = await self._client.getFreeBalance(self.bot_config.base_asset)
            
            # 获取合约仓位 (统一使用 U 本位合约)
            pos_info = await self._client.getFuturesPosition(self.bot_config.symbol)
            if pos_info:
                # positionAmt 带有符号，负数代表空单 (Short)
                self._futures_qty = Decimal(pos_info.get("positionAmt", "0"))
            
            logger.info("📊 [Delta Check] 现货: %s | 合约: %s", self._spot_qty, self._futures_qty)
        except Exception as e:
            logger.error("❌ 同步对冲头寸失败: %s", e)

    async def _open_initial_hedge(self) -> None:
        """执行初始建仓逻辑：买现货 + 卖合约"""
        # 1. 估算买入数量
        try:
            # 获取最新价用于估算
            ticker = await self._client.get_klines(symbol=self.bot_config.symbol, limit=1)
            if not ticker:
                logger.error("无法获取行情，建仓中止")
                return
            price = Decimal(str(ticker[0][4])) # 收盘价
            self._last_price = price
            
            # 计算应买/卖数量
            qty = self._target_notional / price
            logger.warning("🚀 [Initial Hedge] 准备开启 %s USDT 的对冲头寸 (约 %s %s)", 
                           self._target_notional, qty, self.bot_config.base_asset)
            
            # 2. 并发执行现货买入与合约卖出，最小化时间差风险 (Atomic-like)
            tasks = [
                self._client.createOrder(
                    symbol=self.bot_config.symbol, side="BUY", type="MARKET", quantity=qty
                ),
                self._client.futuresCreateOrder(
                    symbol=self.bot_config.symbol, side="SELL", type="MARKET", quantity=qty
                )
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    logger.error("⚠️ 建仓过程中部分指令失败: %s", res)
            
            notification_service.send_notification(
                user_id=self.bot_config.user_id,
                title="🚀 期现对冲已建仓",
                message=f"策略 [{self.bot_config.name}] 已成功开启对冲头寸。\n名义价值: {self._target_notional} USDT | 标的: {self.bot_config.symbol}",
                level=NotificationLevel.SUCCESS
            )
                    
            await self._sync_positions()
        except Exception as e:
            logger.error("💥 初始对冲建仓发生致命错误: %s", e)

    async def on_price_update(self, price: Decimal) -> None:
        """
        [V4.0] 实时价格回调：智能对冲核心。
        同时运行 V1(影子) 与 V2(智能) 算法进行对比与决策。
        """
        self._last_price = price
        if not self._running:
            return

        # 1. 更新波动率感知环境
        self._balancer_v2.update_market_context(float(price))
        
        # 2. 获取 V1 简单分析 (用于向下兼容或对比)
        analysis_v1 = delta_balancer.analyze_imbalance(
            spot_qty=self._spot_qty,
            futures_qty=self._futures_qty,
            mid_price=price
        )
        
        # 3. 获取 V2 智能分析
        analysis_v2_res = await self._balancer_v2.analyze_imbalance_v2(
            spot_qty=self._spot_qty,
            futures_qty=self._futures_qty,
            price=price
        )
        analysis_v2 = analysis_v2_res["data"]
        
        # 影子交易记录：如果 V1 喊“该平衡了”但 V2 喊“不划算，别动”，累加节省成本
        if analysis_v1["needs_fix"] and not analysis_v2["needs_fix"]:
            self._v2_saved_commissions += (analysis_v1["notional_usdt"] * Decimal("0.0004")) # 按 0.04% 预估
            logger.debug("👻 [Shadow Trade] V2 算法拦截了一次低性价比调仓。累计节省磨损: %s USDT", self._v2_saved_commissions)

        # 最终执行决策：目前切换至 V2 级智能决策
        if analysis_v2["needs_fix"]:
            logger.warning("⚖️ [Smart Rebalance] 触发智能重平衡。偏离: %.4f%% | 动态阈值: %.4f%% | 风险溢价: %.2f", 
                           analysis_v2["deviation_ratio"] * 100, 
                           analysis_v2["dynamic_threshold"] * 100,
                           analysis_v2["risk_premium"])
            
            # 兼容老版本执行格式
            fix_analysis = {
                "delta_qty": Decimal(str(analysis_v2["delta_qty"])),
                "notional_usdt": Decimal(str(analysis_v2["notional_usdt"])),
                "fix_action": "SELL_FUTURES" if analysis_v2["delta_qty"] > 0 else "BUY_FUTURES",
                "deviation_ratio": Decimal(str(analysis_v2["deviation_ratio"]))
            }
            await self._rebalance(fix_analysis)

        # 推送增强后的状态给前端仪表盘
        asyncio.create_task(ws_hub.send_personal_message({
            "type": "HEDGE_DELTA_UPDATE",
            "bot_id": self.bot_config.id,
            "data": {
                **analysis_v2,
                "v2_saved_fees": float(self._v2_saved_commissions),
                "is_v2": True
            }
        }, self.bot_config.user_id))

    async def _rebalance(self, analysis: dict) -> None:
        """执行 Delta 修正：在合约端多刷一笔单以抹平与现货的差额"""
        qty = abs(analysis["delta_qty"])
        action = analysis["fix_action"] # SELL_FUTURES or BUY_FUTURES
        
        # 简单防御：过小数量不操作 (防止频繁触发最小成交额限制)
        if analysis["notional_usdt"] < 5: 
            return
            
        try:
            await self._client.futuresCreateOrder(
                symbol=self.bot_config.symbol,
                side="SELL" if action == "SELL_FUTURES" else "BUY",
                type="MARKET",
                quantity=qty
            )
            
            notification_service.send_notification(
                user_id=self.bot_config.user_id,
                title="⚖️ 对冲重平衡触发",
                message=f"策略 [{self.bot_config.name}] 检测到 Delta 偏离，已执行 {action} 操作。\n数量: {qty} | 偏离度: {analysis['deviation_ratio']*100:.2f}%",
                level=NotificationLevel.INFO
            )
            
            # 等待一会后刷新快照
            await asyncio.sleep(1)
            await self._sync_positions()
        except Exception as e:
            logger.error("❌ 重平衡执行异常: %s", e)

    async def on_order_update(self, event: dict[str, Any]) -> None:
        """当用户手动干预或由于强平导致订单变动时，同步状态"""
        # 合约或现货订单成交后，强制刷新持仓数据
        await self._sync_positions()

    async def stop(self) -> None:
        """策略退出"""
        self._running = False
        logger.info("🛑 [HedgeStrategy] 对冲监控已下线。警告：期现头寸未平掉，需手动清算或确保持仓目的。")
