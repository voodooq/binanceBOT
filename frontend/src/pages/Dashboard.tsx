import { TrendingUp, Wallet, ShieldCheck, Activity } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAppStore } from "@/store/useAppStore";

export default function Dashboard() {
    const { activeApiKeyId } = useAppStore();

    const { data, isLoading } = useQuery({
        queryKey: ["dashboard-overview", activeApiKeyId],
        queryFn: async () => {
            const params = activeApiKeyId ? { api_key_id: activeApiKeyId } : {};
            const resp = await api.get("/dashboard/overview", { params });
            return resp.data;
        }
    });

    const stats = [
        { name: "总投资额", value: isLoading ? "..." : `$${data?.total_investment?.toFixed(2) || "0.00"}`, icon: Wallet, color: "text-blue-500", bg: "bg-blue-500/10" },
        { name: "累计收益", value: isLoading ? "..." : `$${data?.total_profit?.toFixed(2) || "0.00"}`, icon: TrendingUp, color: "text-green-500", bg: "bg-green-500/10" },
        { name: "已激活机器人", value: isLoading ? "..." : `${data?.active_bots || 0}`, icon: Activity, color: "text-purple-500", bg: "bg-purple-500/10" },
        { name: "风险等级", value: isLoading ? "..." : (data?.risk_level || "未知"), icon: ShieldCheck, color: "text-amber-500", bg: "bg-amber-500/10" },
    ];

    return (
        <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div>
                <h1 className="text-2xl font-bold tracking-tight">概览仪表盘</h1>
                <p className="text-muted-foreground">欢迎回来，您的交易系统目前一切正常。</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                {stats.map((stat) => (
                    <div key={stat.name} className="p-6 rounded-2xl bg-card border border-border shadow-sm flex items-start justify-between">
                        <div>
                            <p className="text-xs font-medium text-muted-foreground uppercase">{stat.name}</p>
                            <h3 className="text-2xl font-bold mt-1">{stat.value}</h3>
                        </div>
                        <div className={`p-2 rounded-xl ${stat.bg} ${stat.color}`}>
                            <stat.icon className="w-6 h-6" />
                        </div>
                    </div>
                ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 p-6 rounded-2xl bg-card border border-border shadow-sm">
                    <h3 className="text-lg font-semibold mb-6 italic">收益趋势图 (待对接下个迭代)</h3>
                    <div className="h-[300px] w-full bg-accent/30 rounded-xl flex items-center justify-center border border-dashed border-border">
                        <p className="text-muted-foreground text-sm">图表绘制模块准备中...</p>
                    </div>
                </div>

                <div className="p-6 rounded-2xl bg-card border border-border shadow-sm">
                    <h3 className="text-lg font-semibold mb-6">快速指引</h3>
                    <ul className="space-y-4">
                        <li className="flex items-center gap-3 text-sm">
                            <div className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center text-[10px] font-bold">1</div>
                            <span>添加交易所 API 密钥</span>
                        </li>
                        <li className="flex items-center gap-3 text-sm">
                            <div className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center text-[10px] font-bold">2</div>
                            <span>创建一个网格交易机器人</span>
                        </li>
                        <li className="flex items-center gap-3 text-sm">
                            <div className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center text-[10px] font-bold">3</div>
                            <span>选择运行策略并启动</span>
                        </li>
                    </ul>
                </div>
            </div>
        </div>
    );
}
