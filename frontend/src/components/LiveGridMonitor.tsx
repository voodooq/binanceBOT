import { useState, useEffect } from "react";
import { Activity, ArrowDown, ArrowUp } from "lucide-react";
import { api } from "@/lib/api";

interface LiveGridMonitorProps {
    bot: any;
}

export function LiveGridMonitor({ bot }: LiveGridMonitorProps) {
    const [currentPrice, setCurrentPrice] = useState<number | null>(null);
    const [error, setError] = useState<string | null>(null);

    // 解析网格参数
    const lower = parseFloat(bot.parameters?.grid_lower_price || "0");
    const upper = parseFloat(bot.parameters?.grid_upper_price || "0");
    const count = parseInt(bot.parameters?.grid_count || "0");

    useEffect(() => {
        if (!bot.symbol || bot.status !== "RUNNING") return;

        const fetchPrice = async () => {
            try {
                const resp = await api.get(`/market/price?symbol=${bot.symbol}`);
                setCurrentPrice(parseFloat(resp.data.price));
                setError(null);
            } catch (err: any) {
                setError("数据同步延迟");
            }
        };

        fetchPrice();
        const timer = setInterval(fetchPrice, 3000);
        return () => clearInterval(timer);
    }, [bot.symbol, bot.status]);

    if (bot.status !== "RUNNING") {
        return (
            <div className="flex flex-col h-full bg-zinc-950 rounded-2xl border border-zinc-800 p-6 font-mono">
                <div className="flex items-center gap-2 text-zinc-400 mb-6">
                    <Activity className="w-4 h-4" />
                    <span className="font-bold uppercase tracking-wider">实时水位监控</span>
                </div>
                <div className="flex-1 flex flex-col items-center justify-center text-zinc-600 gap-4">
                    <Activity className="w-8 h-8 opacity-20" />
                    机器人未在运行或无行情流
                </div>
            </div>
        );
    }

    if (currentPrice === null) {
        return (
            <div className="flex flex-col h-full bg-zinc-950 rounded-2xl border border-zinc-800 p-6 font-mono">
                <div className="animate-pulse flex items-center justify-center h-full text-zinc-500">
                    正在连接市场数据...
                </div>
            </div>
        );
    }

    // 计算网格属性
    const step = count > 0 ? (upper - lower) / count : 0;

    let nextBuy = 0;
    let nextSell = 0;
    let inRange = false;

    if (currentPrice < lower) {
        nextBuy = lower;
        nextSell = lower + step; // 超跌等待涨回首格
    } else if (currentPrice > upper) {
        nextBuy = upper - step;
        nextSell = upper; // 超涨
    } else {
        inRange = true;
        const gridsAboveLower = (currentPrice - lower) / step;
        const currentGridIndex = Math.floor(gridsAboveLower);
        nextBuy = lower + currentGridIndex * step;
        nextSell = lower + (currentGridIndex + 1) * step;
    }

    // 防御性防止浮点数计算误差
    const distBuy = Math.max(0, currentPrice - nextBuy);
    const distSell = Math.max(0, nextSell - currentPrice);

    const buyPercent = (distBuy / currentPrice) * 100;
    const sellPercent = (distSell / currentPrice) * 100;

    return (
        <div className="flex flex-col h-full bg-zinc-950 rounded-2xl border border-zinc-800 overflow-hidden font-mono text-sm relative shadow-xl">
            <div className="flex items-center justify-between px-6 py-4 bg-zinc-900/50 border-b border-zinc-800">
                <div className="flex items-center gap-2 text-zinc-400">
                    <Activity className="w-4 h-4" />
                    <span className="font-bold uppercase tracking-wider text-green-400">实时网络监测仪</span>
                </div>
                <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                    <span className="text-zinc-500 text-xs">实时同步</span>
                </div>
            </div>

            <div className="flex-1 p-8 flex flex-col justify-center space-y-10">
                {/* Upper Status */}
                {!inRange && currentPrice > upper && (
                    <div className="text-red-400 text-center animate-pulse border border-red-500/20 bg-red-500/10 p-2 rounded">
                        🚀 价格已突破网格上限！暂停开仓。
                    </div>
                )}

                {/* Sell Distance */}
                <div className="flex flex-col gap-3 relative">
                    <div className="flex justify-between text-zinc-400">
                        <span>等待触发卖单价位</span>
                        <span className="font-bold text-red-400">{nextSell.toFixed(4)} <span className="text-xs text-zinc-500">USDT</span></span>
                    </div>
                    <div className="h-1.5 bg-zinc-900 rounded-full overflow-hidden">
                        <div className="h-full bg-gradient-to-r from-red-500/20 to-red-500" style={{ width: `${Math.min(100, (1 - distSell / step) * 100)}%` }} />
                    </div>
                    <div className="flex items-center gap-1 text-red-500 text-xs mt-1 font-bold">
                        <ArrowUp className="w-3 h-3" />
                        距离触发挂出此卖单还差 {distSell.toFixed(4)} USDT (+{sellPercent.toFixed(2)}%)
                    </div>
                </div>

                {/* Current Price */}
                <div className="py-6 border-y border-zinc-800/50 flex flex-col items-center justify-center relative bg-zinc-900/20 rounded-xl">
                    <span className="text-zinc-500 text-xs mb-1 uppercase tracking-widest font-bold">当前币价市价</span>
                    <div className="flex items-baseline gap-2">
                        <span className="text-5xl font-black text-white">{currentPrice.toFixed(4)}</span>
                    </div>
                </div>

                {/* Buy Distance */}
                <div className="flex flex-col gap-3">
                    <div className="flex justify-between text-zinc-400">
                        <span>等待触发买单价位</span>
                        <span className="font-bold text-green-400">{nextBuy.toFixed(4)} <span className="text-xs text-zinc-500">USDT</span></span>
                    </div>
                    <div className="h-1.5 bg-zinc-900 rounded-full overflow-hidden flex justify-end">
                        {/* 买入进度是从上往下掉，离买点越近进度条越满 */}
                        <div className="h-full bg-gradient-to-l from-green-500/20 to-green-500" style={{ width: `${Math.min(100, (1 - distBuy / step) * 100)}%` }} />
                    </div>
                    <div className="flex items-center justify-end gap-1 text-green-500 text-xs mt-1 font-bold">
                        距离触发吃进此买单还差 {distBuy.toFixed(4)} USDT (-{buyPercent.toFixed(2)}%)
                        <ArrowDown className="w-3 h-3" />
                    </div>
                </div>

                {/* Lower Status */}
                {!inRange && currentPrice < lower && (
                    <div className="text-amber-400 text-center animate-pulse border border-amber-500/20 bg-amber-500/10 p-2 rounded">
                        📉 价格已跌破网格下限！进入保护。
                    </div>
                )}
            </div>
            {error && <div className="absolute bottom-4 right-6 text-xs text-zinc-600 italic flex items-center gap-1"><div className="w-1.5 h-1.5 rounded-full bg-zinc-700" /> {error}</div>}
        </div>
    );
}
