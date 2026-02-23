"""
币安交易机器人 — 市场分析器 v2.1

通过技术指标（SMA、RSI、ATR、成交量）自动判断市场状态，
输出网格参数调整建议，驱动策略引擎自适应不同行情。

v2.1 改进（基于回测 -5.25% 亏损的诊断优化）：
- 状态确认机制：连续 N 根 K 线满足才切换，消灭锯齿
- 扩大滞后缓冲区：RSI 缓冲从 5 扩到 10
- 删除宽松突破补充判断
- 冷却期：阴跌/恐慌退出后强制静默 3 根 K 线
"""
import logging
import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from enum import Enum
from src.config.binance_config import Settings

logger = logging.getLogger(__name__)


class MarketState(str, Enum):
    """
    5 种细化市场状态。

    相比 v1 的 4 种状态，将"震荡"拆分为低波动和宽幅两种，
    将"下跌"拆分为阴跌和恐慌两种，提供更精细的策略控制。
    """
    LOW_VOL_RANGE = "低波动横盘"     # 低 ATR + RSI 中性 → 缩减间距加密套利
    WIDE_RANGE = "宽幅震荡"          # 高 ATR + RSI 中性 → 拉大间距防穿仓
    STRONG_BREAKOUT = "强势突破"     # 放量 + 金叉 + RSI>65 → 追踪上移
    SLOW_BLEED = "阴跌收割"         # 缩量 + RSI<35 → 暂停买入拓宽下限
    PANIC_SELL = "恐慌抛售"          # 极高 ATR + RSI<20 → 限额马丁博反弹


@dataclass
class GridAdjustment:
    """
    网格参数调整建议。
    由市场分析器生成，策略引擎据此动态调整网格。
    """
    state: MarketState
    gridCenterShift: Decimal       # 网格中心偏移比例 (-0.1 ~ +0.1)
    densityMultiplier: Decimal     # 网格密度系数 (0.5 ~ 2.0)
    investmentMultiplier: Decimal  # 单格投入系数 (马丁格尔，0.5 ~ 2.0)
    shouldPause: bool              # 是否暂停新建仓
    suggestedGridStep: Decimal | None = None  # ATR 推荐的网格间距

    def __str__(self) -> str:
        step = f", ATR间距={self.suggestedGridStep:.2f}" if self.suggestedGridStep else ""
        return (
            f"[{self.state.value}] "
            f"偏移={self.gridCenterShift:+.1%}, "
            f"密度={self.densityMultiplier:.1f}x, "
            f"投入={self.investmentMultiplier:.1f}x, "
            f"暂停={self.shouldPause}{step}"
        )


class AsymmetricStateController:
    """
    用户推荐：非对称状态控制器。
    核心逻辑：对危险零容忍（秒切），对机会持怀疑态度（确认）。
    """
    def __init__(self, confirmation_candles: int = 2):
        self.current_state = MarketState.LOW_VOL_RANGE
        self.confirmation_candles = confirmation_candles
        # 状态缓冲队列
        self.state_buffer = deque(maxlen=confirmation_candles)
        # 危险状态：阴跌、恐慌
        self.DANGER_STATES = {MarketState.SLOW_BLEED, MarketState.PANIC_SELL}

    def get_confirmed_state(self, raw_state: MarketState) -> MarketState:
        # 1. 路径 A: 危险防御 (0 延迟)
        if raw_state in self.DANGER_STATES:
            if self.current_state != raw_state:
                logger.warning("🚨 风险发现: 立即切换至 %s (熔断逃命)", raw_state.value)
                self.current_state = raw_state
                self.state_buffer.clear()
            return self.current_state

        # 2. 路径 B: 正常信号/机会确认
        if raw_state == self.current_state:
            self.state_buffer.clear()
            return self.current_state

        # 加入缓冲
        self.state_buffer.append(raw_state)

        # 检查是否全部一致且满员
        if len(self.state_buffer) == self.confirmation_candles:
            if all(s == raw_state for s in self.state_buffer):
                logger.info("✅ 状态确认完成: %s (连续 %d 根稳定信号)", raw_state.value, self.confirmation_candles)
                self.current_state = raw_state
                self.state_buffer.clear()
        
        return self.current_state


class MarketAnalyzer:
    """
    市场状态分析器 v2。

    采用多周期确认（MTF）+ 滞后缓冲（Hysteresis）机制，
    输出 5 种细化市场状态和对应的网格调整参数。
    """

    # --- 指标参数 ---
    SMA_SHORT = 7
    SMA_LONG = 25
    RSI_PERIOD = 14
    ATR_PERIOD = 14
    VOLUME_MA_PERIOD = 20
    EMA_MACRO_PERIOD = 200     # v2.2: 宏观牛熊分界线

    # --- 滞后缓冲阈值（v2.1: 缓冲区从 5 扩大到 10） ---
    # NOTE: 进入需要更强信号，退出需要更明确的反转
    ENTER_BREAKOUT_RSI = Decimal("68")
    EXIT_BREAKOUT_RSI = Decimal("58")
    ENTER_BLEED_RSI = Decimal("32")
    EXIT_BLEED_RSI = Decimal("42")
    ENTER_PANIC_RSI = Decimal("18")
    EXIT_PANIC_RSI = Decimal("28")

    # --- ATR 阈值 ---
    ATR_LOW_RATIO = Decimal("0.005")     # ATR/价格 < 0.5% → 低波动
    ATR_HIGH_RATIO = Decimal("0.02")     # ATR/价格 > 2% → 高波动
    ATR_EXTREME_RATIO = Decimal("0.05")  # ATR/价格 > 5% → 极端波动

    # --- 成交量阈值 ---
    VOLUME_SURGE_RATIO = Decimal("1.5")

    # --- ATR 间距系数 ---
    ATR_STEP_MULTIPLIER = Decimal("1.0")
    FEE_SHIELD_RATIO = Decimal("0.002")  # v2.3: 费用盾牌 — 确保网格间距至少覆盖 0.2%

    # --- v2.1: 状态确认 & 冷却期 ---
    CONFIRMATION_CANDLES = 2   # 连续 N 根确认后才正式切换状态
    COOLING_CANDLES = 3        # 退出阴跌/恐慌后的静默 K 线数

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        if settings and hasattr(settings, 'rsiBleedThreshold'):
            self.ENTER_BLEED_RSI = Decimal(str(settings.rsiBleedThreshold))
            self.EXIT_BLEED_RSI = self.ENTER_BLEED_RSI + Decimal("10")
            
        self._controller = AsymmetricStateController(
            confirmation_candles=self.CONFIRMATION_CANDLES
        )
        self._lastAdjustment: GridAdjustment | None = None
        self._lastAnalysisTime: float = 0.0

        # v2.1: 冷却期计数器 — 阴跌/恐慌退出后强制静默
        self._coolingRemaining: int = 0

    def analyze(
        self,
        klinesBig: list[list],
        klinesSmall: list[list] | None = None,
        positionRatio: Decimal = Decimal("0"),  # v2.2: 引入持仓占比
    ) -> GridAdjustment:
        """
        分析 K 线数据，返回网格调整建议。
        支持多周期确认：klinesBig 为大周期（1h），klinesSmall 为小周期（15m）。

        @param klinesBig 大周期 K 线（1h），至少 30 根
        @param klinesSmall 小周期 K 线（15m），可选
        @param positionRatio 当前持仓价值占总资产比例 (0.0 ~ 1.0)
        @returns GridAdjustment 网格调整参数
        """
        if len(klinesBig) < self.SMA_LONG + 5:
            logger.warning("K 线数据不足 (%d 根)，使用默认参数", len(klinesBig))
            return self._defaultAdjustment()

        # --- 大周期指标 ---
        bigCloses = [Decimal(k[4]) for k in klinesBig]
        bigHighs = [Decimal(k[2]) for k in klinesBig]
        bigLows = [Decimal(k[3]) for k in klinesBig]
        bigVolumes = [Decimal(k[5]) for k in klinesBig]

        smaShort = self._calcSMA(bigCloses, self.SMA_SHORT)
        smaLong = self._calcSMA(bigCloses, self.SMA_LONG)
        rsi = self._calcRSI(bigCloses, self.RSI_PERIOD)
        atr = self._calcATR(bigHighs, bigLows, bigCloses, self.ATR_PERIOD)
        volumeRatio = self._calcVolumeRatio(bigVolumes)
        currentPrice = bigCloses[-1]

        # v2.2: 宏观雷达 EMA200
        emaPeriod = self._settings.trendEmaPeriod if self._settings else self.EMA_MACRO_PERIOD
        emaMacro = self._calcEMA(bigCloses, emaPeriod)
        isMacroBullish = currentPrice > emaMacro

        # ATR 相对比例
        atrRatio = atr / currentPrice if currentPrice > 0 else Decimal("0")

        # --- 大趋势判断 ---
        bigTrend: str = "neutral"
        if smaShort > smaLong:
            bigTrend = "bullish"
        elif smaShort < smaLong:
            bigTrend = "bearish"

        smallRsi: Decimal | None = None
        if klinesSmall and len(klinesSmall) > self.RSI_PERIOD + 1:
            smallCloses = [Decimal(k[4]) for k in klinesSmall]
            smallRsi = self._calcRSI(smallCloses, self.RSI_PERIOD)

        logger.info(
            "📊 指标: SMA7=%.2f, SMA25=%.2f, EMA200=%.2f, RSI=%.1f, 大趋势=%s, 宏观=%s",
            smaShort, smaLong, emaMacro, rsi, bigTrend, "牛市" if isMacroBullish else "熊市",
        )

        # --- 综合判断市场状态（带滞后缓冲）---
        rawState = self._determineStateWithHysteresis(
            smaShort, smaLong, rsi, atrRatio, volumeRatio, bigTrend, smallRsi,
        )

        # 1. 保存当前生效状态用于对比（冷却期逻辑需要）
        lastConfirmedState = self._controller.current_state

        # 2. 用户推荐的非对称状态确认模块 (可能触发 0 延迟切换)
        state = self._controller.get_confirmed_state(rawState)

        # 3. 冷却期递减
        if self._coolingRemaining > 0:
            self._coolingRemaining -= 1

        # 4. 检测阴跌/恐慌退出 → 触发冷却期
        if lastConfirmedState in (MarketState.SLOW_BLEED, MarketState.PANIC_SELL):
            if state not in (MarketState.SLOW_BLEED, MarketState.PANIC_SELL):
                self._coolingRemaining = self.COOLING_CANDLES
                logger.info("❄️ 退出危险状态，进入冷却期: %d 根 K 线", self.COOLING_CANDLES)

        # 5. 生成调整参数
        suggestedStep = atr * self.ATR_STEP_MULTIPLIER
        isGoldenCross = smaShort > smaLong # 简单定义金叉
        
        adjustment = self._generateAdjustment(
            state, rsi, atrRatio, volumeRatio, suggestedStep,
            isMacroBullish, positionRatio, isGoldenCross, currentPrice
        )

        # 6. 冷却期内强制暂停
        if self._coolingRemaining > 0 and not adjustment.shouldPause:
            adjustment = GridAdjustment(
                state=adjustment.state,
                gridCenterShift=adjustment.gridCenterShift,
                densityMultiplier=adjustment.densityMultiplier,
                investmentMultiplier=adjustment.investmentMultiplier,
                shouldPause=True,
                suggestedGridStep=adjustment.suggestedGridStep,
            )

        if state != lastConfirmedState:
            logger.info("🔄 市场状态切换: %s → %s", lastConfirmedState.value, state.value)

        self._lastAdjustment = adjustment
        self._lastAnalysisTime = time.time()

        return adjustment

    # ==================================================
    # 技术指标计算
    # ==================================================

    @staticmethod
    def _calcSMA(closes: list[Decimal], period: int) -> Decimal:
        """计算简单移动平均线"""
        if len(closes) < period:
            return closes[-1]
        return sum(closes[-period:]) / period

    @staticmethod
    def _calcEMA(closes: list[Decimal], period: int) -> Decimal:
        """
        计算指数移动平均线 (EMA)。
        公式：EMA = (Price - Prev_EMA) * (2 / (period + 1)) + Prev_EMA
        """
        if len(closes) < period:
            return closes[-1]

        multiplier = Decimal("2") / (Decimal(str(period)) + 1)
        # 初始值采用前 period 根的平均值
        ema = sum(closes[:period]) / period

        for price in closes[period:]:
            ema = (price - ema) * multiplier + ema

        return ema

    @staticmethod
    def _calcRSI(closes: list[Decimal], period: int) -> Decimal:
        """计算相对强弱指标 (RSI)"""
        if len(closes) < period + 1:
            return Decimal("50")

        gains = []
        losses = []
        for i in range(-period, 0):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(Decimal("0"))
            else:
                gains.append(Decimal("0"))
                losses.append(abs(change))

        avgGain = sum(gains) / period
        avgLoss = sum(losses) / period

        if avgLoss == 0:
            return Decimal("100")

        rs = avgGain / avgLoss
        return Decimal("100") - Decimal("100") / (1 + rs)

    @staticmethod
    def _calcATR(
        highs: list[Decimal],
        lows: list[Decimal],
        closes: list[Decimal],
        period: int,
    ) -> Decimal:
        """
        计算平均真实波幅 (ATR)。

        True Range = max(high - low, |high - prevClose|, |low - prevClose|)
        ATR = SMA(TR, period)
        """
        if len(closes) < period + 1:
            # 数据不足时用最近一根的高低差
            if highs and lows:
                return highs[-1] - lows[-1]
            return Decimal("0")

        trueRanges = []
        for i in range(-period, 0):
            high = highs[i]
            low = lows[i]
            prevClose = closes[i - 1]

            tr = max(
                high - low,
                abs(high - prevClose),
                abs(low - prevClose),
            )
            trueRanges.append(tr)

        return sum(trueRanges) / len(trueRanges)

    def _calcVolumeRatio(self, volumes: list[Decimal]) -> Decimal:
        """计算量比（当前量 / 均量）"""
        if len(volumes) < self.VOLUME_MA_PERIOD + 1:
            return Decimal("1")

        currentVolume = volumes[-1]
        avgVolume = sum(volumes[-(self.VOLUME_MA_PERIOD + 1):-1]) / self.VOLUME_MA_PERIOD

        if avgVolume == 0:
            return Decimal("1")

        return currentVolume / avgVolume

    # ==================================================
    # 状态判定（带滞后缓冲）
    # ==================================================

    def _determineStateWithHysteresis(
        self,
        smaShort: Decimal,
        smaLong: Decimal,
        rsi: Decimal,
        atrRatio: Decimal,
        volumeRatio: Decimal,
        bigTrend: str,
        smallRsi: Decimal | None,
    ) -> MarketState:
        """
        带滞后缓冲的状态判定。

        进入某状态需要更强的信号（严格阈值），
        退出当前状态需要更弱的反向信号（宽松阈值），
        避免临界点处反复横跳。
        """
        currentState = self._controller.current_state
        smaBullish = smaShort > smaLong
        smaBearish = smaShort < smaLong
        isHighVolume = volumeRatio >= self.VOLUME_SURGE_RATIO

        # --- 1. 恐慌抛售（最高优先级）---
        if currentState == MarketState.PANIC_SELL:
            # 当前是恐慌状态 → 需要 RSI 回升到退出阈值才能离开
            if rsi > self.EXIT_PANIC_RSI:
                pass  # 继续后续判断
            else:
                return MarketState.PANIC_SELL
        elif rsi <= self.ENTER_PANIC_RSI and atrRatio >= self.ATR_HIGH_RATIO:
            return MarketState.PANIC_SELL

        # --- 2. 强势突破 ---
        if currentState == MarketState.STRONG_BREAKOUT:
            # 已在突破状态 → RSI 需回落到退出阈值才离开
            if rsi >= self.EXIT_BREAKOUT_RSI and smaBullish:
                # NOTE: 多周期确认 — 大周期看跌时降级为宽幅震荡
                if bigTrend == "bearish":
                    return MarketState.WIDE_RANGE
                return MarketState.STRONG_BREAKOUT
        elif rsi >= self.ENTER_BREAKOUT_RSI and smaBullish:
            # 多周期确认：小周期 RSI 也偏强才进入突破
            if smallRsi is None or smallRsi >= Decimal("55"):
                return MarketState.STRONG_BREAKOUT

        # --- 3. 阴跌收割 ---
        if currentState == MarketState.SLOW_BLEED:
            if rsi <= self.EXIT_BLEED_RSI and smaBearish:
                return MarketState.SLOW_BLEED
        elif rsi <= self.ENTER_BLEED_RSI and smaBearish:
            # 多周期确认：大周期确认下跌
            if bigTrend == "bearish":
                return MarketState.SLOW_BLEED

        # --- 4. 放量突破补充判断（v2.1 收紧：需量比+趋势+RSI 三重确认） ---
        if isHighVolume and smaBullish and rsi >= self.ENTER_BREAKOUT_RSI and bigTrend == "bullish":
            return MarketState.STRONG_BREAKOUT

        # --- 5. 波动率分类震荡 ---
        if atrRatio >= self.ATR_HIGH_RATIO:
            return MarketState.WIDE_RANGE

        return MarketState.LOW_VOL_RANGE


    # ==================================================
    # 参数生成
    # ==================================================

    def _generateAdjustment(
        self,
        state: MarketState,
        rsi: Decimal,
        atrRatio: Decimal,
        volumeRatio: Decimal,
        suggestedStep: Decimal,
        isMacroBullish: bool,
        positionRatio: Decimal,
        isGoldenCross: bool = False,
        currentPrice: Decimal = Decimal("0"),
    ) -> GridAdjustment:
        """
        根据市场状态生成网格调整参数，并注入 V2.3 盈利增强矩阵。
        """
        # 1. 获取基础状态建议
        if state == MarketState.LOW_VOL_RANGE:
            adj = self._lowVolRangeAdjustment(atrRatio, suggestedStep)
        elif state == MarketState.WIDE_RANGE:
            adj = self._wideRangeAdjustment(suggestedStep)
        elif state == MarketState.STRONG_BREAKOUT:
            adj = self._breakoutAdjustment(rsi, suggestedStep)
        elif state == MarketState.SLOW_BLEED:
            adj = self._slowBleedAdjustment(rsi, suggestedStep)
        else:  # PANIC_SELL
            adj = self._panicSellAdjustment(volumeRatio, suggestedStep)

        # 2. V2.3 动态密度计算 (Dynamic Density)
        density = adj.densityMultiplier
        if isMacroBullish:
            if isGoldenCross:
                # 黄金回血期：极高频套利
                density = Decimal("1.5")
                logger.info("🚀 黄金回血期：网格密度提升至 1.5x")
            elif Decimal("45") <= rsi <= Decimal("65"):
                # 牛市中性震荡：加密套利
                density = max(density, Decimal("1.2"))
            
            # 牛市抄底增强：若在牛市遭遇恐慌抛售，视为黄金抄底点
            if state == MarketState.PANIC_SELL:
                adj.investmentMultiplier = Decimal("1.8")
                logger.info("💰 牛市黄金坑：抄底权重提升至 1.8x")

        # 极端波动保护：若 ATR 占比超过 5%，主动降低密度
        if atrRatio > self.ATR_EXTREME_RATIO:
            density *= Decimal("0.8")
            logger.warning("⚠️ 极端波动保护：自动降低网格密度以防穿仓")

        # 3. V2.3 费用盾牌 (Fee Shield)
        finalStep = suggestedStep
        if finalStep and currentPrice > 0:
            # 确保单格间距至少大于 0.2% (建议间距已应用了 density 分母效果在策略层)
            # 在此直接计算建议的 step_percent 是否达标
            stepPercent = finalStep / density / currentPrice
            if stepPercent < self.FEE_SHIELD_RATIO:
                # 强制撑开网格，或者降低密度
                # 方案：修正 density 使得 stepPercent = FEE_SHIELD_RATIO
                density = finalStep / (currentPrice * self.FEE_SHIELD_RATIO)
                logger.info("🛡️ 费用盾牌触发：修正密度为 %.2f 以保证利润空间", float(density))

        # 4. V2.3 宏观大势惩罚与 MaxInvest
        maxInvest = Decimal("2.0")
        if not isMacroBullish:
            # 熊市维持现状，且拓宽网格
            finalStep *= Decimal("1.2")
            maxInvest = Decimal("1.0")

        # 5. V2.3 Smart Brake 2.0 (平方衰减)
        # 公式：M_final = M_base * max(decayMin, (1 - positionRatio)^2)
        decayMin = self._settings.decayMinMultiplier if self._settings else Decimal("0.2")
        # 平方衰减：对低持仓更友好（回血快），对高持仓更狠（刹车猛）
        safetyMargin = Decimal("1") - positionRatio
        decayFactor = max(decayMin, safetyMargin * safetyMargin)
        
        finalInvest = min(maxInvest, adj.investmentMultiplier * decayFactor)

        if decayFactor < Decimal("1") and positionRatio > Decimal("0.1"):
            logger.info("📉 Smart Brake 2.0 生效：因子=%.2f, 最终投入=%.2fx", float(decayFactor), float(finalInvest))

        return GridAdjustment(
            state=state,
            gridCenterShift=adj.gridCenterShift,
            densityMultiplier=density,
            investmentMultiplier=finalInvest,
            shouldPause=adj.shouldPause,
            suggestedGridStep=finalStep,
        )

    @staticmethod
    def _lowVolRangeAdjustment(atrRatio: Decimal, step: Decimal) -> GridAdjustment:
        """
        低波动横盘：缩减间距加密套利。
        波动率越低，密度越高。
        """
        if atrRatio < Decimal("0.003"):
            density = Decimal("2.0")
        elif atrRatio < Decimal("0.005"):
            density = Decimal("1.5")
        else:
            density = Decimal("1.2")

        return GridAdjustment(
            state=MarketState.LOW_VOL_RANGE,
            gridCenterShift=Decimal("0"),
            densityMultiplier=density,
            investmentMultiplier=Decimal("1.0"),
            shouldPause=False,
            suggestedGridStep=step,
        )

    @staticmethod
    def _wideRangeAdjustment(step: Decimal) -> GridAdjustment:
        """
        宽幅震荡：拉大间距防穿仓。
        保持标准投入，用 ATR 间距防止被秒穿。
        """
        return GridAdjustment(
            state=MarketState.WIDE_RANGE,
            gridCenterShift=Decimal("0"),
            densityMultiplier=Decimal("0.7"),  # 减少密度拉大间距
            investmentMultiplier=Decimal("1.0"),
            shouldPause=False,
            suggestedGridStep=step,
        )

    @staticmethod
    def _breakoutAdjustment(rsi: Decimal, step: Decimal) -> GridAdjustment:
        """
        强势突破：向上追踪 + 减少卖单挂量。
        RSI 越高，上移幅度越大。
        """
        shift = Decimal("0.03")
        if rsi > Decimal("70"):
            shift = Decimal("0.06")

        return GridAdjustment(
            state=MarketState.STRONG_BREAKOUT,
            gridCenterShift=shift,
            densityMultiplier=Decimal("0.8"),
            investmentMultiplier=Decimal("0.7"),  # 上涨时减少投入
            shouldPause=False,
            suggestedGridStep=step,
        )

    @staticmethod
    def _slowBleedAdjustment(rsi: Decimal, step: Decimal) -> GridAdjustment:
        """
        阴跌收割：暂停买入 + 拓宽下限。
        保护本金，等待底部确立。
        """
        return GridAdjustment(
            state=MarketState.SLOW_BLEED,
            gridCenterShift=Decimal("-0.03"),
            densityMultiplier=Decimal("0.6"),
            investmentMultiplier=Decimal("0.5"),  # 大幅减少投入
            shouldPause=True,  # 暂停新建仓
            suggestedGridStep=step,
        )

    @staticmethod
    def _panicSellAdjustment(volumeRatio: Decimal, step: Decimal) -> GridAdjustment:
        """
        恐慌抛售：限额马丁加仓博反弹。
        只在极端超卖时小额抄底。
        """
        # NOTE: 放量恐慌时可以更积极一点
        investment = Decimal("1.3")
        if volumeRatio > Decimal("2.0"):
            investment = Decimal("1.5")

        return GridAdjustment(
            state=MarketState.PANIC_SELL,
            gridCenterShift=Decimal("-0.08"),
            densityMultiplier=Decimal("0.5"),
            investmentMultiplier=investment,
            shouldPause=False,  # 允许限额抄底
            suggestedGridStep=step,
        )

    def _defaultAdjustment(self) -> GridAdjustment:
        """数据不足时的默认参数"""
        return GridAdjustment(
            state=self._controller.current_state,
            gridCenterShift=Decimal("0"),
            densityMultiplier=Decimal("1.0"),
            investmentMultiplier=Decimal("1.0"),
            shouldPause=False,
            suggestedGridStep=None,
        )

    @property
    def lastState(self) -> MarketState:
        return self._controller.current_state

    @property
    def lastAdjustment(self) -> GridAdjustment | None:
        return self._lastAdjustment

    @property
    def lastAnalysisTime(self) -> float:
        return self._lastAnalysisTime
