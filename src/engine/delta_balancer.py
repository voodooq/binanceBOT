import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

class DeltaBalancer:
    """
    期现对冲平衡器 (Delta Balancer)。
    专门用于量化并管理现货 (Spot) 与 U 本位合约 (Futures) 之间的风险敞口差额。
    """
    
    def __init__(self, threshold_percent: Decimal = Decimal("0.005")):
        """
        @param threshold_percent: 允许的最大偏移阈值，默认 0.5%。超过此值将触发同步补单。
        """
        self.threshold_percent = threshold_percent

    def get_exposure(self, spot_qty: Decimal, futures_qty: Decimal) -> Decimal:
        """
        计算绝对净敞口 (Delta)。
        对冲场景下：Spot Qty (多) + Futures Qty (空/负) = 0 为理想态。
        """
        return spot_qty + futures_qty

    def analyze_imbalance(self, spot_qty: Decimal, futures_qty: Decimal, mid_price: Decimal) -> dict:
        """
        分析不平衡状态及其修正方案。
        """
        delta = self.get_exposure(spot_qty, futures_qty)
        notional_delta = abs(delta * mid_price)
        
        # 计算偏移比例 (相对于现货持仓)
        deviation_ratio = Decimal("0")
        if spot_qty > 0:
            deviation_ratio = abs(delta) / spot_qty

        needs_fix = deviation_ratio > self.threshold_percent
        
        return {
            "delta_qty": delta, # >0 表示现货多，需要空合约； <0 表示现货少，需要买现货或平合约
            "notional_usdt": notional_delta,
            "deviation_ratio": deviation_ratio,
            "needs_fix": needs_fix,
            "fix_action": "SELL_FUTURES" if delta > 0 else "BUY_FUTURES" # 简单演示，实际可能需要买现货
        }

# 单例辅助工具类
delta_balancer = DeltaBalancer()
