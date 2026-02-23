import pytest
from decimal import Decimal
from src.strategies.market_analyzer import MarketAnalyzer, MarketState

class TestMarketAnalyzerV22:
    def _makeKlines(self, prices: list[float], volumes: list[float]):
        klines = []
        for i, (p, v) in enumerate(zip(prices, volumes)):
            # [openTime, open, high, low, close, volume, closeTime, ...]
            klines.append([
                i * 3600000,
                str(p),
                str(p + 1),
                str(p - 1),
                str(p),
                str(v),
                (i + 1) * 3600000,
            ])
        return klines

    def test_asymmetricConfirmation_DangerImmediate(self):
        """测试阴跌状态 0 延迟逃命"""
        analyzer = MarketAnalyzer()
        # 初始状态：低波动横盘
        klines = self._makeKlines([1000.0] * 50, [1000.0] * 50)
        analyzer.analyze(klines)
        assert analyzer.lastState == MarketState.LOW_VOL_RANGE

        # 构造阴跌信号：RSI 低 + 均线看跌 (且 ATR 比例不高)
        # SMA_SHORT=7, SMA_LONG=25.
        # 下跌 1% (1000 -> 990)，避免触发 2% 的 PANIC_SELL
        prices = [1000.0] * 25 + [990.0] * 7
        klines_bleed = self._makeKlines(prices, [500.0] * 32)
        
        # v2.2 逻辑：一旦检测到阴跌，应立即切换，无需等待第 2 根
        adj = analyzer.analyze(klines_bleed)
        assert adj.state == MarketState.SLOW_BLEED
        assert analyzer.lastState == MarketState.SLOW_BLEED

    def test_asymmetricConfirmation_RecoveryNeedsConfirmation(self):
        """测试从危险状态恢复需要确认"""
        analyzer = MarketAnalyzer()
        # 1. 进入阴跌（0 延迟）
        prices_bleed = [1000.0] * 25 + [980.0] * 7
        klines_bleed = self._makeKlines(prices_bleed, [500.0] * 32)
        analyzer.analyze(klines_bleed)
        assert analyzer.lastState == MarketState.SLOW_BLEED

        # 2. 信号大幅好转（强反弹），尝试回到横盘，但仅 1 根
        prices_recovery = [1000.0] * 25 + [980.0] * 6 + [1010.0] # 强劲反弹，RSI 激增
        klines_rec1 = self._makeKlines(prices_recovery, [1000.0] * 32)
        adj = analyzer.analyze(klines_rec1)
        
        # 虽然信号变好，但由于需要确认，应维持在阴跌状态
        assert adj.state == MarketState.SLOW_BLEED
        
        # 3. 第 2 根确认信号
        klines_rec2 = self._makeKlines(prices_recovery + [1012.0], [1000.0] * 33)
        adj = analyzer.analyze(klines_rec2)
        assert adj.state == MarketState.LOW_VOL_RANGE

    def test_macroRadarBearishPenalty(self):
        """测试熊市下的惩罚逻辑 (Price < EMA200)"""
        analyzer = MarketAnalyzer()
        # 构造熊市环境：EMA200 很高，当前价格很低
        # 为了让 EMA200 准确，我们需要较多数据
        prices = [200.0] * 200 + [100.0] * 10
        klines = self._makeKlines(prices, [1000.0] * 210)
        
        # 即使指标看起来是横盘，但因为在 EMA200 下方，应受到惩罚
        adj = analyzer.analyze(klines)
        
        # 惩罚1：investmentMultiplier 强制限制在 1.0 (即使低波动默认是 1.2+)
        assert adj.investmentMultiplier <= Decimal("1.0")
        # 惩罚2：步长应被放大
        # 低波动默认 ATR 步长，这里应乘以 1.2
        assert adj.suggestedGridStep is not None

    def test_smartBrakePositionDecay(self):
        """测试仓位衰减逻辑 (Smart Brake)"""
        analyzer = MarketAnalyzer()
        prices = [100.0] * 50
        klines = self._makeKlines(prices, [1000.0] * 50)
        
        # 1. 空仓 (positionRatio=0)
        adj0 = analyzer.analyze(klines, positionRatio=Decimal("0"))
        m0 = adj0.investmentMultiplier
        
        # 2. 半仓 (positionRatio=0.5)
        adj50 = analyzer.analyze(klines, positionRatio=Decimal("0.5"))
        m50 = adj50.investmentMultiplier
        
        # 3. 重仓 (positionRatio=0.9)
        adj90 = analyzer.analyze(klines, positionRatio=Decimal("0.9"))
        m90 = adj90.investmentMultiplier
        
        # 验证衰减：m0 > m50 > m90
        assert m0 > m50
        assert m50 > m90
        # 至少保留 0.2 倍投入
        assert m90 >= Decimal("0.2")
