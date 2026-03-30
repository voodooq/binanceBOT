import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, AlertTriangle, Coins, RotateCcw, Sparkles, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface LiveGridMonitorProps {
    bot: any;
    currentPrice: number | null;
    isConnected: boolean;
    connectionStatus: "idle" | "connecting" | "connected" | "reconnecting" | "error";
    lastMessageAt: number | null;
    lastProfitEvent: any;
    profitEventVersion: number;
    onReconnect: () => void;
}

export function LiveGridMonitor({
    bot,
    currentPrice,
    isConnected,
    connectionStatus,
    lastMessageAt,
    lastProfitEvent,
    profitEventVersion,
    onReconnect,
}: LiveGridMonitorProps) {
    const [displayPrice, setDisplayPrice] = useState<number | null>(currentPrice);
    const [showProfitAnim, setShowProfitAnim] = useState(false);
    const animationFrameRef = useRef<number | null>(null);
    const profitAnimTimerRef = useRef<number | null>(null);

    // 解析网格参数
    const lower = parseFloat(bot.parameters?.grid_lower_price || "0");
    const upper = parseFloat(bot.parameters?.grid_upper_price || "0");
    const count = parseInt(bot.parameters?.grid_count || "0");
    const step = count > 0 ? (upper - lower) / count : 0;

    const isDataStale = useMemo(() => {
        if (!lastMessageAt) return false;
        return Date.now() - lastMessageAt > 15000;
    }, [lastMessageAt]);

    const linkLabel = useMemo(() => {
        if (isConnected && !isDataStale) return "WS Linked";
        if (connectionStatus === "reconnecting") return "Reconnecting";
        if (connectionStatus === "connecting") return "Connecting";
        if (isDataStale) return "Data Stale";
        return "Disconnected";
    }, [connectionStatus, isConnected, isDataStale]);

    useEffect(() => {
        if (currentPrice === null || Number.isNaN(currentPrice)) {
            setDisplayPrice(null);
            return;
        }

        if (displayPrice === null) {
            setDisplayPrice(currentPrice);
            return;
        }

        if (animationFrameRef.current !== null) {
            cancelAnimationFrame(animationFrameRef.current);
        }

        const animate = () => {
            setDisplayPrice((prev) => {
                if (prev === null) return currentPrice;

                const delta = currentPrice - prev;
                if (Math.abs(delta) < 0.0001) {
                    return currentPrice;
                }

                const next = prev + delta * 0.18;
                animationFrameRef.current = requestAnimationFrame(animate);
                return next;
            });
        };

        animationFrameRef.current = requestAnimationFrame(animate);

        return () => {
            if (animationFrameRef.current !== null) {
                cancelAnimationFrame(animationFrameRef.current);
                animationFrameRef.current = null;
            }
        };
    }, [currentPrice]);

    useEffect(() => {
        if (!profitEventVersion || !lastProfitEvent) return;

        setShowProfitAnim(true);
        if (profitAnimTimerRef.current !== null) {
            window.clearTimeout(profitAnimTimerRef.current);
        }
        profitAnimTimerRef.current = window.setTimeout(() => {
            setShowProfitAnim(false);
        }, 3000);

        return () => {
            if (profitAnimTimerRef.current !== null) {
                window.clearTimeout(profitAnimTimerRef.current);
                profitAnimTimerRef.current = null;
            }
        };
    }, [lastProfitEvent, profitEventVersion]);

    if (bot.status?.toUpperCase() !== "RUNNING") {
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

    if (displayPrice === null) {
        return (
            <div className="flex flex-col h-full bg-zinc-950 rounded-2xl border border-zinc-800 p-6 font-mono">
                <div className="animate-pulse flex items-center justify-center h-full text-zinc-500">
                    正在等待 WebSocket 行情推送...
                </div>
            </div>
        );
    }

    const safePrice = displayPrice ?? 0;
    const safeStep = step > 0 ? step : 1;

    let nextBuy = 0;
    let nextSell = 0;
    let inRange = false;

    if (safePrice < lower) {
        nextBuy = lower;
        nextSell = lower + safeStep;
    } else if (safePrice > upper) {
        nextBuy = upper - safeStep;
        nextSell = upper;
    } else {
        inRange = true;
        const gridsAboveLower = safeStep > 0 ? (safePrice - lower) / safeStep : 0;
        const currentGridIndex = Math.floor(gridsAboveLower);
        nextBuy = lower + currentGridIndex * safeStep;
        nextSell = lower + (currentGridIndex + 1) * safeStep;
    }

    const distBuy = Math.max(0, safePrice - nextBuy);
    const distSell = Math.max(0, nextSell - safePrice);
    const buyPercent = safePrice > 0 ? (distBuy / safePrice) * 100 : 0;
    const sellPercent = safePrice > 0 ? (distSell / safePrice) * 100 : 0;

    return (
        <div className="flex flex-col h-full bg-zinc-950 rounded-2xl border border-zinc-800 overflow-hidden font-mono text-sm relative shadow-2xl">
            {/* [P3] 波动爆炸 / 配对利润爆炸特效层 */}
            <AnimatePresence>
                {showProfitAnim && (
                    <motion.div
                        initial={{ opacity: 0, scale: 0.8 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 1.2 }}
                        className="absolute inset-0 z-50 flex items-center justify-center pointer-events-none"
                    >
                        <div className="relative">
                            {/* 背景光晕 */}
                            <motion.div
                                animate={{ rotate: 360 }}
                                transition={{ duration: 10, repeat: Infinity, ease: "linear" }}
                                className="absolute inset-0 -m-20 bg-gradient-conic from-yellow-500/0 via-yellow-500/40 to-yellow-500/0 blur-2xl rounded-full"
                            />

                            <div className="relative bg-zinc-900/90 border-2 border-yellow-500/50 p-8 rounded-3xl shadow-[0_0_50px_rgba(234,179,8,0.3)] flex flex-col items-center gap-4 backdrop-blur-md">
                                <motion.div
                                    animate={{ y: [0, -10, 0] }}
                                    transition={{ duration: 2, repeat: Infinity }}
                                    className="p-4 bg-yellow-500 rounded-full text-black shadow-[0_0_20px_rgba(234,179,8,0.5)]"
                                >
                                    <Coins className="w-10 h-10" />
                                </motion.div>
                                <div className="text-center">
                                    <h4 className="text-yellow-500 font-black text-2xl mb-1 uppercase tracking-tighter italic">Matched Profit!</h4>
                                    <p className="text-zinc-400 text-xs">格位 #{lastProfitEvent?.grid_index} 成功配对平仓</p>
                                </div>
                                <div className="text-4xl font-black text-white flex items-center gap-2">
                                    +{lastProfitEvent?.profit.toFixed(4)}
                                    <span className="text-sm text-zinc-500">USDT</span>
                                </div>
                                <div className="flex gap-2 items-center text-[10px] text-zinc-500 border-t border-zinc-800 pt-3 mt-1 w-full justify-center">
                                    <Sparkles className="w-3 h-3 text-yellow-500" />
                                    <span>累计已实现 PnL: {lastProfitEvent?.total_pnl.toFixed(4)} USDT</span>
                                </div>
                            </div>

                            {/* 粒子喷发 */}
                            {[...Array(8)].map((_, i) => (
                                <motion.div
                                    key={i}
                                    initial={{ x: 0, y: 0, opacity: 1 }}
                                    animate={{ x: (i - 4) * 40, y: -200, opacity: 0 }}
                                    transition={{ duration: 1, delay: i * 0.05 }}
                                    className="absolute top-1/2 left-1/2 w-2 h-2 bg-yellow-400 rounded-full"
                                />
                            ))}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            <div className="flex items-center justify-between px-6 py-4 bg-zinc-900/50 border-b border-zinc-800">
                <div className="flex items-center gap-2 text-zinc-400">
                    <Activity className="w-4 h-4 text-green-500" />
                    <span className="font-bold uppercase tracking-wider text-zinc-200">实时水位监测仪 (V3)</span>
                </div>
                <div className="flex items-center gap-2">
                    <div
                        className={`w-2 h-2 rounded-full ${
                            isConnected && !isDataStale
                                ? "bg-green-500 animate-pulse"
                                : connectionStatus === "reconnecting" || connectionStatus === "connecting"
                                ? "bg-amber-500 animate-pulse"
                                : "bg-red-500"
                        }`}
                    />
                    <span className="text-zinc-500 text-[10px] uppercase font-bold tracking-widest">
                        {linkLabel}
                    </span>
                </div>
            </div>

            <div className="flex-1 p-8 flex flex-col justify-center space-y-10 relative">
                {/* Upper Status */}
                <AnimatePresence>
                    {!inRange && safePrice > upper && (
                        <motion.div
                            initial={{ y: -20, opacity: 0 }}
                            animate={{ y: 0, opacity: 1 }}
                            className="text-red-400 text-center border border-red-500/20 bg-red-500/10 p-2 rounded text-xs font-bold"
                        >
                            🚀 价格已突破网格上限！暂停开仓。
                        </motion.div>
                    )}
                </AnimatePresence>

                {/* Sell Distance */}
                <div className="flex flex-col gap-3 relative">
                    <div className="flex justify-between text-zinc-400 items-baseline">
                        <span className="text-[10px] uppercase font-bold tracking-tighter">Next Sell Logic</span>
                        <span className="font-bold text-red-500 text-lg">{nextSell.toFixed(4)}</span>
                    </div>
                    <div className="h-2 bg-zinc-900 rounded-full overflow-hidden border border-zinc-800">
                        <motion.div
                            animate={{ width: `${Math.min(100, Math.max(0, (1 - distSell / safeStep) * 100))}%` }}
                            transition={{ duration: 0.2, ease: "easeOut" }}
                            className="h-full bg-gradient-to-r from-red-500/10 to-red-500 shadow-[0_0_10px_rgba(239,68,68,0.3)]"
                        />
                    </div>
                    <div className="flex items-center gap-1 text-red-500 text-[10px] mt-1 font-bold">
                        <Zap className="w-3 h-3 fill-red-500/20" />
                        UP +{sellPercent.toFixed(2)}% TO TRIGGER
                    </div>
                </div>

                {/* Main Price Display */}
                <div className="py-8 border-y border-zinc-800/50 flex flex-col items-center justify-center relative bg-white/[0.02] rounded-3xl group transition-all hover:bg-white/[0.04]">
                    <div className="absolute inset-0 bg-green-500/5 blur-3xl rounded-full opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />
                    <span className="text-zinc-600 text-[10px] mb-2 uppercase tracking-[0.3em] font-black">MARKET PRICE</span>
                    <div className="flex items-baseline gap-2">
                        <motion.span
                            key={displayPrice?.toFixed(4)}
                            initial={{ opacity: 0.5 }}
                            animate={{ opacity: 1 }}
                            className="text-6xl font-black text-white tracking-tighter"
                        >
                            {displayPrice.toFixed(4)}
                        </motion.span>
                        <span className="text-zinc-500 font-bold">USDT</span>
                    </div>
                </div>

                {/* Buy Distance */}
                <div className="flex flex-col gap-3">
                    <div className="flex justify-between text-zinc-400 items-baseline">
                        <span className="text-[10px] uppercase font-bold tracking-tighter">Next Buy Logic</span>
                        <span className="font-bold text-green-500 text-lg">{nextBuy.toFixed(4)}</span>
                    </div>
                    <div className="h-2 bg-zinc-900 rounded-full overflow-hidden flex justify-end border border-zinc-800">
                        <motion.div
                            animate={{ width: `${Math.min(100, Math.max(0, (1 - distBuy / safeStep) * 100))}%` }}
                            transition={{ duration: 0.2, ease: "easeOut" }}
                            className="h-full bg-gradient-to-l from-green-500/10 to-green-500 shadow-[0_0_10px_rgba(34,197,94,0.3)]"
                        />
                    </div>
                    <div className="flex items-center justify-end gap-1 text-green-500 text-[10px] mt-1 font-bold">
                        DOWN -{buyPercent.toFixed(2)}% TO TRIGGER
                        <Zap className="w-3 h-3 fill-green-500/20" />
                    </div>
                </div>

                {/* Lower Status */}
                <AnimatePresence>
                    {!inRange && safePrice < lower && (
                        <motion.div
                            initial={{ y: 20, opacity: 0 }}
                            animate={{ y: 0, opacity: 1 }}
                            className="text-amber-400 text-center border border-amber-500/20 bg-amber-500/10 p-2 rounded text-xs font-bold"
                        >
                            📉 价格已跌破网格下限！进入保护。
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>

            <div className="px-6 py-3 bg-zinc-900/30 border-t border-zinc-800 flex justify-between items-center text-[10px] text-zinc-600 font-bold">
                <div className="flex items-center gap-3 flex-wrap">
                    <span className="flex items-center gap-1"><div className="w-1 h-1 rounded-full bg-zinc-700" /> RANGE: {lower} - {upper}</span>
                    <span className="flex items-center gap-1"><div className="w-1 h-1 rounded-full bg-zinc-700" /> GRIDS: {count}</span>
                    <span className="flex items-center gap-1">
                        <div className="w-1 h-1 rounded-full bg-zinc-700" />
                        LAST UPDATE: {lastMessageAt ? new Date(lastMessageAt).toLocaleTimeString() : "--"}
                    </span>
                </div>
                <div className="flex items-center gap-3">
                    {isDataStale && (
                        <span className="flex items-center gap-1 text-amber-400">
                            <AlertTriangle className="w-3 h-3" />
                            DATA STALE
                        </span>
                    )}
                    {!isConnected && (
                        <button
                            onClick={onReconnect}
                            className="flex items-center gap-1 text-zinc-300 hover:text-white transition-colors"
                        >
                            <RotateCcw className="w-3 h-3" />
                            RETRY
                        </button>
                    )}
                    <div className="flex items-center gap-1">
                        <Activity className="w-3 h-3" />
                        ENGINE ACTIVE
                    </div>
                </div>
            </div>
        </div>
    );
}
