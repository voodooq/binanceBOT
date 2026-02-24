import { Play, Square, AlertCircle, Info, Trash2, Cpu } from "lucide-react";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type BotStatus = "RUNNING" | "STOPPED" | "ERROR" | "IDLE";

interface BotCardProps {
    bot: {
        id: number;
        name: string;
        symbol: string;
        status: BotStatus;
        total_pnl: string;
        strategy_type: string;
        parameters?: any;
    };
    onStart: (id: number) => void;
    onStop: (id: number) => void;
    onDelete: (id: number) => void;
    onViewDetails: (id: number) => void;
}

export function BotCard({ bot, onStart, onStop, onDelete, onViewDetails }: BotCardProps) {
    const botStatus = String(bot.status).toUpperCase();
    const isRunning = botStatus === "RUNNING";
    const isError = botStatus === "ERROR";

    // 获取实时行情
    const { data: currentPrice } = useQuery({
        queryKey: ["mini-price", bot.symbol],
        queryFn: async () => {
            const resp = await api.get(`/market/price?symbol=${bot.symbol}`);
            return parseFloat(resp.data.price);
        },
        enabled: isRunning,
        refetchInterval: 3000,
        staleTime: 2000,
    });

    const lower = parseFloat(bot.parameters?.grid_lower_price || "0");
    const upper = parseFloat(bot.parameters?.grid_upper_price || "0");
    const count = parseInt(bot.parameters?.grid_count || "0");
    const step = count > 0 ? (upper - lower) / count : 0;

    let miniMonitor = null;

    if (isRunning && currentPrice && currentPrice > 0 && count > 0) {
        let nextBuy = 0;
        let nextSell = 0;
        let inRange = false;

        if (currentPrice < lower) {
            nextBuy = lower;
            nextSell = lower + step;
        } else if (currentPrice > upper) {
            nextBuy = upper - step;
            nextSell = upper;
        } else {
            inRange = true;
            const gridsAboveLower = (currentPrice - lower) / step;
            const currentGridIndex = Math.floor(gridsAboveLower);
            nextBuy = lower + currentGridIndex * step;
            nextSell = lower + (currentGridIndex + 1) * step;
        }

        const distBuy = Math.max(0, currentPrice - nextBuy);
        const distSell = Math.max(0, nextSell - currentPrice);
        const buyPercent = (distBuy / currentPrice) * 100;
        const sellPercent = (distSell / currentPrice) * 100;

        miniMonitor = (
            <div className="mt-4 p-4 rounded-xl bg-zinc-950/5 dark:bg-zinc-950 border border-border/50 font-mono text-xs shadow-inner">
                <div className="flex justify-between items-center mb-3">
                    <span className="text-muted-foreground uppercase font-bold text-[10px]">当前市价</span>
                    <span className="font-bold text-sm tracking-tight">{currentPrice.toFixed(4)} <span className="text-[10px] text-muted-foreground font-normal">USDT</span></span>
                </div>

                {!inRange && currentPrice > upper && (
                    <div className="text-red-500/80 mb-2 font-bold animate-pulse text-[10px] text-center">🚀 突破上限，暂停开仓</div>
                )}
                {!inRange && currentPrice < lower && (
                    <div className="text-amber-500/80 mb-2 font-bold animate-pulse text-[10px] text-center">📉 跌破下限，触发保护</div>
                )}

                {inRange && (
                    <div className="flex flex-col gap-2 relative mt-1">
                        <div className="flex items-center gap-2">
                            <span className="text-[10px] text-muted-foreground w-8">卖出</span>
                            <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                                <div className="h-full bg-red-400" style={{ width: `${Math.min(100, (1 - distSell / step) * 100)}%` }} />
                            </div>
                            <span className="text-[10px] text-red-500 w-10 text-right">-{sellPercent.toFixed(2)}%</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-[10px] text-muted-foreground w-8">买入</span>
                            <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden flex justify-end">
                                <div className="h-full bg-green-400" style={{ width: `${Math.min(100, (1 - distBuy / step) * 100)}%` }} />
                            </div>
                            <span className="text-[10px] text-green-500 w-10 text-right">-{buyPercent.toFixed(2)}%</span>
                        </div>
                    </div>
                )}
            </div>
        );
    }

    return (
        <div className="p-6 rounded-2xl bg-card border border-border shadow-sm hover:shadow-md transition-shadow group">
            <div className="flex justify-between items-start mb-4">
                <div className="flex items-center gap-3">
                    <div className={cn(
                        "p-2 rounded-xl",
                        isRunning ? "bg-green-500/10 text-green-500" :
                            isError ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground"
                    )}>
                        <Cpu className="w-5 h-5" />
                    </div>
                    <div>
                        <h3 className="font-bold text-lg">{bot.name}</h3>
                        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-tight">
                            {bot.symbol} • {bot.strategy_type}
                        </p>
                    </div>
                </div>

                <div className={cn(
                    "px-2 py-1 rounded-md text-[10px] font-bold uppercase",
                    isRunning ? "bg-green-500/20 text-green-600 dark:text-green-400" :
                        isError ? "bg-destructive/20 text-destructive" : "bg-muted text-muted-foreground"
                )}>
                    {bot.status}
                </div>
            </div>

            {miniMonitor}

            <div className="flex items-end justify-between mt-6 pt-4 border-t border-border/40">
                <div>
                    <p className="text-[10px] text-muted-foreground uppercase font-bold">累计收益 (USDT)</p>
                    <p className={cn(
                        "text-xl font-bold tracking-tight",
                        parseFloat(bot.total_pnl) >= 0 ? "text-green-500" : "text-destructive"
                    )}>
                        {parseFloat(bot.total_pnl) >= 0 ? "+" : ""}{parseFloat(bot.total_pnl).toFixed(4)}
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    {isRunning ? (
                        <button
                            onClick={() => onStop(bot.id)}
                            className="p-2 rounded-lg bg-orange-500/10 text-orange-500 hover:bg-orange-500 hover:text-white transition-colors"
                            title="暂停"
                        >
                            <Square className="w-4 h-4" />
                        </button>
                    ) : (
                        <button
                            onClick={() => onStart(bot.id)}
                            className="p-2 rounded-lg bg-green-500/10 text-green-500 hover:bg-green-500 hover:text-white transition-colors"
                            title="启动"
                        >
                            <Play className="w-4 h-4" />
                        </button>
                    )}

                    <button
                        onClick={() => onViewDetails(bot.id)}
                        className="p-2 rounded-lg bg-accent text-accent-foreground hover:bg-primary hover:text-primary-foreground transition-colors"
                        title="详情"
                    >
                        <Info className="w-4 h-4" />
                    </button>

                    <button
                        onClick={() => onDelete(bot.id)}
                        className="p-2 rounded-lg text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors opacity-0 group-hover:opacity-100"
                        title={isRunning ? "强制停止并删除" : "删除"}
                    >
                        <Trash2 className="w-4 h-4" />
                    </button>
                </div>
            </div>

            {isError && (
                <div className="mt-4 p-2 rounded-lg bg-destructive/5 border border-destructive/20 flex items-center gap-2 text-xs text-destructive">
                    <AlertCircle className="w-3.5 h-3.5" />
                    <span>运行时发生异常，请检查 API 密钥或网络。</span>
                </div>
            )}
        </div>
    );
}
