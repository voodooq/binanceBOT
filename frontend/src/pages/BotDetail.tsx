import { useQuery } from "@tanstack/react-query";
import { useParams, useNavigate } from "react-router-dom";
import {
    ChevronLeft,
    Activity,
    TrendingUp,
    History,
    LayoutGrid,
    Zap
} from "lucide-react";
import { api } from "@/lib/api";
import { LiveGridMonitor } from "@/components/LiveGridMonitor";
import { cn } from "@/lib/utils";

export default function BotDetail() {
    const { id } = useParams();
    const navigate = useNavigate();

    const { data: bot, isLoading } = useQuery({
        queryKey: ["bot", id],
        queryFn: async () => {
            const resp = await api.get(`/bots/${id}`);
            return resp.data;
        },
    });

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-full py-20">
                <div className="w-10 h-10 border-4 border-primary/20 border-t-primary rounded-full animate-spin" />
            </div>
        );
    }

    if (!bot) return <div className="p-8 text-center text-muted-foreground">未找到该机器人</div>;

    return (
        <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500 pb-10">
            {/* 头部导航与关键状态 */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                <div className="flex items-center gap-4">
                    <button
                        onClick={() => navigate("/bots")}
                        className="p-2 hover:bg-muted rounded-full transition-colors"
                    >
                        <ChevronLeft className="w-6 h-6" />
                    </button>
                    <div>
                        <div className="flex items-center gap-3">
                            <h1 className="text-2xl font-bold tracking-tight">{bot.name}</h1>
                            <span className={cn(
                                "px-2 py-0.5 rounded text-[10px] font-bold uppercase",
                                bot.status === "RUNNING" ? "bg-green-500/10 text-green-500" : "bg-muted text-muted-foreground"
                            )}>
                                {bot.status}
                            </span>
                        </div>
                        <p className="text-muted-foreground text-sm">{bot.symbol} • {bot.strategy_type}</p>
                    </div>
                </div>

                <div className="flex items-center gap-3">
                    <div className="px-4 py-2 bg-card border border-border rounded-xl">
                        <p className="text-[10px] text-muted-foreground uppercase font-bold">运行状态</p>
                        <p className="text-sm font-bold">{bot.status === 'RUNNING' ? '运行中' : bot.status === 'STOPPED' ? '已停止' : '空闲'}</p>
                    </div>
                    <div className="px-4 py-2 bg-card border border-border rounded-xl">
                        <p className="text-[10px] text-muted-foreground uppercase font-bold">创建时间</p>
                        <p className="text-sm font-bold">{new Date(bot.created_at).toLocaleDateString()}</p>
                    </div>
                </div>
            </div>

            {/* 核心数据卡片 */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="p-6 rounded-2xl bg-card border border-border flex flex-col justify-between h-32">
                    <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-2">
                        <TrendingUp className="w-3 h-3" />
                        已实现收益
                    </p>
                    <div className="flex items-baseline gap-2">
                        <h2 className={cn("text-3xl font-black", parseFloat(bot.total_pnl) >= 0 ? "text-green-500" : "text-red-500")}>
                            {parseFloat(bot.total_pnl) >= 0 ? "+" : ""}{parseFloat(bot.total_pnl).toFixed(4)}
                        </h2>
                        <span className="text-xs font-medium text-muted-foreground">USDT</span>
                    </div>
                </div>

                <div className="p-6 rounded-2xl bg-card border border-border flex flex-col justify-between h-32">
                    <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-2">
                        <Zap className="w-3 h-3" />
                        总投入金额
                    </p>
                    <div className="flex items-baseline gap-2">
                        <h2 className="text-3xl font-black uppercase">$ {parseFloat(bot.total_investment).toFixed(2)}</h2>
                        <span className="text-xs font-medium text-muted-foreground">USDT</span>
                    </div>
                </div>

                {parseFloat(bot.total_investment) > 0 ? (
                    <div className="p-6 rounded-2xl bg-card border border-border flex flex-col justify-between h-32">
                        <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-2">
                            <Activity className="w-3 h-3" />
                            ROI
                        </p>
                        <div className="flex items-baseline gap-2">
                            <h2 className={cn("text-3xl font-black", parseFloat(bot.total_pnl) > 0 ? "text-green-500" : parseFloat(bot.total_pnl) < 0 ? "text-red-500" : "text-zinc-500")}>
                                {parseFloat(bot.total_pnl) > 0 ? "+" : ""}{((parseFloat(bot.total_pnl) / parseFloat(bot.total_investment)) * 100).toFixed(2)}%
                            </h2>
                        </div>
                    </div>
                ) : (
                    <div className="p-6 rounded-2xl bg-card border border-border flex flex-col justify-between h-32 opacity-50">
                        <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-2">
                            <Activity className="w-3 h-3" />
                            ROI
                        </p>
                        <div className="flex items-baseline gap-2">
                            <h2 className="text-3xl font-black text-muted-foreground">--</h2>
                        </div>
                    </div>
                )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">
                {/* 左侧详情与列表 */}
                <div className="lg:col-span-3 space-y-8">
                    {/* 网格参数概览 */}
                    <div className="p-6 rounded-2xl bg-card border border-border">
                        <div className="flex items-center justify-between mb-6">
                            <h3 className="font-bold flex items-center gap-2">
                                <LayoutGrid className="w-4 h-4 text-primary" />
                                策略参数概览
                            </h3>
                        </div>

                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 py-2">
                            <div className="flex flex-col gap-1">
                                <span className="text-xs text-muted-foreground uppercase font-bold">价格下限</span>
                                <span className="text-sm font-mono font-bold">{bot.parameters?.grid_lower_price || '--'}</span>
                            </div>
                            <div className="flex flex-col gap-1">
                                <span className="text-xs text-muted-foreground uppercase font-bold">价格上限</span>
                                <span className="text-sm font-mono font-bold">{bot.parameters?.grid_upper_price || '--'}</span>
                            </div>
                            <div className="flex flex-col gap-1">
                                <span className="text-xs text-muted-foreground uppercase font-bold">网格数量</span>
                                <span className="text-sm font-mono font-bold">{bot.parameters?.grid_count || '--'}</span>
                            </div>
                            <div className="flex flex-col gap-1">
                                <span className="text-xs text-muted-foreground uppercase font-bold">单格投入</span>
                                <span className="text-sm font-mono font-bold">{bot.parameters?.grid_investment_per_grid || '--'}</span>
                            </div>
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 py-2 border-t border-border/50">
                            <div className="flex flex-col gap-1">
                                <span className="text-xs text-muted-foreground uppercase font-bold">止损比例</span>
                                <span className="text-sm font-mono font-bold">{(parseFloat(bot.parameters?.stop_loss_percent || "0") * 100).toFixed(1)}%</span>
                            </div>
                            <div className="flex flex-col gap-1">
                                <span className="text-xs text-muted-foreground uppercase font-bold">目标止盈</span>
                                <span className="text-sm font-mono font-bold">{bot.parameters?.take_profit_amount || '--'} USDT</span>
                            </div>
                            <div className="flex flex-col gap-1">
                                <span className="text-xs text-muted-foreground uppercase font-bold">自适应模式</span>
                                <span className="text-sm font-mono font-bold">{bot.parameters?.adaptive_mode ? 'ON' : 'OFF'}</span>
                            </div>
                        </div>
                    </div>

                    {/* 成交历史占位 */}
                    <div className="p-6 rounded-2xl bg-card border border-border flex flex-col items-center justify-center min-h-[200px]">
                        <History className="w-8 h-8 text-muted-foreground mb-4 opacity-50" />
                        <h3 className="font-bold text-muted-foreground">暂无可用历史明细</h3>
                        <p className="text-xs text-muted-foreground/70 mt-2">成交记录接口暂未接入 V3 引擎</p>
                    </div>
                </div>

                {/* 右侧实时水位监控 */}
                <div className="lg:col-span-2 h-[600px] lg:h-auto lg:min-h-[600px] sticky top-8">
                    <LiveGridMonitor bot={bot} />
                </div>
            </div>
        </div>
    );
}
