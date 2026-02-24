import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useState } from "react";
import {
    ChevronLeft,
    Settings2,
    Zap,
    Target,
    AlertTriangle,
    Info
} from "lucide-react";

export default function CreateBot() {
    const navigate = useNavigate();
    const queryClient = useQueryClient();

    // 获取可用的 API Keys
    const { data: keys = [] } = useQuery({
        queryKey: ["api-keys"],
        queryFn: async () => {
            const resp = await api.get("/keys/");
            return resp.data;
        },
    });

    const [formData, setFormData] = useState({
        name: "",
        symbol: "BTCUSDT",
        api_key_id: "",
        strategy_type: "GRID",
        is_testnet: true,
        total_investment: 100,
        parameters: {
            grid_lower_price: "",
            grid_upper_price: "",
            grid_count: 20,
            grid_investment_per_grid: 10,
            reserve_ratio: 0.05,
            adaptive_mode: false,
            stop_loss_percent: 0.15,
            take_profit_amount: 100,
        }
    });

    const createMutation = useMutation({
        mutationFn: async (data: any) => {
            // 构造符合后端要求的 Payload
            const payload = {
                ...data,
                api_key_id: parseInt(data.api_key_id),
                base_asset: data.symbol.replace("USDT", ""),
                quote_asset: "USDT",
            };
            return await api.post("/bots/", payload);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["bots"] });
            navigate("/bots");
        },
    });

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!formData.api_key_id) {
            alert("请先选择一个绑定的 API Key");
            return;
        }
        createMutation.mutate(formData);
    };

    return (
        <div className="max-w-4xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500 pb-20">
            <div className="flex items-center gap-4">
                <button
                    onClick={() => navigate(-1)}
                    className="p-2 hover:bg-muted rounded-full transition-colors"
                >
                    <ChevronLeft className="w-6 h-6" />
                </button>
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">创建新机器人</h1>
                    <p className="text-muted-foreground text-sm">部署一个新的量化策略实。请仔细核对以下参数。</p>
                </div>
            </div>

            <form onSubmit={handleSubmit} className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* 左侧主要配置 */}
                <div className="lg:col-span-2 space-y-6">
                    <section className="p-6 rounded-2xl bg-card border border-border shadow-sm space-y-4">
                        <h3 className="text-sm font-bold uppercase text-muted-foreground flex items-center gap-2">
                            <Settings2 className="w-4 h-4" />
                            基础信息
                        </h3>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-xs font-bold uppercase ml-1">机器人名称</label>
                                <input
                                    type="text"
                                    required
                                    value={formData.name}
                                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                    placeholder="例如: BTC 震荡网格 01"
                                    className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:ring-2 focus:ring-primary/20 outline-none transition-all"
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-xs font-bold uppercase ml-1">交易对 (Symbol)</label>
                                <input
                                    type="text"
                                    required
                                    value={formData.symbol}
                                    onChange={(e) => setFormData({ ...formData, symbol: e.target.value.toUpperCase() })}
                                    placeholder="BTCUSDT / ETHUSDT"
                                    className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:ring-2 focus:ring-primary/20 outline-none transition-all"
                                />
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-xs font-bold uppercase ml-1">API 密钥绑定</label>
                                <select
                                    required
                                    value={formData.api_key_id}
                                    onChange={(e) => setFormData({ ...formData, api_key_id: e.target.value })}
                                    className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:ring-2 focus:ring-primary/20 outline-none transition-all cursor-pointer"
                                >
                                    <option value="">选择已绑定的 Key...</option>
                                    {keys.map((k: { id: number; exchange: string; api_key: string; is_testnet: boolean }) => (
                                        <option key={k.id} value={k.id}>
                                            {k.exchange} - {k.api_key.substring(0, 8)}... ({k.is_testnet ? "测试网" : "实盘"})
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <div className="space-y-2">
                                <label className="text-xs font-bold uppercase ml-1">投资总额 (USDT)</label>
                                <input
                                    type="number"
                                    required
                                    value={formData.total_investment}
                                    onChange={(e) => setFormData({ ...formData, total_investment: parseFloat(e.target.value) })}
                                    className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:ring-2 focus:ring-primary/20 outline-none transition-all"
                                />
                            </div>
                        </div>
                    </section>

                    <section className="p-6 rounded-2xl bg-card border border-border shadow-sm space-y-6">
                        <h3 className="text-sm font-bold uppercase text-muted-foreground flex items-center gap-2">
                            <Zap className="w-4 h-4" />
                            策略深度参数 (网格策略)
                        </h3>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div className="space-y-2">
                                <label className="text-xs font-bold uppercase ml-1">网格上限价格</label>
                                <input
                                    type="number"
                                    required
                                    value={formData.parameters.grid_upper_price}
                                    onChange={(e) => setFormData({ ...formData, parameters: { ...formData.parameters, grid_upper_price: e.target.value } })}
                                    className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:ring-2 focus:ring-primary/20"
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-xs font-bold uppercase ml-1">网格下限价格</label>
                                <input
                                    type="number"
                                    required
                                    value={formData.parameters.grid_lower_price}
                                    onChange={(e) => setFormData({ ...formData, parameters: { ...formData.parameters, grid_lower_price: e.target.value } })}
                                    className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:ring-2 focus:ring-primary/20"
                                />
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <div className="space-y-2">
                                <label className="text-xs font-bold uppercase ml-1">网格密度 (格数)</label>
                                <input
                                    type="number"
                                    value={formData.parameters.grid_count}
                                    onChange={(e) => setFormData({ ...formData, parameters: { ...formData.parameters, grid_count: parseInt(e.target.value) } })}
                                    className="w-full px-4 py-2 bg-background border border-border rounded-lg"
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-xs font-bold uppercase ml-1">单格投入 (USDT)</label>
                                <input
                                    type="number"
                                    value={formData.parameters.grid_investment_per_grid}
                                    onChange={(e) => setFormData({ ...formData, parameters: { ...formData.parameters, grid_investment_per_grid: parseFloat(e.target.value) } })}
                                    className="w-full px-4 py-2 bg-background border border-border rounded-lg"
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-xs font-bold uppercase ml-1">止损比例 (%)</label>
                                <input
                                    type="number"
                                    step="0.01"
                                    value={formData.parameters.stop_loss_percent}
                                    onChange={(e) => setFormData({ ...formData, parameters: { ...formData.parameters, stop_loss_percent: parseFloat(e.target.value) } })}
                                    className="w-full px-4 py-2 bg-background border border-border rounded-lg"
                                />
                            </div>
                        </div>

                        <div className="p-4 bg-muted/50 rounded-xl flex gap-3 text-xs text-muted-foreground leading-relaxed italic">
                            <Info className="w-4 h-4 shrink-0 text-primary mt-0.5" />
                            <span>
                                等差网格逻辑：将在上限与下限之间均匀分布买单。价格每下跌一个步长触发一次买入，并自动挂出利润卖单。
                            </span>
                        </div>
                    </section>
                </div>

                {/* 右侧边栏：状态摘要与提交 */}
                <div className="space-y-6">
                    <section className="p-6 rounded-2xl bg-card border border-border shadow-sm sticky top-6">
                        <h3 className="text-sm font-bold uppercase text-muted-foreground mb-4">执行预览</h3>

                        <div className="space-y-4">
                            <div className="flex justify-between py-2 border-b border-dashed border-border text-sm">
                                <span className="text-muted-foreground">拟用账户</span>
                                <span className="font-medium">Binance</span>
                            </div>
                            <div className="flex justify-between py-2 border-b border-dashed border-border text-sm">
                                <span className="text-muted-foreground">环境</span>
                                <span className={formData.is_testnet ? "text-amber-500 font-bold" : "text-green-500 font-bold"}>
                                    {formData.is_testnet ? "TESTNET" : "REAL ACCOUNT"}
                                </span>
                            </div>
                            <div className="flex justify-between py-2 border-b border-dashed border-border text-sm">
                                <span className="text-muted-foreground">预估步长</span>
                                <span className="font-medium text-primary">--</span>
                            </div>
                        </div>

                        <div className="mt-8 space-y-3">
                            <button
                                type="submit"
                                disabled={createMutation.isPending}
                                className="w-full bg-primary text-primary-foreground py-4 rounded-xl font-bold hover:opacity-90 transition-all flex items-center justify-center gap-2"
                            >
                                {createMutation.isPending ? "正在部署引擎..." : (
                                    <>
                                        <Target className="w-5 h-5" />
                                        立即创建并启动
                                    </>
                                )}
                            </button>
                            <div className="flex items-center gap-2 text-[10px] text-muted-foreground px-2">
                                <AlertTriangle className="w-3 h-3 shrink-0" />
                                <span>请确保账户内有足够的 {formData.symbol.includes("USDT") ? "USDT" : "基础货币"} 余额。</span>
                            </div>
                        </div>
                    </section>
                </div>
            </form>
        </div>
    );
}
