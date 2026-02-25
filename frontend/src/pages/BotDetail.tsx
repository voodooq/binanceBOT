import { useQuery } from "@tanstack/react-query";
import { useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
    ChevronLeft,
    Activity,
    TrendingUp,
    History,
    LayoutGrid,
    Zap,
    Flame,
    Loader2,
    ArrowRightLeft
} from "lucide-react";
import { api } from "@/lib/api";
import { LiveGridMonitor } from "@/components/LiveGridMonitor";
import { cn } from "@/lib/utils";
import { useWebSocket } from "@/hooks/useWebSocket";

export default function BotDetail() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [isPanicking, setIsPanicking] = useState(false);
    const [deltaData, setDeltaData] = useState<any>(null);

    const { data: bot, isLoading, refetch } = useQuery({
        queryKey: ["bot", id],
        queryFn: async () => {
            const resp = await api.get(`/bots/${id}`);
            return resp.data;
        },
    });

    const { data: trades = [], isLoading: isLoadingTrades } = useQuery({
        queryKey: ["bot-trades", id],
        queryFn: async () => {
            const resp = await api.get(`/bots/${id}/trades`);
            return resp.data;
        },
        refetchInterval: 15000,
    });

    // 处理实时推送数据 (P3 Delta 监控)
    const handleMessage = useCallback((payload: any) => {
        if (payload.bot_id.toString() !== id) return;

        if (payload.type === "HEDGE_DELTA_UPDATE") {
            setDeltaData(payload.data);
        }
    }, [id]);

    useWebSocket(handleMessage);

    const handlePanicClose = async () => {
        const confirmed = window.confirm(`🔥 🚨 极高危操作警告 🚨 🔥\n\n确定要对 ${bot?.name} (${bot?.symbol}) 立即执行【一键平仓】吗？\n该操作会强制撤销所有网格挂单并市价抛售全部 Base Asset。此操作不可逆！`);
        if (!confirmed) return;
        setIsPanicking(true);
        try {
            const response = await api.post(`/bots/${id}/panic-close`);
            if (response.data?.status === "success") {
                refetch();
            }
        } catch (error: any) {
            console.error("平仓失败", error);
            const msg = error.response?.data?.detail || "发生未知错误";
            alert("平仓失败: " + msg);
        } finally {
            setIsPanicking(false);
        }
    };

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
                                bot.status?.toUpperCase() === "RUNNING" ? "bg-green-500/10 text-green-500" : "bg-muted text-muted-foreground"
                            )}>
                                {bot.status}
                            </span>
                        </div>
                        <p className="text-muted-foreground text-sm">{bot.symbol} • {bot.strategy_type}</p>
                    </div>
                </div>

                <div className="flex items-center gap-3">
                    {bot.status?.toUpperCase() === 'RUNNING' && (
                        <button
                            onClick={handlePanicClose}
                            disabled={isPanicking}
                            className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl shadow-lg shadow-red-500/20 font-bold transition-all disabled:opacity-50"
                        >
                            {isPanicking ? <Loader2 className="w-5 h-5 animate-spin" /> : <Flame className="w-5 h-5" />}
                            一键平仓
                        </button>
                    )}
                    <div className="px-4 py-2 bg-card border border-border rounded-xl">
                        <p className="text-[10px] text-muted-foreground uppercase font-bold">运行状态</p>
                        <p className="text-sm font-bold">{bot.status?.toUpperCase() === 'RUNNING' ? '运行中' : bot.status?.toUpperCase() === 'STOPPED' ? '已停止' : '空闲'}</p>
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

                {/* P3: 对冲策略专属状态卡片 */}
                {bot.strategy_type === "hedge" && (
                    <div className="p-6 rounded-2xl bg-primary/5 border border-primary/20 flex flex-col justify-between h-32 md:col-span-3">
                        <div className="flex justify-between items-start">
                            <p className="text-xs font-bold text-primary uppercase tracking-widest flex items-center gap-2">
                                <ArrowRightLeft className="w-3 h-3" />
                                Delta 偏离度监控
                            </p>
                            <span className="px-2 py-0.5 rounded bg-green-500/20 text-green-500 text-[10px] font-black">中性平衡中</span>
                        </div>
                        <div className="flex items-end justify-between">
                            <div className="flex items-baseline gap-2">
                                <h2 className="text-3xl font-black text-primary">
                                    {deltaData ? `${(deltaData.deviation_ratio * 100).toFixed(2)}%` : "0.00%"}
                                </h2>
                                <span className="text-xs font-medium text-muted-foreground">偏离</span>
                            </div>
                            <div className="text-right">
                                <p className="text-[10px] text-muted-foreground font-bold uppercase">重平衡阈值</p>
                                <p className="text-sm font-mono font-bold">{(parseFloat(bot.parameters?.rebalance_threshold || "0.005") * 100).toFixed(1)}%</p>
                            </div>
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
                                {bot.strategy_type === 'hedge' ? '对冲对核心参数' : '网格参数概览'}
                            </h3>
                        </div>

                        {bot.strategy_type === 'hedge' ? (
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 py-2">
                                <div className="flex flex-col gap-1">
                                    <span className="text-xs text-muted-foreground uppercase font-bold">目标价值</span>
                                    <span className="text-sm font-mono font-bold">{bot.parameters?.target_notional || '--'} USDT</span>
                                </div>
                                <div className="flex flex-col gap-1">
                                    <span className="text-xs text-muted-foreground uppercase font-bold">平衡阈值</span>
                                    <span className="text-sm font-mono font-bold">{(parseFloat(bot.parameters?.rebalance_threshold || "0") * 100).toFixed(2)}%</span>
                                </div>
                                <div className="flex flex-col gap-1">
                                    <span className="text-xs text-muted-foreground uppercase font-bold">风险保护</span>
                                    <span className="text-sm font-mono font-bold">开启</span>
                                </div>
                                <div className="flex flex-col gap-1">
                                    <span className="text-xs text-muted-foreground uppercase font-bold">对冲乘数</span>
                                    <span className="text-sm font-mono font-bold">1.0x (全对冲)</span>
                                </div>
                            </div>
                        ) : (
                            <>
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
                            </>
                        )}
                    </div>

                    {/* 成交历史 */}
                    <div className="p-6 rounded-2xl bg-card border border-border flex flex-col min-h-[300px]">
                        <h3 className="font-bold flex items-center gap-2 mb-6">
                            <History className="w-4 h-4 text-primary" />
                            近期历史明细
                        </h3>

                        {isLoadingTrades ? (
                            <div className="flex-1 flex flex-col items-center justify-center opacity-50">
                                <div className="w-6 h-6 border-2 border-primary/20 border-t-primary rounded-full animate-spin mb-3" />
                                <span className="text-xs">加载明细中...</span>
                            </div>
                        ) : trades.length > 0 ? (
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm text-left">
                                    <thead className="text-xs text-muted-foreground uppercase bg-muted/50">
                                        <tr>
                                            <th className="px-4 py-3 rounded-l-lg">时间</th>
                                            <th className="px-4 py-3">方向</th>
                                            <th className="px-4 py-3">成交均价</th>
                                            <th className="px-4 py-3">成交数量</th>
                                            <th className="px-4 py-3 text-right rounded-r-lg">实现利润</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-border/50">
                                        {trades.map((trade: any) => (
                                            <tr key={trade.id} className="hover:bg-muted/20 transition-colors">
                                                <td className="px-4 py-3 font-mono text-xs whitespace-nowrap">
                                                    {new Date(trade.created_at).toLocaleString()}
                                                </td>
                                                <td className="px-4 py-3">
                                                    <span className={cn(
                                                        "px-2 py-0.5 rounded text-[10px] font-bold uppercase",
                                                        trade.side === "BUY" ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"
                                                    )}>
                                                        {trade.side === "BUY" ? "买入" : "卖出"}
                                                    </span>
                                                </td>
                                                <td className="px-4 py-3 font-mono">
                                                    {parseFloat(trade.price).toFixed(4)}
                                                </td>
                                                <td className="px-4 py-3 font-mono text-muted-foreground">
                                                    {parseFloat(trade.qty).toString()}
                                                </td>
                                                <td className="px-4 py-3 text-right">
                                                    {parseFloat(trade.realized_profit) !== 0 ? (
                                                        <span className={cn(
                                                            "font-mono font-bold",
                                                            parseFloat(trade.realized_profit) > 0 ? "text-green-500" : "text-red-500"
                                                        )}>
                                                            {parseFloat(trade.realized_profit) > 0 ? "+" : ""}{parseFloat(trade.realized_profit).toFixed(4)} USDT
                                                        </span>
                                                    ) : (
                                                        <span className="text-muted-foreground font-mono">--</span>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        ) : (
                            <div className="flex-1 flex flex-col items-center justify-center opacity-50 border border-dashed border-border rounded-xl bg-muted/20">
                                <History className="w-8 h-8 mb-3 opacity-50 text-muted-foreground" />
                                <span className="text-sm font-bold">暂无成交记录</span>
                                <span className="text-[10px] text-muted-foreground mt-1">引擎启动或行情波动后将在此展示交易流水</span>
                            </div>
                        )}
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
