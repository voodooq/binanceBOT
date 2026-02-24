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
import { RealtimeLog } from "@/components/RealtimeLog";
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
                        <p className="text-[10px] text-muted-foreground uppercase font-bold">运行天数</p>
                        <p className="text-sm font-bold">12 天</p>
                    </div>
                    <div className="px-4 py-2 bg-card border border-border rounded-xl">
                        <p className="text-[10px] text-muted-foreground uppercase font-bold">成交笔数</p>
                        <p className="text-sm font-bold">1,248</p>
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
                        <h2 className="text-3xl font-black text-green-500">+ {bot.total_pnl}</h2>
                        <span className="text-xs font-medium text-muted-foreground">USDT</span>
                    </div>
                </div>

                <div className="p-6 rounded-2xl bg-card border border-border flex flex-col justify-between h-32">
                    <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-2">
                        <Zap className="w-3 h-3" />
                        当前持仓价值
                    </p>
                    <div className="flex items-baseline gap-2">
                        <h2 className="text-3xl font-black uppercase">$ {parseFloat(bot.total_investment) * 0.42}</h2>
                        <span className="text-xs font-medium text-muted-foreground">USDT</span>
                    </div>
                </div>

                <div className="p-6 rounded-2xl bg-card border border-border flex flex-col justify-between h-32">
                    <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-2">
                        <Activity className="w-3 h-3" />
                        ROI
                    </p>
                    <div className="flex items-baseline gap-2">
                        <h2 className="text-3xl font-black text-green-500">12.4%</h2>
                        <span className="text-xs font-medium text-muted-foreground text-green-500">↑</span>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">
                {/* 左侧详情与列表 */}
                <div className="lg:col-span-3 space-y-8">
                    {/* 网格分布预览图占位 */}
                    <div className="p-6 rounded-2xl bg-card border border-border">
                        <div className="flex items-center justify-between mb-6">
                            <h3 className="font-bold flex items-center gap-2">
                                <LayoutGrid className="w-4 h-4 text-primary" />
                                网格挂单分布
                            </h3>
                            <div className="flex gap-2 text-[10px] font-bold">
                                <span className="flex items-center gap-1 text-green-500"><div className="w-2 h-2 rounded-full bg-green-500" /> BUY</span>
                                <span className="flex items-center gap-1 text-red-500"><div className="w-2 h-2 rounded-full bg-red-500" /> SELL</span>
                            </div>
                        </div>

                        <div className="space-y-2 py-4">
                            {/* 模拟网格线 */}
                            {[1, 2, 3, 4, 5].map(i => (
                                <div key={i} className="flex items-center gap-4 group">
                                    <span className="text-[10px] font-mono text-muted-foreground w-12 text-right">45,10{i}</span>
                                    <div className={cn(
                                        "flex-1 h-6 rounded flex items-center px-4 text-[10px] font-bold transition-all",
                                        i < 3 ? "bg-red-500/10 text-red-500 border-l-2 border-red-500 group-hover:bg-red-500/20" :
                                            "bg-green-500/10 text-green-500 border-l-2 border-green-500 group-hover:bg-green-500/20"
                                    )}>
                                        {i < 3 ? "LIMIT_SELL" : "LIMIT_BUY"} • 0.02 BTC
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* 历史成交记录表 */}
                    <div className="p-6 rounded-2xl bg-card border border-border">
                        <h3 className="font-bold flex items-center gap-2 mb-6">
                            <History className="w-4 h-4 text-primary" />
                            最近成交历史
                        </h3>
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="text-muted-foreground text-xs uppercase border-b border-border">
                                        <th className="text-left pb-3 font-bold">类型</th>
                                        <th className="text-left pb-3 font-bold">价格</th>
                                        <th className="text-left pb-3 font-bold">数量</th>
                                        <th className="text-right pb-3 font-bold">时间</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-border">
                                    {[1, 2, 3].map(i => (
                                        <tr key={i} className="group hover:bg-muted/30 transition-colors">
                                            <td className="py-4">
                                                <span className={i % 2 === 0 ? "text-green-500 font-bold" : "text-red-500 font-bold"}>
                                                    {i % 2 === 0 ? "BUY" : "SELL"}
                                                </span>
                                            </td>
                                            <td className="py-4 font-mono">49,231.00</td>
                                            <td className="py-4 font-mono">0.051</td>
                                            <td className="py-4 text-right text-muted-foreground text-xs">10:45:12</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                {/* 右侧实时日志 */}
                <div className="lg:col-span-2 h-[600px] lg:h-auto lg:min-h-[600px] sticky top-8">
                    <RealtimeLog botId={parseInt(id || "0")} />
                </div>
            </div>
        </div>
    );
}
