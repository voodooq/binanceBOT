import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Bell, User, Wifi, WifiOff } from "lucide-react";
import { useState, useEffect } from "react";

export function AdminLayout() {
    const [isOnline, setIsOnline] = useState(true);

    // 模拟 WebSocket 状态或网络状态
    useEffect(() => {
        const handleOnline = () => setIsOnline(true);
        const handleOffline = () => setIsOnline(false);

        window.addEventListener("online", handleOnline);
        window.addEventListener("offline", handleOffline);

        return () => {
            window.removeEventListener("online", handleOnline);
            window.removeEventListener("offline", handleOffline);
        };
    }, []);

    return (
        <div className="flex h-screen bg-background overflow-hidden">
            {/* 侧边栏 */}
            <Sidebar />

            {/* 主内容区域 */}
            <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
                {/* 顶部状态栏 */}
                <header className="h-16 border-b border-border bg-card flex items-center justify-between px-8 text-card-foreground">
                    <div className="flex items-center gap-4">
                        <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
                            BINANCEBOT CORE V3.0
                        </h2>
                    </div>

                    <div className="flex items-center gap-6">
                        <div className="flex items-center gap-2">
                            {isOnline ? (
                                <div className="flex items-center gap-1.5 text-xs text-green-500 font-medium">
                                    <Wifi className="w-4 h-4" />
                                    <span>已连接服务线</span>
                                </div>
                            ) : (
                                <div className="flex items-center gap-1.5 text-xs text-destructive font-medium">
                                    <WifiOff className="w-4 h-4" />
                                    <span>服务连接已断开</span>
                                </div>
                            )}
                        </div>

                        <div className="h-6 w-px bg-border" />

                        <div className="flex items-center gap-4">
                            <button className="relative p-2 text-muted-foreground hover:text-foreground transition-colors">
                                <Bell className="w-5 h-5" />
                                <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-destructive rounded-full" />
                            </button>
                            <div className="flex items-center gap-3 pl-2 group cursor-pointer border-l border-transparent hover:border-border transition-all">
                                <div className="flex flex-col items-end">
                                    <span className="text-xs font-semibold">管理员</span>
                                    <span className="text-[10px] text-muted-foreground">admin@binancebot.io</span>
                                </div>
                                <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center text-accent-foreground border border-border">
                                    <User className="w-4 h-4" />
                                </div>
                            </div>
                        </div>
                    </div>
                </header>

                {/* 内容滚体区域 */}
                <main className="flex-1 overflow-y-auto p-8 bg-zinc-50/50 dark:bg-black/20">
                    <div className="max-w-7xl mx-auto h-full">
                        <Outlet />
                    </div>
                </main>
            </div>
        </div>
    );
}
