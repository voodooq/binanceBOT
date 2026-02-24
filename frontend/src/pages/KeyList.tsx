import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Key, Plus, Trash2, ShieldCheck, AlertTriangle } from "lucide-react";
import { api } from "@/lib/api";
import { useState } from "react";

interface ApiKey {
    id: number;
    exchange: string;
    api_key: string;
    is_testnet: boolean;
}

export default function KeyList() {
    const queryClient = useQueryClient();
    const [showAdd, setShowAdd] = useState(false);
    const [newKey, setNewKey] = useState({
        api_key: "",
        api_secret: "",
        is_testnet: true,
    });

    const { data: keys = [], isLoading } = useQuery<ApiKey[]>({
        queryKey: ["api-keys"],
        queryFn: async () => {
            const response = await api.get("/keys/");
            return response.data;
        },
    });

    const addMutation = useMutation({
        mutationFn: async (data: typeof newKey) => {
            return await api.post("/keys/", data);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["api-keys"] });
            setShowAdd(false);
            setNewKey({ api_key: "", api_secret: "", is_testnet: true });
        },
    });

    const deleteMutation = useMutation({
        mutationFn: async (id: number) => {
            return await api.delete(`/keys/${id}`);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["api-keys"] });
        },
    });

    return (
        <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">API 密钥管理</h1>
                    <p className="text-muted-foreground">绑定并管理您的交易所 API 凭证，所有密钥在落地前均已加密。</p>
                </div>
                {!showAdd && (
                    <button
                        onClick={() => setShowAdd(true)}
                        className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2.5 rounded-xl font-semibold hover:opacity-90 transition-opacity"
                    >
                        <Plus className="w-5 h-5" />
                        绑定新密钥
                    </button>
                )}
            </div>

            {showAdd && (
                <div className="p-6 rounded-2xl bg-card border-2 border-primary/20 shadow-lg animate-in zoom-in-95 duration-200">
                    <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                        <ShieldCheck className="w-5 h-5 text-primary" />
                        绑定 Binance API 密钥
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <label className="text-xs font-bold text-muted-foreground uppercase">API Key</label>
                            <input
                                type="text"
                                value={newKey.api_key}
                                onChange={(e) => setNewKey({ ...newKey, api_key: e.target.value })}
                                placeholder="请输入公钥..."
                                className="w-full px-4 py-2 bg-background border border-border rounded-lg text-sm focus:ring-2 focus:ring-primary/20 outline-none transition-all"
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-xs font-bold text-muted-foreground uppercase">API Secret</label>
                            <input
                                type="password"
                                value={newKey.api_secret}
                                onChange={(e) => setNewKey({ ...newKey, api_secret: e.target.value })}
                                placeholder="请输入私钥 (将加密存储)..."
                                className="w-full px-4 py-2 bg-background border border-border rounded-lg text-sm focus:ring-2 focus:ring-primary/20 outline-none transition-all"
                            />
                        </div>
                    </div>
                    <div className="mt-4 flex items-center gap-6">
                        <label className="flex items-center gap-2 cursor-pointer group">
                            <input
                                type="checkbox"
                                checked={newKey.is_testnet}
                                onChange={(e) => setNewKey({ ...newKey, is_testnet: e.target.checked })}
                                className="w-4 h-4 rounded border-border text-primary focus:ring-primary/20"
                            />
                            <span className="text-sm font-medium group-hover:text-primary transition-colors">使用测试网 (Testnet)</span>
                        </label>
                    </div>
                    <div className="mt-6 flex gap-3 justify-end border-t border-border pt-6">
                        <button
                            onClick={() => setShowAdd(false)}
                            className="px-4 py-2 rounded-lg text-sm font-medium hover:bg-muted transition-colors"
                        >
                            取消
                        </button>
                        <button
                            onClick={() => addMutation.mutate(newKey)}
                            disabled={addMutation.isPending || !newKey.api_key || !newKey.api_secret}
                            className="bg-primary text-primary-foreground px-6 py-2 rounded-lg text-sm font-bold hover:opacity-90 disabled:opacity-50 transition-all flex items-center gap-2"
                        >
                            {addMutation.isPending ? "正在绑定..." : "确认绑定"}
                        </button>
                    </div>
                </div>
            )}

            {isLoading ? (
                <div className="flex items-center justify-center py-20">
                    <div className="w-8 h-8 border-4 border-primary/20 border-t-primary rounded-full animate-spin" />
                </div>
            ) : keys.length > 0 ? (
                <div className="grid grid-cols-1 gap-4">
                    {keys.map((k) => (
                        <div key={k.id} className="p-4 rounded-xl bg-card border border-border flex items-center justify-between group">
                            <div className="flex items-center gap-4">
                                <div className="p-3 bg-muted rounded-xl text-muted-foreground">
                                    <Key className="w-5 h-5" />
                                </div>
                                <div>
                                    <div className="flex items-center gap-2">
                                        <span className="font-bold">{k.exchange.toUpperCase()}</span>
                                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${k.is_testnet ? "bg-amber-500/10 text-amber-500" : "bg-green-500/10 text-green-500"}`}>
                                            {k.is_testnet ? "TESTNET" : "MAINNET"}
                                        </span>
                                    </div>
                                    <p className="text-xs text-muted-foreground mt-0.5 font-mono">{k.api_key.substring(0, 12)}**************************</p>
                                </div>
                            </div>
                            <button
                                onClick={() => {
                                    if (window.confirm("确定要解绑此密钥吗？")) {
                                        deleteMutation.mutate(k.id);
                                    }
                                }}
                                className="p-2 mr-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg opacity-0 group-hover:opacity-100 transition-all"
                            >
                                <Trash2 className="w-4 h-4" />
                            </button>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="flex flex-col items-center justify-center py-16 bg-card/50 rounded-3xl border border-dashed border-border">
                    <div className="p-4 bg-muted rounded-full mb-4">
                        <Key className="w-8 h-8 text-muted-foreground" />
                    </div>
                    <h3 className="text-lg font-semibold">尚未绑定任何交易所</h3>
                    <p className="text-muted-foreground mt-1 max-w-xs text-center text-sm">
                        为了让机器人代表您执行交易，您需要至少绑定一个 Binance API Key。
                    </p>
                </div>
            )}

            <div className="p-4 rounded-xl bg-blue-500/5 border border-blue-500/20 flex gap-3 items-start">
                <AlertTriangle className="w-5 h-5 text-blue-500 shrink-0" />
                <div className="text-xs text-blue-600 dark:text-blue-400 leading-relaxed">
                    <strong>安全事项：</strong> 您的 API Secret 在保存进数据库时会使用您的专属 DEK (数据加密密钥) 进行信封加密。DEK 本身又经过主密钥加密。即使数据库泄露，攻击者也无法在没有主密钥的情况下还原您的 Secret。
                </div>
            </div>
        </div>
    );
}
