import { useEffect } from "react";
import {
    X,
    Bell,
    CheckCheck,
    Info,
    AlertTriangle,
    CheckCircle2,
    XCircle,
    AlertOctagon,
    Clock
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useWebSocket } from "@/hooks/useWebSocket";

interface Notification {
    id: number;
    level: "info" | "success" | "warning" | "error" | "critical";
    title: string;
    message: string;
    is_read: boolean;
    created_at: string;
}

interface NotificationDrawerProps {
    isOpen: boolean;
    onClose: () => void;
    onUnreadChange?: (count: number) => void;
}

const LEVEL_ICONS = {
    info: <Info className="w-4 h-4 text-blue-500" />,
    success: <CheckCircle2 className="w-4 h-4 text-green-500" />,
    warning: <AlertTriangle className="w-4 h-4 text-orange-500" />,
    error: <XCircle className="w-4 h-4 text-red-500" />,
    critical: <AlertOctagon className="w-4 h-4 text-red-600 animate-pulse" />,
};

export function NotificationDrawer({ isOpen, onClose, onUnreadChange }: NotificationDrawerProps) {
    const queryClient = useQueryClient();

    // 1. 加载历史通知
    const { data: notifications = [], refetch } = useQuery({
        queryKey: ["notifications"],
        queryFn: async () => {
            const resp = await api.get("/notifications/");
            return resp.data;
        },
    });

    // 2. 标记已读
    const markReadMutation = useMutation({
        mutationFn: async (id: number) => await api.post(`/notifications/${id}/read`),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
    });

    // 3. 监听实时 WebSocket 通道
    const { lastMessage } = useWebSocket();

    useEffect(() => {
        if (lastMessage?.type === "NOTIFICATION") {
            // 实时追加或重新拉取
            refetch();
            // 如果是在关闭状态下收到消息，可以触发系统提示声或震动（可选）
        }
    }, [lastMessage, refetch]);

    // 计算未读数
    const unreadCount = notifications.filter((n: Notification) => !n.is_read).length;

    useEffect(() => {
        onUnreadChange?.(unreadCount);
    }, [unreadCount, onUnreadChange]);

    return (
        <AnimatePresence>
            {isOpen && (
                <>
                    {/* 背景遮罩 */}
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={onClose}
                        className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[100]"
                    />

                    {/* 侧边抽屉 */}
                    <motion.div
                        initial={{ x: "100%" }}
                        animate={{ x: 0 }}
                        exit={{ x: "100%" }}
                        transition={{ type: "spring", damping: 25, stiffness: 200 }}
                        className="fixed right-0 top-0 bottom-0 w-full max-w-[400px] bg-card border-l border-border shadow-2xl z-[101] flex flex-col"
                    >
                        {/* 头部 */}
                        <div className="p-6 border-b border-border flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <div className="p-2 bg-primary/10 rounded-xl">
                                    <Bell className="w-5 h-5 text-primary" />
                                </div>
                                <div>
                                    <h2 className="font-bold">通知中心</h2>
                                    <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-bold">
                                        Notification Center
                                    </p>
                                </div>
                            </div>
                            <button
                                onClick={onClose}
                                className="p-2 hover:bg-muted rounded-full transition-colors"
                            >
                                <X className="w-5 h-5" />
                            </button>
                        </div>

                        {/* 列表内容 */}
                        <div className="flex-1 overflow-y-auto p-4 space-y-3">
                            {notifications.length === 0 ? (
                                <div className="h-full flex flex-col items-center justify-center text-muted-foreground pb-20">
                                    <Bell className="w-12 h-12 mb-4 opacity-10" />
                                    <p className="text-sm font-medium">暂无通知消息</p>
                                    <p className="text-xs opacity-50">交易动态将在此实时展现</p>
                                </div>
                            ) : (
                                notifications.map((notif: Notification) => (
                                    <motion.div
                                        key={notif.id}
                                        layout
                                        initial={{ opacity: 0, y: 10 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        className={cn(
                                            "p-4 rounded-2xl border transition-all cursor-pointer relative group",
                                            notif.is_read
                                                ? "bg-card border-border/50 opacity-60"
                                                : "bg-accent/50 border-primary/20 shadow-sm hover:border-primary/40"
                                        )}
                                        onClick={() => !notif.is_read && markReadMutation.mutate(notif.id)}
                                    >
                                        <div className="flex gap-3">
                                            <div className="mt-1">{LEVEL_ICONS[notif.level]}</div>
                                            <div className="flex-1 space-y-1">
                                                <div className="flex justify-between items-start">
                                                    <h4 className="text-sm font-bold leading-none">{notif.title}</h4>
                                                    {!notif.is_read && (
                                                        <div className="w-2 h-2 rounded-full bg-primary" />
                                                    )}
                                                </div>
                                                <p className="text-xs text-muted-foreground leading-relaxed">
                                                    {notif.message}
                                                </p>
                                                <div className="flex items-center gap-2 pt-1">
                                                    <Clock className="w-3 h-3 text-muted-foreground/50" />
                                                    <span className="text-[10px] text-muted-foreground/60 font-mono">
                                                        {new Date(notif.created_at).toLocaleString()}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                    </motion.div>
                                ))
                            )}
                        </div>

                        {/* 底部操作 */}
                        {notifications.length > 0 && (
                            <div className="p-4 border-t border-border bg-muted/30">
                                <button
                                    onClick={() => {
                                        // 全标记为已读（后续扩展 API 支持）
                                        notifications.forEach((n: Notification) => !n.is_read && markReadMutation.mutate(n.id))
                                    }}
                                    className="w-full py-2.5 text-xs font-bold flex items-center justify-center gap-2 hover:text-primary transition-colors"
                                >
                                    <CheckCheck className="w-4 h-4" />
                                    全部标记为已读
                                </button>
                            </div>
                        )}
                    </motion.div>
                </>
            )}
        </AnimatePresence>
    );
}
