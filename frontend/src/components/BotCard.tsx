import { Play, Square, AlertCircle, Info, Trash2, Cpu } from "lucide-react";
import { cn } from "@/lib/utils";

export type BotStatus = "RUNNING" | "STOPPED" | "ERROR" | "IDLE";

interface BotCardProps {
    bot: {
        id: number;
        name: string;
        symbol: string;
        status: BotStatus;
        total_pnl: string;
        strategy_type: string;
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

            <div className="flex items-end justify-between mt-6">
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
