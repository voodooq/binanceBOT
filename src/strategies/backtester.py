"""
币安交易机器人 — 历史回测脚本 v2

从币安 API 下载历史 K 线数据，逐根喂给 MarketAnalyzer，
记录状态转换时间点并生成可视化报告。

v2 增强：
- 状态持续时间分布（热力图分析，检测锯齿切换）
- 恐慌滑点模拟（PANIC_SELL 增加额外损耗）
- 模拟净值曲线（验证策略在极端行情下的盈亏）

用法:
    python -m src.strategies.backtester --symbol BNBUSDT --days 30
    python -m src.strategies.backtester --symbol BTCUSDT --days 60 --slippage 0.005
"""
import argparse
import asyncio
import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal

from dotenv import load_dotenv
from binance import AsyncClient

from src.strategies.market_analyzer import MarketAnalyzer, MarketState

# 加载 .env 配置（代理等）
load_dotenv()

logger = logging.getLogger(__name__)


async def fetchHistoricalKlines(
    symbol: str,
    interval: str,
    days: int,
    testnet: bool = False,
) -> list[list]:
    """从币安 API 下载历史 K 线数据（自动使用 .env 中的代理）"""
    proxyUrl = os.getenv("PROXY_URL")
    if proxyUrl:
        logger.info("🌐 使用代理: %s", proxyUrl)

    client = await AsyncClient.create(
        testnet=testnet,
        https_proxy=proxyUrl,
    )

    try:
        startTime = datetime.utcnow() - timedelta(days=days)
        startStr = startTime.strftime("%d %b %Y")

        klines = await client.get_historical_klines(
            symbol=symbol,
            interval=interval,
            start_str=startStr,
        )
        logger.info("📥 下载 %d 根 %s K 线 (%s, 最近 %d 天)", len(klines), interval, symbol, days)
        return klines
    finally:
        await client.close_connection()


def runBacktest(
    klines: list[list],
    windowSize: int = 50,
    slippageRate: float = 0.003,
    feeRate: float = 0.001,
) -> tuple[list[dict], list[dict]]:
    """
    逐根 K 线喂给 MarketAnalyzer，记录状态和模拟交易净值。

    @param klines 完整历史 K 线
    @param windowSize 每次分析使用的窗口大小
    @param slippageRate 恐慌状态下的额外滑点率
    @param feeRate 单边手续费率
    """
    analyzer = MarketAnalyzer()
    transitions = []
    stateHistory = []

    # --- 模拟净值追踪 ---
    initialCapital = 10000.0
    capital = initialCapital       # USDT 账户
    holdings = 0.0                 # 持仓数量
    gridInvestment = 150.0         # 单格投入
    tradeLog: list[dict] = []

    for i in range(windowSize, len(klines)):
        window = klines[i - windowSize:i]
        
        # --- v2.2: 计算当前持仓占比 ---
        closePrice = float(klines[i][4])
        totalEquity = capital + holdings * closePrice
        posRatio = Decimal(str(holdings * closePrice / totalEquity)) if totalEquity > 0 else Decimal("0")
        
        adjustment = analyzer.analyze(window, positionRatio=posRatio)

        closeTime = datetime.utcfromtimestamp(int(klines[i][6]) / 1000)
        state = adjustment.state

        # --- 滑点模拟：恐慌状态下增加额外损耗 ---
        effectiveSlippage = 0.0
        if state == MarketState.PANIC_SELL:
            effectiveSlippage = slippageRate

        stateHistory.append({
            "time": closeTime,
            "price": closePrice,
            "state": state.value,
            "shift": float(adjustment.gridCenterShift),
            "density": float(adjustment.densityMultiplier),
            "investment": float(adjustment.investmentMultiplier),
            "pause": adjustment.shouldPause,
            "atrStep": float(adjustment.suggestedGridStep) if adjustment.suggestedGridStep else None,
            "slippage": effectiveSlippage,
        })

        # --- 简化模拟交易（验证策略方向是否正确）---
        investMultiplier = float(adjustment.investmentMultiplier)
        actualInvestment = gridInvestment * investMultiplier

        if not adjustment.shouldPause and capital >= actualInvestment:
            # 模拟买入（扣除手续费 + 滑点）
            buyPrice = closePrice * (1 + feeRate + effectiveSlippage)
            qty = actualInvestment / buyPrice
            capital -= actualInvestment
            holdings += qty
            tradeLog.append({
                "time": closeTime, "action": "BUY", "price": buyPrice,
                "qty": qty, "state": state.value, "slippage": effectiveSlippage,
            })

        # 检查卖出时机：如果持仓且当前价 > 平均成本 + 手续费
        if holdings > 0 and len(tradeLog) > 0:
            lastBuy = [t for t in tradeLog if t["action"] == "BUY"]
            if lastBuy:
                avgCost = sum(t["price"] for t in lastBuy[-3:]) / min(len(lastBuy), 3)
                sellThreshold = avgCost * (1 + feeRate * 2 + effectiveSlippage)
                if closePrice > sellThreshold:
                    sellPrice = closePrice * (1 - feeRate - effectiveSlippage)
                    sellQty = holdings * 0.5  # 分批卖出
                    capital += sellQty * sellPrice
                    holdings -= sellQty
                    tradeLog.append({
                        "time": closeTime, "action": "SELL", "price": sellPrice,
                        "qty": sellQty, "state": state.value, "slippage": effectiveSlippage,
                    })

        # 记录净值
        totalEquity = capital + holdings * closePrice
        stateHistory[-1]["equity"] = totalEquity

        # 状态转换
        if len(stateHistory) >= 2 and stateHistory[-1]["state"] != stateHistory[-2]["state"]:
            transitions.append({
                "time": closeTime,
                "price": closePrice,
                "from": stateHistory[-2]["state"],
                "to": stateHistory[-1]["state"],
            })

    return transitions, stateHistory


def printReport(
    transitions: list[dict],
    stateHistory: list[dict],
    slippageRate: float,
    feeRate: float,
) -> None:
    """打印完整回测报告"""
    print("\n" + "=" * 70)
    print("📊 MarketAnalyzer 历史回测报告 v2")
    print("=" * 70)

    if not stateHistory:
        print("❌ 无数据")
        return

    totalBars = len(stateHistory)

    # --- 基础信息 ---
    print(f"\n📈 总 K 线数: {totalBars}")
    print(f"📅 时间范围: {stateHistory[0]['time']} ~ {stateHistory[-1]['time']}")
    print(f"💰 价格范围: {min(s['price'] for s in stateHistory):.2f} ~ {max(s['price'] for s in stateHistory):.2f}")
    print(f"🔄 状态切换次数: {len(transitions)}")
    print(f"📉 恐慌滑点: {slippageRate*100:.1f}%  |  手续费: {feeRate*100:.2f}%")

    # --- 状态分布 ---
    stateCounts: dict[str, int] = {}
    for s in stateHistory:
        stateCounts[s["state"]] = stateCounts.get(s["state"], 0) + 1

    print("\n📊 状态分布:")
    for state, count in sorted(stateCounts.items(), key=lambda x: -x[1]):
        pct = count / totalBars * 100
        bar = "█" * int(pct / 2)
        print(f"  {state:12s}: {count:5d} ({pct:5.1f}%) {bar}")

    # --- 状态持续时间分布（热力图分析）---
    print("\n🔥 状态持续时间分布 (检测锯齿切换):")
    currentState = stateHistory[0]["state"]
    stateStart = 0
    durations: dict[str, list[int]] = {}

    for i in range(1, len(stateHistory)):
        if stateHistory[i]["state"] != currentState:
            duration = i - stateStart
            if currentState not in durations:
                durations[currentState] = []
            durations[currentState].append(duration)
            currentState = stateHistory[i]["state"]
            stateStart = i

    # 最后一段
    lastDuration = len(stateHistory) - stateStart
    if currentState not in durations:
        durations[currentState] = []
    durations[currentState].append(lastDuration)

    sawtoothWarning = False
    for state, durs in sorted(durations.items()):
        avgDur = sum(durs) / len(durs)
        maxDur = max(durs)
        minDur = min(durs)
        shortCount = sum(1 for d in durs if d <= 3)  # 短于3根K线的状态段

        # 质量评估
        if avgDur < 5 and len(durs) > 3:
            quality = "⚠️ 锯齿"
            sawtoothWarning = True
        elif avgDur < 10:
            quality = "🟡 偏短"
        else:
            quality = "✅ 健康"

        print(f"  {state:12s}: 平均={avgDur:5.1f}根, 最短={minDur}, 最长={maxDur}, "
              f"切换{len(durs):3d}次, 短暂(<3根)={shortCount}次 {quality}")

    if sawtoothWarning:
        print("\n  ⚠️ 检测到锯齿切换! 建议增大 RSI 缓冲区 (当前=5，建议调到 8-10)")

    # --- 状态转换详情 ---
    if transitions:
        print(f"\n🔄 最近 30 次状态转换:")
        for t in transitions[-30:]:
            print(f"  [{t['time']}] @ {t['price']:.2f}: {t['from']} → {t['to']}")

    # --- 净值曲线 ---
    print("\n💰 模拟净值曲线:")
    initialEquity = stateHistory[0].get("equity", 10000)
    finalEquity = stateHistory[-1].get("equity", 10000)
    maxEquity = max(s.get("equity", 10000) for s in stateHistory)
    minEquity = min(s.get("equity", 10000) for s in stateHistory)
    maxDrawdownPct = (maxEquity - minEquity) / maxEquity * 100 if maxEquity > 0 else 0
    totalReturn = (finalEquity - initialEquity) / initialEquity * 100

    # 计算卡玛比率 (Calmar Ratio)
    # Calmar = 年化收益率 / 最大回撤
    days = (stateHistory[-1]["time"] - stateHistory[0]["time"]).days or 1
    annualizedReturn = (totalReturn / days) * 365
    calmarRatio = annualizedReturn / maxDrawdownPct if maxDrawdownPct > 0 else 0

    print(f"  初始资金: {initialEquity:.2f} USDT")
    print(f"  最终净值: {finalEquity:.2f} USDT")
    print(f"  总收益率: {totalReturn:+.2f}% (年化: {annualizedReturn:+.1f}%)")
    print(f"  最高净值: {maxEquity:.2f}")
    print(f"  最低净值: {minEquity:.2f}")
    print(f"  最大回撤: {maxDrawdownPct:.2f}%")
    print(f"  卡玛比率: {calmarRatio:.2f} (年化收益 / 最大回撤)")

    # 各状态下的滑点损耗
    totalSlippage = sum(s["slippage"] for s in stateHistory if s["slippage"] > 0)
    panicBars = sum(1 for s in stateHistory if s["state"] == MarketState.PANIC_SELL.value)
    print(f"\n🚨 恐慌状态下的额外滑点损耗:")
    print(f"  恐慌 K 线数: {panicBars}")
    print(f"  累计滑点: {totalSlippage*100:.3f}%")

    # 净值变化趋势（取样10个点）
    step = max(1, totalBars // 10)
    print(f"\n📈 净值趋势 (每 {step} 根采样):")
    for i in range(0, totalBars, step):
        eq = stateHistory[i].get("equity", 10000)
        pnl = (eq - initialEquity) / initialEquity * 100
        bar = "▓" * max(0, int(pnl / 2)) if pnl > 0 else "░" * max(0, int(-pnl / 2))
        print(f"  [{stateHistory[i]['time']}] {eq:10.2f} ({pnl:+6.2f}%) {bar}")

    print("\n" + "=" * 70)
    # 综合结论，引入卡玛比率评价
    if totalReturn > 0:
        if calmarRatio >= 2.0:
            print("💎 结论: 表现卓越 (Calmar > 2.0)，策略极具实盘竞争力")
        elif calmarRatio >= 1.0:
            print("✅ 结论: 表现合格 (Calmar 1.0~2.0)，回撤控制在可接受范围")
        else:
            print("🟡 结论: 收益覆盖不足 (Calmar < 1.0)，最大回撤风险较高，建议收紧风控参数")
    else:
        print("🔴 结论: 策略亏损，请检查参数或市场适配性")
    print("=" * 70)


async def main() -> None:
    parser = argparse.ArgumentParser(description="MarketAnalyzer 历史回测 v2")
    parser.add_argument("--symbol", default="BNBUSDT", help="交易对")
    parser.add_argument("--interval", default="1h", help="K 线周期")
    parser.add_argument("--days", type=int, default=30, help="回测天数")
    parser.add_argument("--testnet", action="store_true", help="使用测试网")
    parser.add_argument("--slippage", type=float, default=0.003, help="恐慌状态滑点率 (默认: 0.3%%)")
    parser.add_argument("--fee", type=float, default=0.001, help="单边手续费率 (默认: 0.1%%)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    print(f"\n🚀 开始回测: {args.symbol} {args.interval} 最近 {args.days} 天")
    print(f"   恐慌滑点: {args.slippage*100:.1f}% | 手续费: {args.fee*100:.2f}%")

    klines = await fetchHistoricalKlines(
        symbol=args.symbol,
        interval=args.interval,
        days=args.days,
        testnet=args.testnet,
    )

    if len(klines) < 50:
        print("❌ K 线数据不足（少于 50 根），无法回测")
        return

    transitions, stateHistory = runBacktest(
        klines,
        slippageRate=args.slippage,
        feeRate=args.fee,
    )
    printReport(transitions, stateHistory, args.slippage, args.fee)


if __name__ == "__main__":
    asyncio.run(main())
