import { useState } from "react";
import {
    Play,
    X,
    Activity,
    BarChart3,
    Calendar,
    Zap,
    Loader2
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface BacktestResults {
    symbol: string;
    start_balance: number;
    end_balance: number;
    total_pnl: number;
    roi: number;
    max_drawdown: number;
    trade_count: number;
}

interface BacktestOverlayProps {
    isOpen: boolean;
    onClose: () => void;
    botData: any;
}

export function BacktestOverlay({ isOpen, onClose, botData }: BacktestOverlayProps) {
    const [isLoading, setIsLoading] = useState(false);
    const [results, setResults] = useState<BacktestResults | null>(null);
    const [days, setDays] = useState(7);

    const runBacktest = async () => {
        setIsLoading(true);
        setResults(null);
        try {
            // 注意：因为机器人还没创建，我们需要通过一个特殊的“临时回测”接口或传递完整参数
            // 这里我们假设后端支持传递完整配置进行回测，或者我们直接复用 /run (需要 mock bot_id = 0)
            const resp = await api.post("/backtest/run?bot_id=0", {
                ...botData,
                days: days,
            });
            setResults(resp.data);
        } catch (error) {
            console.error("回测失败:", error);
            alert("回测引擎启动失败，请检查参数合法性");
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <AnimatePresence>
            {isOpen && (
                <div className="fixed inset-0 z-[150] flex items-center justify-center p-4">
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={onClose}
                        className="absolute inset-0 bg-black/60 backdrop-blur-md"
                    />

                    <motion.div
                        initial={{ scale: 0.9, opacity: 0, y: 20 }}
                        animate={{ scale: 1, opacity: 1, y: 0 }}
                        exit={{ scale: 0.9, opacity: 0, y: 20 }}
                        className="relative w-full max-w-2xl bg-card border border-border rounded-3xl shadow-2xl overflow-hidden"
                    >
                        {/* 装饰性背景 */}
                        <div className="absolute top-0 left-0 right-0 h-32 bg-gradient-to-b from-primary/10 to-transparent pointer-events-none" />

                        <div className="p-8 relative">
                            <div className="flex justify-between items-start mb-8">
                                <div className="space-y-1">
                                    <h2 className="text-2xl font-black tracking-tight flex items-center gap-2">
                                        <BarChart3 className="w-6 h-6 text-primary" />
                                        策略性能拟合预检
                                    </h2>
                                    <p className="text-xs text-muted-foreground font-bold uppercase tracking-widest">
                                        Historical Price Action Backtest
                                    </p>
                                </div>
                                <button onClick={onClose} className="p-2 hover:bg-muted rounded-full transition-colors">
                                    <X className="w-6 h-6" />
                                </button>
                            </div>

                            {!results && !isLoading ? (
                                <div className="space-y-8 py-10">
                                    <div className="flex flex-col items-center text-center space-y-4">
                                        <div className="w-16 h-16 bg-primary/10 rounded-full flex items-center justify-center">
                                            <Zap className="w-8 h-8 text-primary animate-pulse" />
                                        </div>
                                        <div className="max-w-xs">
                                            <p className="text-sm font-medium">准备好测试你的参数了吗？</p>
                                            <p className="text-xs text-muted-foreground mt-1">我们将利用最近 7 天的真实行情对你的网格配置进行压力测试。</p>
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-4 justify-center">
                                        <div className="flex items-center gap-2 bg-muted px-4 py-2 rounded-xl border border-border">
                                            <Calendar className="w-4 h-4 text-muted-foreground" />
                                            <select
                                                value={days}
                                                onChange={(e) => setDays(parseInt(e.target.value))}
                                                className="bg-transparent text-sm font-bold outline-none"
                                            >
                                                <option value={3}>最近 3 天</option>
                                                <option value={7}>最近 7 天</option>
                                                <option value={14}>最近 14 天</option>
                                            </select>
                                        </div>
                                        <button
                                            onClick={runBacktest}
                                            className="px-8 py-3 bg-primary text-primary-foreground rounded-xl font-bold shadow-lg shadow-primary/20 flex items-center gap-2 hover:scale-105 transition-all"
                                        >
                                            <Play className="w-4 h-4 fill-current" />
                                            启动拟合
                                        </button>
                                    </div>
                                </div>
                            ) : isLoading ? (
                                <div className="py-20 flex flex-col items-center justify-center space-y-4">
                                    <Loader2 className="w-10 h-10 text-primary animate-spin" />
                                    <div className="text-center">
                                        <p className="text-sm font-bold">正在抓取历史 K 线...</p>
                                        <p className="text-[10px] text-muted-foreground uppercase mt-1 animate-pulse tracking-tighter">Simulating trades at sub-millisecond precision</p>
                                    </div>
                                </div>
                            ) : (
                                <div className="space-y-6 animate-in zoom-in-95 duration-300">
                                    {/* 关键性能指标 */}
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                        <div className="p-4 rounded-2xl bg-muted/50 border border-border/50">
                                            <p className="text-[10px] text-muted-foreground font-bold uppercase mb-1">预估回报率 (ROI)</p>
                                            <p className={cn("text-xl font-black", results!.roi >= 0 ? "text-green-500" : "text-red-500")}>
                                                {results!.roi >= 0 ? "+" : ""}{results!.roi.toFixed(2)}%
                                            </p>
                                        </div>
                                        <div className="p-4 rounded-2xl bg-muted/50 border border-border/50">
                                            <p className="text-[10px] text-muted-foreground font-bold uppercase mb-1">最大回撤</p>
                                            <p className="text-xl font-black text-red-400">-{results!.max_drawdown.toFixed(2)}%</p>
                                        </div>
                                        <div className="p-4 rounded-2xl bg-muted/50 border border-border/50">
                                            <p className="text-[10px] text-muted-foreground font-bold uppercase mb-1">成交频次</p>
                                            <p className="text-xl font-black">{results!.trade_count} <span className="text-xs font-medium opacity-50">次</span></p>
                                        </div>
                                        <div className="p-4 rounded-2xl bg-muted/50 border border-border/50">
                                            <p className="text-[10px] text-muted-foreground font-bold uppercase mb-1">风险系数</p>
                                            <p className="text-xl font-black text-primary">
                                                {(results!.max_drawdown > 15 ? "高" : results!.max_drawdown > 5 ? "中" : "低")}
                                            </p>
                                        </div>
                                    </div>

                                    {/* 对比卡片 */}
                                    <div className="p-6 rounded-2xl bg-black/5 border border-white/5 flex items-center justify-between">
                                        <div className="space-y-1">
                                            <p className="text-xs text-muted-foreground">初始余额</p>
                                            <p className="font-mono font-bold">$ {results!.start_balance.toLocaleString()}</p>
                                        </div>
                                        <div className="h-8 w-px bg-border/50" />
                                        <div className="text-right space-y-1">
                                            <p className="text-xs text-muted-foreground">拟合终值</p>
                                            <p className="font-mono font-bold text-primary">$ {results!.end_balance.toLocaleString()}</p>
                                        </div>
                                    </div>

                                    <div className="p-4 bg-primary/5 rounded-xl flex gap-3 text-xs leading-relaxed italic border border-primary/10">
                                        <Activity className="w-4 h-4 shrink-0 text-primary mt-0.5" />
                                        <span>
                                            回测结论：该配置在最近行情中表现 {results!.roi > 0 ? "稳健" : "较弱"}。{results!.max_drawdown > 10 ? "注意：该参数下回撤较大，请考虑增加网格宽度。" : "回撤控制良好，适合实盘部署。"}
                                        </span>
                                    </div>

                                    <div className="flex gap-4 pt-4">
                                        <button
                                            onClick={() => setResults(null)}
                                            className="flex-1 py-3 bg-muted rounded-xl text-xs font-bold hover:bg-border transition-colors"
                                        >
                                            修改参数
                                        </button>
                                        <button
                                            onClick={onClose}
                                            className="flex-2 px-10 py-3 bg-primary text-primary-foreground rounded-xl text-xs font-black shadow-lg shadow-primary/20 hover:scale-[1.02] active:scale-[0.98] transition-all"
                                        >
                                            采用配置并启动 ENGINE
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>
                    </motion.div>
                </div>
            )}
        </AnimatePresence>
    );
}
