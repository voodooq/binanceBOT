import { useEffect, useRef, useState, useCallback } from "react";

export function useWebSocket(onMessage?: (data: any) => void) {
    const [isConnected, setIsConnected] = useState(false);
    const [lastMessage, setLastMessage] = useState<any>(null);
    const ws = useRef<WebSocket | null>(null);
    const retryCount = useRef(0);

    const connect = useCallback(() => {
        if (ws.current?.readyState === WebSocket.OPEN) return;

        const token = localStorage.getItem("token");
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const host = window.location.host;
        const wsUrl = `${protocol}//${host}/api/v1/ws${token ? `?token=${token}` : ""}`;

        const socket = new WebSocket(wsUrl);

        socket.onopen = () => {
            setIsConnected(true);
            retryCount.current = 0;
        };

        socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                setLastMessage(data);
                if (onMessage) onMessage(data);
            } catch (e) {
                console.warn("WS Message Parse Error:", e);
            }
        };

        socket.onclose = () => {
            setIsConnected(false);
            const delay = Math.min(30000, 1000 * Math.pow(2, retryCount.current));
            setTimeout(() => {
                retryCount.current += 1;
                connect();
            }, delay);
        };

        socket.onerror = (err) => {
            socket.close();
        };

        ws.current = socket;
    }, [onMessage]);

    useEffect(() => {
        connect();
        return () => {
            if (ws.current) {
                ws.current.close();
            }
        };
    }, [connect]);

    return { isConnected, lastMessage };
}
