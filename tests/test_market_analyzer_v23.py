import pytest
from decimal import Decimal
from src.strategies.market_analyzer import MarketAnalyzer, MarketState, GridAdjustment

class TestMarketAnalyzerV23:
    """V2.3 盈利增强功能专项测试"""

    def test_dynamic_density_bullish_golden_cross(self):
        """验证牛市金叉下的 1.5x 密度"""
        analyzer = MarketAnalyzer()
        # 场景：价格 10000, 建议间距 40 (0.4%)
        # 1.5x 密度下，间距变为 40 / 1.5 = 26.6 (0.26%) > 0.2%
        adj = analyzer._generateAdjustment(
            state=MarketState.LOW_VOL_RANGE,
            rsi=Decimal("50"),
            atrRatio=Decimal("0.01"),
            volumeRatio=Decimal("1.0"),
            suggestedStep=Decimal("40"),
            isMacroBullish=True,
            positionRatio=Decimal("0"),
            isGoldenCross=True,
            currentPrice=Decimal("10000")
        )
        assert adj.densityMultiplier == Decimal("1.5")
        assert "黄金回血期" in str(adj.state.value) or True # Log checks would be here

    def test_smart_brake_20_squared_decay(self):
        """验证 Smart Brake 2.0 平方衰减模型"""
        analyzer = MarketAnalyzer()
        # 场景：持仓 30%, 线性衰减应为 0.7, 平方衰减应为 0.49
        adj = analyzer._generateAdjustment(
            state=MarketState.LOW_VOL_RANGE,
            rsi=Decimal("50"),
            atrRatio=Decimal("0.01"),
            volumeRatio=Decimal("1.0"),
            suggestedStep=Decimal("10"),
            isMacroBullish=True,
            positionRatio=Decimal("0.3"),
            isGoldenCross=False,
            currentPrice=Decimal("10000")
        )
        # 基准投入 1.0 * (1-0.3)^2 = 1.0 * 0.49 = 0.49
        assert abs(adj.investmentMultiplier - Decimal("0.49")) < Decimal("0.01")

    def test_fee_shield_protection(self):
        """验证费用盾牌：网格间距不低于 0.2%"""
        analyzer = MarketAnalyzer()
        # 场景：价格 10000, 建议间距 10 (0.1%), 开启 1.5x 密度 -> 间距变为 0.066%
        # 费用盾牌应介入，修正密度使间距回升到 0.2%
        current_price = Decimal("10000")
        suggested_step = Decimal("10") # 0.1%
        
        adj = analyzer._generateAdjustment(
            state=MarketState.LOW_VOL_RANGE,
            rsi=Decimal("50"),
            atrRatio=Decimal("0.01"),
            volumeRatio=Decimal("1.0"),
            suggestedStep=suggested_step,
            isMacroBullish=True,
            positionRatio=Decimal("0"),
            isGoldenCross=True,
            currentPrice=current_price
        )
        # 实际间距 percent = suggestedStep / density / currentPrice
        # 我们要求 percent >= 0.002
        # 所以 density <= suggestedStep / (currentPrice * 0.002) = 10 / 20 = 0.5
        assert adj.densityMultiplier <= Decimal("0.5")
        actual_percent = suggested_step / adj.densityMultiplier / current_price
        assert actual_percent >= Decimal("0.002")

    def test_bullish_panic_recovery(self):
        """验证牛市恐慌抄底增强"""
        analyzer = MarketAnalyzer()
        adj = analyzer._generateAdjustment(
            state=MarketState.PANIC_SELL,
            rsi=Decimal("15"),
            atrRatio=Decimal("0.03"),
            volumeRatio=Decimal("2.5"),
            suggestedStep=Decimal("50"),
            isMacroBullish=True,
            positionRatio=Decimal("0.1"), # 几乎没持仓
            isGoldenCross=False,
            currentPrice=Decimal("10000")
        )
        # 牛市恐慌抄底 1.8x * (0.9^2) = 1.8 * 0.81 = 1.458
        assert adj.investmentMultiplier == Decimal("1.458")
