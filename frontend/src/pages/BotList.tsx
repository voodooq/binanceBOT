import { useQuery } from "@tanstack/react-query";
import { Plus, RefreshCcw, Search } from "lucide-react";
import { BotCard } from "@/components/BotCard";
import type { BotStatus } from "@/components/BotCard";
import { api } from "@/lib/api";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppStore } from "@/store/useAppStore";

interface Bot {
    id: number;
    name: string;
    symbol: string;
    status: BotStatus;
    total_pnl: string;
    strategy_type: string;
}

export default function BotList() {
    const navigate = useNavigate();
    const [search, setSearch] = useState("");
    const { activeApiKeyId } = useAppStore();

    const { data: bots = [], isLoading, refetch } = useQuery<Bot[]>({
        queryKey: ["bots", activeApiKeyId],
        queryFn: async () => {
            const params = activeApiKeyId ? { api_key_id: activeApiKeyId } : {};
            const response = await api.get("/bots/", { params });
            return response.data;
        },
    });

    const filteredBots = bots.filter(
        (bot) =>
            bot.name.toLowerCase().includes(search.toLowerCase()) ||
            bot.symbol.toLowerCase().includes(search.toLowerCase())
    );

    const handleStart = async (id: number) => {
        try {
            await api.post(`/bots/${id}/start`);
            refetch();
        } catch (error) {
            console.error("启动失败", error);
        }
    };

    const handleStop = async (id: number) => {
        try {
            await api.post(`/bots/${id}/stop`);
            refetch();
        } catch (error) {
            console.error("停止失败", error);
        }
    };

    const handleDelete = async (id: number) => {
        const botToDelete = bots.find(b => b.id === id);
        if (!botToDelete) return;

        if (String(botToDelete.status).toUpperCase() === "RUNNING") {
            if (window.confirm(`[${botToDelete.name}] 正在运行中，您确定要强制停止并彻底删除它吗？`)) {
                try {
                    await api.post(`/bots/${id}/stop`);
                    await api.delete(`/bots/${id}`);
                    refetch();
                } catch (error) {
                    console.error("强制删除失败", error);
                    alert("强制删除过程失败，请检查控制台。");
                }
            }
        } else {
            if (window.confirm("确定要删除这个机器人吗？此操作不可逆。")) {
                try {
                    await api.delete(`/bots/${id}`);
                    refetch();
                } catch (error) {
                    console.error("删除失败", error);
                }
            }
        }
    };

    return (
        <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">机器人管理</h1>
                    <p className="text-muted-foreground">管理并监控您所有的网格机器人实例。</p>
                </div>
                <button
                    onClick={() => navigate("/bots/new")}
                    className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2.5 rounded-xl font-semibold hover:opacity-90 transition-opacity"
                >
                    <Plus className="w-5 h-5" />
                    创建新机器人
                </button>
            </div>

            <div className="flex items-center gap-4">
                <div className="relative flex-1 max-w-sm">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <input
                        type="text"
                        placeholder="搜索名称或币种..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="w-full pl-10 pr-4 py-2 bg-card border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
                    />
                </div>
                <button
                    onClick={() => refetch()}
                    className="p-2.5 rounded-xl bg-card border border-border text-muted-foreground hover:text-foreground transition-all"
                    title="刷新列表"
                >
                    <RefreshCcw className={cn("w-5 h-5", isLoading && "animate-spin")} />
                </button>
            </div>

            {isLoading && bots.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-20 bg-card/50 rounded-3xl border border-dashed border-border">
                    <div className="w-12 h-12 border-4 border-primary/20 border-t-primary rounded-full animate-spin mb-4" />
                    <p className="text-muted-foreground italic">正在拉取机器人数据...</p>
                </div>
            ) : filteredBots.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {filteredBots.map((bot) => (
                        <BotCard
                            key={bot.id}
                            bot={bot}
                            onStart={handleStart}
                            onStop={handleStop}
                            onDelete={handleDelete}
                            onViewDetails={(id) => navigate(`/bots/${id}`)}
                        />
                    ))}
                </div>
            ) : (
                <div className="flex flex-col items-center justify-center py-20 bg-card/50 rounded-3xl border border-dashed border-border">
                    <div className="p-4 bg-muted rounded-full mb-4">
                        <Plus className="w-8 h-8 text-muted-foreground" />
                    </div>
                    <h3 className="text-lg font-semibold">暂无匹配的机器人</h3>
                    <p className="text-muted-foreground mt-1 max-w-xs text-center text-sm">
                        您还没有创建任何机器人，或者搜索条件没有结果。点击右上角按钮开始您的交易之旅。
                    </p>
                </div>
            )}
        </div>
    );
}

// 辅助函数 (由于无法直接在 write_to_file 外部引用 lib/utils，此处 inline 或假设全局)
function cn(...inputs: any[]) {
    return inputs.filter(Boolean).join(" ");
}
