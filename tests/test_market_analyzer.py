"""
市场分析器 v2.1 单元测试

覆盖：SMA/RSI/ATR 计算、滞后缓冲、多周期确认、
5 种市场状态判定、ATR 动态间距、参数生成、
状态确认机制、冷却期保护。
"""
import pytest
from decimal import Decimal
from src.strategies.market_analyzer import (
    MarketAnalyzer, MarketState, GridAdjustment,
)


class TestSMACalculation:
    """简单移动平均线计算"""

    def test_normalSMA(self):
        closes = [Decimal(str(i)) for i in range(1, 11)]
        result = MarketAnalyzer._calcSMA(closes, 5)
        assert result == Decimal("8")

    def test_insufficientData(self):
        closes = [Decimal("100")]
        result = MarketAnalyzer._calcSMA(closes, 5)
        assert result == Decimal("100")


class TestRSICalculation:
    """相对强弱指标计算"""

    def test_allGains(self):
        closes = [Decimal(str(i)) for i in range(100, 120)]
        rsi = MarketAnalyzer._calcRSI(closes, 14)
        assert rsi == Decimal("100")

    def test_allLosses(self):
        closes = [Decimal(str(i)) for i in range(120, 100, -1)]
        rsi = MarketAnalyzer._calcRSI(closes, 14)
        assert rsi < Decimal("5")

    def test_neutral(self):
        closes = []
        for i in range(30):
            closes.append(Decimal("100") + Decimal(str(i % 2)))
        rsi = MarketAnalyzer._calcRSI(closes, 14)
        assert Decimal("40") < rsi < Decimal("60")

    def test_insufficientData(self):
        closes = [Decimal("100")]
        rsi = MarketAnalyzer._calcRSI(closes, 14)
        assert rsi == Decimal("50")


class TestATRCalculation:
    """平均真实波幅 (ATR) 计算"""

    def test_normalATR(self):
        # 构造简单的高低收数据
        highs = [Decimal("110")] * 20
        lows = [Decimal("90")] * 20
        closes = [Decimal("100")] * 20
        atr = MarketAnalyzer._calcATR(highs, lows, closes, 14)
        # TR = max(110-90, |110-100|, |90-100|) = 20
        assert atr == Decimal("20")

    def test_insufficientData(self):
        highs = [Decimal("110")]
        lows = [Decimal("90")]
        closes = [Decimal("100")]
        atr = MarketAnalyzer._calcATR(highs, lows, closes, 14)
        assert atr == Decimal("20")  # 用最近一根的高低差


class TestVolumeRatio:
    """成交量比计算"""

    def test_normalVolume(self):
        analyzer = MarketAnalyzer()
        volumes = [Decimal("100")] * 21
        ratio = analyzer._calcVolumeRatio(volumes)
        assert Decimal("0.9") < ratio < Decimal("1.1")

    def test_highVolume(self):
        analyzer = MarketAnalyzer()
        volumes = [Decimal("100")] * 20 + [Decimal("200")]
        ratio = analyzer._calcVolumeRatio(volumes)
        assert Decimal("1.9") < ratio < Decimal("2.1")


class TestHysteresisStateDetection:
    """滞后缓冲状态判定"""

    def test_enterPanic(self):
        analyzer = MarketAnalyzer()
        state = analyzer._determineStateWithHysteresis(
            smaShort=Decimal("90"), smaLong=Decimal("100"),
            rsi=Decimal("15"), atrRatio=Decimal("0.03"),
            volumeRatio=Decimal("2.0"), bigTrend="bearish", smallRsi=None,
        )
        assert state == MarketState.PANIC_SELL

    def test_stayInPanicUntilExit(self):
        analyzer = MarketAnalyzer()
        # 进入恐慌
        analyzer._controller.current_state = MarketState.PANIC_SELL
        # RSI 回升到 25（还没到退出阈值 28）→ 仍然恐慌
        state = analyzer._determineStateWithHysteresis(
            smaShort=Decimal("95"), smaLong=Decimal("100"),
            rsi=Decimal("25"), atrRatio=Decimal("0.03"),
            volumeRatio=Decimal("1.0"), bigTrend="bearish", smallRsi=None,
        )
        assert state == MarketState.PANIC_SELL

    def test_exitPanic(self):
        analyzer = MarketAnalyzer()
        analyzer._controller.current_state = MarketState.PANIC_SELL
        # RSI 回升到 35 → 已经超过退出阈值 28 → 应该离开恐慌
        state = analyzer._determineStateWithHysteresis(
            smaShort=Decimal("100"), smaLong=Decimal("100"),
            rsi=Decimal("35"), atrRatio=Decimal("0.01"),
            volumeRatio=Decimal("1.0"), bigTrend="neutral", smallRsi=None,
        )
        assert state != MarketState.PANIC_SELL

    def test_enterBreakout(self):
        analyzer = MarketAnalyzer()
        state = analyzer._determineStateWithHysteresis(
            smaShort=Decimal("105"), smaLong=Decimal("100"),
            rsi=Decimal("70"), atrRatio=Decimal("0.01"),
            volumeRatio=Decimal("1.0"), bigTrend="bullish", smallRsi=Decimal("60"),
        )
        assert state == MarketState.STRONG_BREAKOUT

    def test_stayInBreakoutWithHysteresis(self):
        analyzer = MarketAnalyzer()
        analyzer._controller.current_state = MarketState.STRONG_BREAKOUT
        # RSI 降到 60（仍然高于退出阈值 58）→ 保持突破
        state = analyzer._determineStateWithHysteresis(
            smaShort=Decimal("102"), smaLong=Decimal("100"),
            rsi=Decimal("60"), atrRatio=Decimal("0.01"),
            volumeRatio=Decimal("1.0"), bigTrend="bullish", smallRsi=None,
        )
        assert state == MarketState.STRONG_BREAKOUT

    def test_enterSlowBleed(self):
        analyzer = MarketAnalyzer()
        state = analyzer._determineStateWithHysteresis(
            smaShort=Decimal("95"), smaLong=Decimal("100"),
            rsi=Decimal("30"), atrRatio=Decimal("0.01"),
            volumeRatio=Decimal("0.8"), bigTrend="bearish", smallRsi=None,
        )
        assert state == MarketState.SLOW_BLEED


class TestMTFConfirmation:
    """多周期确认"""

    def test_bigBearishBlocksBreakout(self):
        """大周期看跌时，即使 RSI 高也不应进入突破"""
        analyzer = MarketAnalyzer()
        state = analyzer._determineStateWithHysteresis(
            smaShort=Decimal("102"), smaLong=Decimal("100"),
            rsi=Decimal("66"), atrRatio=Decimal("0.01"),
            volumeRatio=Decimal("1.0"), bigTrend="bearish",
            smallRsi=Decimal("50"),  # 小周期弱
        )
        # 大周期看跌 + 小周期弱 → 不应进入突破
        assert state != MarketState.STRONG_BREAKOUT

    def test_bigBullishAllowsBreakout(self):
        analyzer = MarketAnalyzer()
        state = analyzer._determineStateWithHysteresis(
            smaShort=Decimal("105"), smaLong=Decimal("100"),
            rsi=Decimal("70"), atrRatio=Decimal("0.01"),
            volumeRatio=Decimal("1.5"), bigTrend="bullish",
            smallRsi=Decimal("65"),  # 小周期也强
        )
        assert state == MarketState.STRONG_BREAKOUT


class TestWideRangeDetection:
    """宽幅震荡判定"""

    def test_highATRNeutralRSI(self):
        analyzer = MarketAnalyzer()
        state = analyzer._determineStateWithHysteresis(
            smaShort=Decimal("100"), smaLong=Decimal("100"),
            rsi=Decimal("50"), atrRatio=Decimal("0.03"),
            volumeRatio=Decimal("1.0"), bigTrend="neutral", smallRsi=None,
        )
        assert state == MarketState.WIDE_RANGE


class TestGridAdjustmentGeneration:
    """网格调整参数生成"""

    def test_lowVolRange(self):
        adj = MarketAnalyzer._lowVolRangeAdjustment(Decimal("0.003"), Decimal("5"))
        assert adj.state == MarketState.LOW_VOL_RANGE
        assert adj.densityMultiplier > Decimal("1")
        assert adj.suggestedGridStep == Decimal("5")

    def test_wideRange(self):
        adj = MarketAnalyzer._wideRangeAdjustment(Decimal("10"))
        assert adj.state == MarketState.WIDE_RANGE
        assert adj.densityMultiplier < Decimal("1")  # 减少密度

    def test_breakout(self):
        adj = MarketAnalyzer._breakoutAdjustment(Decimal("72"), Decimal("8"))
        assert adj.state == MarketState.STRONG_BREAKOUT
        assert adj.gridCenterShift > Decimal("0")  # 上移
        assert adj.investmentMultiplier < Decimal("1")  # 减少投入

    def test_slowBleedPause(self):
        adj = MarketAnalyzer._slowBleedAdjustment(Decimal("30"), Decimal("6"))
        assert adj.state == MarketState.SLOW_BLEED
        assert adj.shouldPause is True

    def test_panicSellHighVolume(self):
        adj = MarketAnalyzer._panicSellAdjustment(Decimal("2.5"), Decimal("15"))
        assert adj.state == MarketState.PANIC_SELL
        assert adj.investmentMultiplier == Decimal("1.5")  # 放量加仓
        assert adj.shouldPause is False  # 允许限额抄底


class TestFullAnalysis:
    """完整分析流程"""

    def _makeKlines(self, closes: list[float], volumes: list[float]) -> list[list]:
        klines = []
        for i, (c, v) in enumerate(zip(closes, volumes)):
            klines.append([
                i * 3600000,
                str(c),
                str(c * 1.01),
                str(c * 0.99),
                str(c),
                str(v),
                (i + 1) * 3600000,
            ])
        return klines

    def test_insufficientData(self):
        analyzer = MarketAnalyzer()
        klines = self._makeKlines([100] * 5, [1000] * 5)
        adj = analyzer.analyze(klines)
        assert adj.state == MarketState.LOW_VOL_RANGE

    def test_withMultiTimeframe(self):
        analyzer = MarketAnalyzer()
        big = self._makeKlines([100.0 + i * 0.1 for i in range(50)], [1000.0] * 50)
        small = self._makeKlines([100.0 + i * 0.05 for i in range(50)], [500.0] * 50)
        adj = analyzer.analyze(big, small)
        assert adj.suggestedGridStep is not None

    def test_analysisTimeUpdated(self):
        analyzer = MarketAnalyzer()
        assert analyzer.lastAnalysisTime == 0.0
        klines = self._makeKlines([100.0 + i * 0.1 for i in range(50)], [1000.0] * 50)
        analyzer.analyze(klines)
        assert analyzer.lastAnalysisTime > 0


class TestStateConfirmation:
    """状态确认机制（v2.2 非对称）"""

    def test_singleCandleDoesNotSwitch(self):
        """单根 K 线不应切换状态"""
        analyzer = MarketAnalyzer()
        analyzer._controller.current_state = MarketState.LOW_VOL_RANGE
        # 第 1 根：原始状态计算为 STRONG_BREAKOUT → 但尚未确认
        result = analyzer._controller.get_confirmed_state(MarketState.STRONG_BREAKOUT)
        assert result == MarketState.LOW_VOL_RANGE  # 维持原状态

    def test_twoCandlesConfirmSwitch(self):
        """连续 2 根确认后应切换"""
        analyzer = MarketAnalyzer()
        analyzer._controller.current_state = MarketState.LOW_VOL_RANGE
        # 第 1 根
        analyzer._controller.get_confirmed_state(MarketState.STRONG_BREAKOUT)
        # 第 2 根
        result = analyzer._controller.get_confirmed_state(MarketState.STRONG_BREAKOUT)
        assert result == MarketState.STRONG_BREAKOUT

    def test_interruptedConfirmationResets(self):
        """确认中间被打断应重置"""
        analyzer = MarketAnalyzer()
        analyzer._controller.current_state = MarketState.LOW_VOL_RANGE
        # 第 1 根：BREAKOUT
        analyzer._controller.get_confirmed_state(MarketState.STRONG_BREAKOUT)
        # 第 2 根：变成 SLOW_BLEED → 打断 (且 SLOW_BLEED 是危险状态，会秒切)
        result = analyzer._controller.get_confirmed_state(MarketState.SLOW_BLEED)
        assert result == MarketState.SLOW_BLEED 
        
        # 验证缓存已清空且不可被之前的状态确认
        analyzer._controller.get_confirmed_state(MarketState.STRONG_BREAKOUT)
        assert analyzer._controller.current_state == MarketState.SLOW_BLEED

    def test_panicSkipsConfirmation(self):
        """恐慌招售应跳过确认立即切换"""
        analyzer = MarketAnalyzer()
        analyzer._controller.current_state = MarketState.LOW_VOL_RANGE
        result = analyzer._controller.get_confirmed_state(MarketState.PANIC_SELL)
        assert result == MarketState.PANIC_SELL

    def test_sameStateResetsCounter(self):
        """原始状态与当前一致时重置计数器"""
        analyzer = MarketAnalyzer()
        analyzer._controller.current_state = MarketState.LOW_VOL_RANGE
        analyzer._controller.get_confirmed_state(MarketState.STRONG_BREAKOUT)  # 开始确认
        analyzer._controller.get_confirmed_state(MarketState.LOW_VOL_RANGE)  # 回到原状态
        assert len(analyzer._controller.state_buffer) == 0


class TestCoolingPeriod:
    """冷却期保护（v2.1）"""

    def _makeKlines(self, closes: list[float], volumes: list[float]) -> list[list]:
        klines = []
        for i, (c, v) in enumerate(zip(closes, volumes)):
            klines.append([
                i * 3600000, str(c), str(c * 1.01),
                str(c * 0.99), str(c), str(v), (i + 1) * 3600000,
            ])
        return klines

    def test_coolingAfterBleed(self):
        """阴跌退出后应进入冷却期"""
        analyzer = MarketAnalyzer()
        analyzer._controller.current_state = MarketState.SLOW_BLEED
        analyzer._coolingRemaining = 0
        # 模拟退出阴跌：给一组横盘数据
        klines = self._makeKlines([100.0] * 50, [1000.0] * 50)
        adj = analyzer.analyze(klines)
        # 应进入冷却期 -> shouldPause=True
        assert analyzer._coolingRemaining > 0 or adj.shouldPause

    def test_coolingDecrement(self):
        """冷却期每次分析递减"""
        analyzer = MarketAnalyzer()
        analyzer._coolingRemaining = 3
        klines = self._makeKlines([100.0] * 50, [1000.0] * 50)
        analyzer.analyze(klines)
        assert analyzer._coolingRemaining == 2
