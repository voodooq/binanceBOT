import { useAuthStore } from "@/store/useAuthStore";
import { LogOut } from "lucide-react";

export default function Dashboard() {
    const { logout } = useAuthStore();

    return (
        <div className="flex flex-col h-screen w-full bg-zinc-950 text-white">
            <header className="flex h-16 items-center justify-between border-b border-zinc-800 px-6">
                <h1 className="text-xl font-bold tracking-tight">BinanceBot V3.0 控制台</h1>
                <button
                    onClick={logout}
                    className="flex items-center text-sm text-zinc-400 hover:text-white transition-colors"
                >
                    <LogOut className="mr-2 h-4 w-4" />
                    退出登录
                </button>
            </header>
            <main className="flex-1 p-6">
                <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6">
                    <h2 className="text-lg font-medium mb-4">欢迎回来</h2>
                    <p className="text-zinc-400">
                        目前此页面还在开发阶段。在 P1/P2 完成后，这里将显示网格机器人的运行状态、收益统计和对冲信息。
                    </p>
                </div>
            </main>
        </div>
    );
}
