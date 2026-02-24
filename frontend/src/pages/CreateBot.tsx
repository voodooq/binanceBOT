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
    Info,
    TrendingUp,
    Shield,
    Activity
} from "lucide-react";

const TOP_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT"
];

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
        exchange: "Binance", // Added default to show in preview
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

    // 实时获取选中交易对的价格
    const { data: marketData, isLoading: isPriceLoading } = useQuery({
        queryKey: ["market-price", formData.symbol],
        queryFn: async () => {
            const resp = await api.get(`/market/price?symbol=${formData.symbol}`);
            return resp.data;
        },
        staleTime: 10000, // 10秒内不重复请求
    });

    const currentPrice = marketData?.price ? parseFloat(marketData.price) : null;

    // 处理 API Key 切换事件，同步推断环境
    const handleKeyChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
        const id = e.target.value;
        const selectedKey = keys.find((k: any) => k.id.toString() === id);
        setFormData({
            ...formData,
            api_key_id: id,
            is_testnet: selectedKey ? selectedKey.is_testnet : true,
            exchange: selectedKey ? selectedKey.exchange : "Binance"
        });
    };

    // 一键填充推荐策略
    const applyStrategy = (type: "conservative" | "moderate" | "aggressive") => {
        if (!currentPrice) {
            alert("正在获取实时价格，请稍等...");
            return;
        }

        let lowerMultiplier, upperMultiplier, gridCount, stopLoss;

        switch (type) {
            case "conservative": // 保守: 宽幅网格，低止损
                lowerMultiplier = 0.80; // -20%
                upperMultiplier = 1.20; // +20%
                gridCount = 15;
                stopLoss = 0.25;
                break;
            case "moderate": // 稳健: 中等网格
                lowerMultiplier = 0.85; // -15%
                upperMultiplier = 1.15; // +15%
                gridCount = 25;
                stopLoss = 0.20;
                break;
            case "aggressive": // 激进: 窄幅高频
                lowerMultiplier = 0.90; // -10%
                upperMultiplier = 1.10; // +10%
                gridCount = 40;
                stopLoss = 0.15;
                break;
        }

        setFormData(prev => ({
            ...prev,
            parameters: {
                ...prev.parameters,
                grid_lower_price: (currentPrice * lowerMultiplier).toFixed(2),
                grid_upper_price: (currentPrice * upperMultiplier).toFixed(2),
                grid_count: gridCount,
                stop_loss_percent: stopLoss,
            }
        }));
    };

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
                                <div className="flex justify-between items-center ml-1">
                                    <label className="text-xs font-bold uppercase">交易对 (Symbol)</label>
                                    {isPriceLoading ? (
                                        <span className="text-[10px] text-muted-foreground animate-pulse">获取报价中...</span>
                                    ) : currentPrice ? (
                                        <span className="text-[10px] font-mono text-green-500 font-bold">${currentPrice}</span>
                                    ) : null}
                                </div>
                                <select
                                    required
                                    value={formData.symbol}
                                    onChange={(e) => setFormData({ ...formData, symbol: e.target.value })}
                                    className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:ring-2 focus:ring-primary/20 outline-none transition-all cursor-pointer font-bold"
                                >
                                    {TOP_SYMBOLS.map(sym => (
                                        <option key={sym} value={sym}>{sym}</option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-xs font-bold uppercase ml-1">API 密钥绑定</label>
                                <select
                                    required
                                    value={formData.api_key_id}
                                    onChange={handleKeyChange}
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
                        <div className="flex items-center justify-between mb-2">
                            <h3 className="text-sm font-bold uppercase text-muted-foreground flex items-center gap-2">
                                <Zap className="w-4 h-4" />
                                策略深度参数 (网格策略)
                            </h3>
                            {/* 一键推荐 */}
                            <div className="flex gap-2">
                                <button
                                    type="button"
                                    onClick={() => applyStrategy("conservative")}
                                    className="px-3 py-1 text-[10px] font-bold rounded-full bg-blue-500/10 text-blue-500 hover:bg-blue-500/20 transition-colors flex items-center gap-1"
                                >
                                    <Shield className="w-3 h-3" /> 保守型
                                </button>
                                <button
                                    type="button"
                                    onClick={() => applyStrategy("moderate")}
                                    className="px-3 py-1 text-[10px] font-bold rounded-full bg-orange-500/10 text-orange-500 hover:bg-orange-500/20 transition-colors flex items-center gap-1"
                                >
                                    <Activity className="w-3 h-3" /> 稳健型
                                </button>
                                <button
                                    type="button"
                                    onClick={() => applyStrategy("aggressive")}
                                    className="px-3 py-1 text-[10px] font-bold rounded-full bg-red-500/10 text-red-500 hover:bg-red-500/20 transition-colors flex items-center gap-1"
                                >
                                    <TrendingUp className="w-3 h-3" /> 激进型
                                </button>
                            </div>
                        </div>

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
                                <span className="text-muted-foreground">拟用账户环境</span>
                                <span className={formData.is_testnet ? "text-amber-500 font-bold" : "text-green-500 font-bold"}>
                                    {formData.exchange} {formData.is_testnet ? "(TESTNET)" : "(REAL)"}
                                </span>
                            </div>
                            <div className="flex justify-between py-2 border-b border-dashed border-border text-sm">
                                <span className="text-muted-foreground">基准参考价</span>
                                <span className="font-mono font-bold text-primary">
                                    {currentPrice ? `$${currentPrice}` : "--"}
                                </span>
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
