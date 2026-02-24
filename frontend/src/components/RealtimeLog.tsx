import { Terminal, Trash2 } from "lucide-react";
import { useState, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

interface LogEntry {
    timestamp: string;
    level: "INFO" | "WARN" | "ERROR" | "DEBUG" | "SUCCESS";
    message: string;
}

interface RealtimeLogProps {
    botId: number;
}

export function RealtimeLog({ botId }: RealtimeLogProps) {
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const scrollRef = useRef<HTMLDivElement>(null);

    // 模拟 WebSocket 接收日志
    useEffect(() => {
        const timer = setInterval(() => {
            const newLog: LogEntry = {
                timestamp: new Date().toLocaleTimeString(),
                level: Math.random() > 0.8 ? "WARN" : "INFO",
                message: `[Bot ${botId}] 正在扫描盘口深度，当前价位正常运行中...`
            };
            setLogs((prev) => [...prev.slice(-49), newLog]);
        }, 5000);

        return () => clearInterval(timer);
    }, [botId]);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [logs]);

    return (
        <div className="flex flex-col h-full bg-zinc-950 rounded-2xl border border-zinc-800 overflow-hidden font-mono text-xs">
            <div className="flex items-center justify-between px-4 py-3 bg-zinc-900/50 border-b border-zinc-800">
                <div className="flex items-center gap-2 text-zinc-400">
                    <Terminal className="w-4 h-4" />
                    <span className="font-bold uppercase tracking-wider">实时执行日志</span>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setLogs([])}
                        className="p-1.5 hover:bg-zinc-800 rounded text-zinc-500 transition-colors"
                    >
                        <Trash2 className="w-3.5 h-3.5" />
                    </button>
                </div>
            </div>

            <div
                ref={scrollRef}
                className="flex-1 p-4 overflow-y-auto space-y-1 scrollbar-thin scrollbar-thumb-zinc-800"
            >
                {logs.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-zinc-600 italic">
                        等待日志流推送...
                    </div>
                ) : (
                    logs.map((log, i) => (
                        <div key={i} className="flex gap-3 leading-relaxed group">
                            <span className="text-zinc-600 shrink-0">[{log.timestamp}]</span>
                            <span className={cn(
                                "font-bold shrink-0",
                                log.level === "INFO" && "text-blue-400",
                                log.level === "WARN" && "text-amber-400",
                                log.level === "ERROR" && "text-destructive",
                                log.level === "SUCCESS" && "text-green-400"
                            )}>
                                {log.level}
                            </span>
                            <span className="text-zinc-300 break-all">{log.message}</span>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
