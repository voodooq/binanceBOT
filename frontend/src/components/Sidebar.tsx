import { NavLink } from "react-router-dom";
import {
    LayoutDashboard,
    PlayCircle,
    Key,
    Settings,
    LogOut,
    Activity,
    ShieldAlert
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/useAuthStore";

const navItems = [
    { name: "仪表盘", path: "/dashboard", icon: LayoutDashboard },
    { name: "机器人列表", path: "/bots", icon: PlayCircle },
    { name: "API 密钥", path: "/keys", icon: Key },
    { name: "系统状态", path: "/status", icon: Activity },
    { name: "全局配置", path: "/settings", icon: Settings },
];

export function Sidebar() {
    const logout = useAuthStore((state) => state.logout);

    return (
        <div className="flex flex-col h-full w-64 bg-card border-r border-border text-card-foreground">
            <div className="p-6 flex items-center gap-3">
                <div className="p-2 bg-primary rounded-lg">
                    <ShieldAlert className="w-6 h-6 text-primary-foreground" />
                </div>
                <h1 className="text-xl font-bold tracking-tight">BinanceBot V3</h1>
            </div>

            <nav className="flex-1 px-4 space-y-1 mt-4">
                {navItems.map((item) => (
                    <NavLink
                        key={item.path}
                        to={item.path}
                        className={({ isActive }) =>
                            cn(
                                "flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors",
                                isActive
                                    ? "bg-primary text-primary-foreground"
                                    : "hover:bg-accent hover:text-accent-foreground text-muted-foreground"
                            )
                        }
                    >
                        <item.icon className="w-5 h-5" />
                        {item.name}
                    </NavLink>
                ))}
            </nav>

            <div className="p-4 border-t border-border">
                <button
                    onClick={logout}
                    className="flex items-center gap-3 w-full px-4 py-3 rounded-lg text-sm font-medium text-destructive hover:bg-destructive/10 transition-colors"
                >
                    <LogOut className="w-5 h-5" />
                    退出登录
                </button>
            </div>
        </div>
    );
}
