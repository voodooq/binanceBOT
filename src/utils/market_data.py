import numpy as np
import collections
from decimal import Decimal
import logging

logger = logging.getLogger("VolatilityMonitor")

class VolatilityMonitor:
    """
    市场波动率监控组件。
    基于收益率标准差计算即时波动率与历史平均波动率的比值（Volatility Ratio）。
    """
    def __init__(self, window: int = 14):
        """
        @param window: 计算平均波动率的时间窗口（采样点数量）
        """
        self.window = window
        # 使用 deque 存储最近的价格和对数收益率
        self.price_history = collections.deque(maxlen=window + 1)
        self.returns_history = collections.deque(maxlen=window)
        
        self.current_std = 0.0
        self.avg_std = 0.0

    def update(self, new_price: float):
        """
        实时注入价格更新并重新计算指标
        """
        self.price_history.append(new_price)
        
        if len(self.price_history) > 1:
            # 计算对数收益率：log(P_t / P_{t-1})
            prev_price = self.price_history[-2]
            if prev_price > 0 and new_price > 0:
                log_return = np.log(new_price / prev_price)
                self.returns_history.append(log_return)
            
            # 当数据量达到窗口大小时更新标准差
            if len(self.returns_history) >= self.window:
                self._calculate_metrics()

    def _calculate_metrics(self):
        """内部滚动计算核心波动指标"""
        returns_array = np.array(self.returns_history)
        
        # 1. 计算当前窗口的收益率标准差 (即时波动)
        self.current_std = np.std(returns_array)
        
        # 2. 更新历史平均波动率 (使用 EMA 平滑基准)
        if self.avg_std == 0:
            self.avg_std = self.current_std
        else:
            alpha = 0.1 # 平滑系数，越小对长期基准越迟钝
            self.avg_std = (alpha * self.current_std) + (1 - alpha) * self.avg_std

    def get_volatility_ratio(self) -> float:
        """
        获取当前波动率相对于基准的比值。
        > 1.5 通常意味着行情进入高波动剧震期。
        """
        if self.avg_std == 0:
            return 1.0
        return self.current_std / self.avg_std

    def get_current_std(self) -> Decimal:
        """返回 Decimal 格式的当前标准差，用于代价函数计算"""
        return Decimal(str(round(self.current_std, 8)))

    def is_ready(self) -> bool:
        """判断是否已完成冷启动采样"""
        return len(self.returns_history) >= self.window
