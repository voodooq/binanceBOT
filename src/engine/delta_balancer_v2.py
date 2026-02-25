import logging
import asyncio
from decimal import Decimal
from typing import Dict, Any, Optional

from src.exchanges.binance_client import BinanceClient
from src.utils.market_data import VolatilityMonitor
from src.models.bot import BotConfig

logger = logging.getLogger("DeltaBalancerV2")

class DeltaBalancerV2:
    """
    智能期现对冲平衡器 (V2)。
    不再仅仅依靠固定阈值，而是结合市场波动率 (VaR) 与 调仓成本 (Cost) 进行经济最优化决策。
    """
    def __init__(self, bot_config: BotConfig, client: BinanceClient, window: int = 14):
        self.bot_config = bot_config
        self.client = client
        
        # 算法超参数
        self.base_threshold = Decimal(str(bot_config.parameters.get("rebalance_threshold", 0.005)))
        self.k_volatility = Decimal("1.5")           # 波动率调节灵敏度系数
        self.fee_rate = Decimal("0.001")             # 预计综合交易成本 (Maker/Taker + 滑点预紧)
        
        self.vol_monitor = VolatilityMonitor(window=window)

    def update_market_context(self, price: float):
        """同步最新价格到波动率分析器"""
        self.vol_monitor.update(price)

    def get_adaptive_threshold(self) -> Decimal:
        """
        计算动态死区阈值: 
        Threshold_adj = Base * (1 + k * max(0, Current_Vol/Avg_Vol - 1))
        确保在波动率 <= 平均值时，维持 Base 阈值；
        在波动率飙升时，按比例线性扩大死区，规避“来回打脸”的振荡损耗。
        """
        if not self.vol_monitor.is_ready():
            return self.base_threshold
            
        ratio = Decimal(str(self.vol_monitor.get_volatility_ratio()))
        # 计算因波动率激增产生的“超额死区”权重
        excess_vol_factor = max(Decimal("0"), ratio - Decimal("1"))
        adaptive_limit = self.base_threshold * (Decimal("1") + self.k_volatility * excess_vol_factor)
        
        # 硬限幅：最大放宽到 2.0% (4倍基准)，防止对冲完全瘫痪
        return min(adaptive_limit, Decimal("0.02"))

    async def analyze_imbalance_v2(self, spot_qty: Decimal, futures_qty: Decimal, price: Decimal) -> dict:
        """
        执行基于代价函数 (Cost Function) 的不平衡分析。
        """
        delta = spot_qty + futures_qty # 净敞口
        notional_delta = abs(delta * price)
        
        # 1. 计算偏离比例
        deviation_ratio = Decimal("0")
        if spot_qty > 0:
            deviation_ratio = abs(delta) / spot_qty
            
        # 2. 计算动态阈值
        dynamic_threshold = self.get_adaptive_threshold()
        
        # 3. 核心评估: 代价函数判定 (VaR vs Execution Cost)
        # 风险价值 (Risk Exposure): 敞口部分在即时波动下的潜在损失预期
        std_factor = self.vol_monitor.get_current_std() if self.vol_monitor.is_ready() else Decimal("0.0001")
        risk_value = notional_delta * std_factor
        
        # 执行代价 (Execution Cost): 预估手续费 + 盘口滑点
        # 假设最小滑点为价格的 0.01%
        execution_cost = (notional_delta * self.fee_rate) + (notional_delta * Decimal("0.0001"))
        
        # 判定：只有当 潜在风险 > 2倍执行代价 时，且 比例超过动态阈值，才触发真实下单
        needs_fix = (deviation_ratio > dynamic_threshold) and (risk_value > execution_cost * Decimal("2.0"))
        
        # 影子日志：如果满足老版本阈值但不满足代价函数，记录“节省的手续费”
        if not needs_fix and deviation_ratio > self.base_threshold:
            logger.debug(f"[DeltaBalancerV2] 拦截无效调仓: 偏离 {deviation_ratio:.4%}, 风险覆盖率不足, 已节省磨损。")

        return {
            "type": "HEDGE_DELTA_UPDATE",
            "bot_id": self.bot_config.id,
            "data": {
                "delta_qty": float(delta),
                "notional_usdt": float(notional_delta),
                "deviation_ratio": float(deviation_ratio),
                "dynamic_threshold": float(dynamic_threshold),
                "needs_fix": needs_fix,
                "spot_qty": float(spot_qty),
                "futures_qty": float(futures_qty),
                "price": float(price),
                "risk_premium": float(risk_value / execution_cost) if execution_cost > 0 else 0
            }
        }
